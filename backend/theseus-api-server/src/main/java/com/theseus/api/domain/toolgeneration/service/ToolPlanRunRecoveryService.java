package com.theseus.api.domain.toolgeneration.service;

import com.theseus.api.domain.chat.entity.ChatMessageContentType;
import com.theseus.api.domain.chat.entity.ChatMessageSenderType;
import com.theseus.api.domain.chat.entity.ChatMessageType;
import com.theseus.api.domain.chat.service.ChatMessageService;
import com.theseus.api.domain.tool.entity.ToolPlan;
import com.theseus.api.domain.tool.entity.ToolPlanGroup;
import com.theseus.api.domain.tool.entity.ToolPlanRun;
import com.theseus.api.domain.tool.entity.ToolPlanRunRequestType;
import com.theseus.api.domain.tool.entity.ToolPlanRunStatus;
import com.theseus.api.domain.tool.repository.ToolPlanRunRepository;
import com.theseus.api.domain.toolgeneration.dto.ToolPlanRunState;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 응답이 오지 않거나 요청 발행에 실패한 ToolPlanRun을 실패로 확정하는 공통 경로입니다.
 *
 * <p>Run을 FAILED로 바꾸는 것만으로는 화면이 SSE 타임아웃까지 진행 중으로 남으므로, 실패 확정 시에는 항상
 * (1) 빌드 Run이면 PlanGroup도 FAILED로 바꾸고 (2) 채팅에 SYSTEM_NOTICE를 남기고
 * (3) 커밋 후 Redis/SSE로 failed 상태를 보냅니다.
 */
@Slf4j
@RequiredArgsConstructor
@Service
public class ToolPlanRunRecoveryService {

	private static final String TIMEOUT_ERROR_CODE = "TOOL_PLAN_RUN_TIMEOUT";
	private static final String TIMEOUT_MESSAGE = "ToolPlanRun 처리 시간이 초과되었습니다.";
	private static final String EVENT_TYPE_FAILED = "failed";
	private static final String STATUS_FAILED = "FAILED";

	private final ToolPlanRunRepository toolPlanRunRepository;
	private final ChatMessageService chatMessageService;
	private final ToolPlanRunStatePublisher toolPlanRunStatePublisher;

	/**
	 * 제한 시간을 넘긴 GENERATING/REQUESTED Run을 실패 처리합니다.
	 *
	 * <p>Core는 요청을 순서대로 하나씩 처리하므로 REQUESTED Run은 대기열에서 오래 기다릴 수 있습니다.
	 * 그래서 처리 중(GENERATING)인 Run과 대기 중(REQUESTED)인 Run의 제한 시간을 따로 둡니다.
	 *
	 * @param generatingTimeout GENERATING Run의 제한 시간(마지막 상태 변경부터)
	 * @param requestedTimeout REQUESTED Run의 제한 시간(요청 후 Core가 시작하지 않은 시간)
	 * @param batchSize 한 번에 실패 처리할 최대 Run 수(두 상태 합계)
	 */
	@Transactional
	public int failTimedOutRuns(Duration generatingTimeout, Duration requestedTimeout, int batchSize) {
		if (!isValidTimeout(generatingTimeout) || !isValidTimeout(requestedTimeout)) {
			log.warn(
				">>>> ToolPlanRun timeout recovery skipped. invalidTimeout generating={}, requested={}",
				generatingTimeout,
				requestedTimeout
			);
			return 0;
		}
		if (batchSize <= 0) {
			log.warn(">>>> ToolPlanRun timeout recovery skipped. invalidBatchSize={}", batchSize);
			return 0;
		}

		LocalDateTime now = LocalDateTime.now();
		List<ToolPlanRun> timedOutRuns = new ArrayList<>(toolPlanRunRepository.findTimedOutRunsForUpdate(
			List.of(ToolPlanRunStatus.GENERATING),
			now.minus(generatingTimeout),
			PageRequest.of(0, batchSize)
		));
		int remaining = batchSize - timedOutRuns.size();
		if (remaining > 0) {
			timedOutRuns.addAll(toolPlanRunRepository.findTimedOutRunsForUpdate(
				List.of(ToolPlanRunStatus.REQUESTED),
				now.minus(requestedTimeout),
				PageRequest.of(0, remaining)
			));
		}

		timedOutRuns.forEach(this::failTimedOutRun);
		return timedOutRuns.size();
	}

	private boolean isValidTimeout(Duration timeout) {
		return timeout != null && !timeout.isZero() && !timeout.isNegative();
	}

	/**
	 * 진행 중인 Run을 지정한 오류로 실패 확정합니다. 이미 종료된 Run은 건드리지 않습니다.
	 * 호출자의 트랜잭션에 참여하며 Redis/SSE 전송은 그 트랜잭션이 커밋된 뒤에 일어납니다.
	 */
	@Transactional
	public void failRun(ToolPlanRun toolPlanRun, String errorCode, String errorMessage) {
		if (toolPlanRun.isFinished()) {
			return;
		}
		failRun(
			toolPlanRun,
			errorCode,
			errorMessage,
			"tool-plan-run-failed:" + toolPlanRun.getRunId() + ":system"
		);
		log.warn(
			">>>> ToolPlanRun failed. runId={}, code={}",
			toolPlanRun.getRunId(),
			errorCode
		);
	}

	private void failTimedOutRun(ToolPlanRun toolPlanRun) {
		failRun(toolPlanRun, TIMEOUT_ERROR_CODE, TIMEOUT_MESSAGE, createTimeoutIdempotencyKey(toolPlanRun));
		log.warn(">>>> ToolPlanRun timeout handled. runId={}", toolPlanRun.getRunId());
	}

	private void failRun(
		ToolPlanRun toolPlanRun,
		String errorCode,
		String errorMessage,
		String noticeIdempotencyKey
	) {
		failBuildGroupIfNeeded(toolPlanRun);
		toolPlanRun.fail(errorCode, errorMessage, LocalDateTime.now());
		chatMessageService.saveToolPlanEventMessage(
			toolPlanRun.getChatSession(),
			toolPlanRun.getBaseToolPlan(),
			toolPlanRun,
			ChatMessageSenderType.SYSTEM,
			ChatMessageType.SYSTEM_NOTICE,
			ChatMessageContentType.TEXT,
			createNoticeMessage(errorCode, errorMessage),
			noticeIdempotencyKey
		);
		toolPlanRunStatePublisher.publishFailedAfterCommit(
			createFailedState(toolPlanRun, errorCode, errorMessage)
		);
	}

	private void failBuildGroupIfNeeded(ToolPlanRun toolPlanRun) {
		ToolPlanGroup planGroup = toolPlanRun.getPlanGroup();
		if (
			!ToolPlanRunRequestType.BUILD_TOOL.equals(toolPlanRun.getRequestType()) ||
			planGroup == null ||
			planGroup.isFinished()
		) {
			return;
		}

		planGroup.fail();
	}

	private ToolPlanRunState createFailedState(
		ToolPlanRun toolPlanRun,
		String errorCode,
		String errorMessage
	) {
		ToolPlan baseToolPlan = toolPlanRun.getBaseToolPlan();
		ToolPlanGroup planGroup = toolPlanRun.getPlanGroup();
		if (planGroup == null && baseToolPlan != null) {
			planGroup = baseToolPlan.getPlanGroup();
		}

		return ToolPlanRunState.builder()
			.runId(toolPlanRun.getRunId())
			.projectId(toolPlanRun.getProject().getId())
			.chatSessionId(toolPlanRun.getChatSession().getId())
			.toolPlanGroupId(planGroup == null ? null : planGroup.getId())
			.toolPlanId(baseToolPlan == null ? null : baseToolPlan.getId())
			.planVersion(baseToolPlan == null ? null : baseToolPlan.getPlanVersion())
			.eventType(EVENT_TYPE_FAILED)
			.status(STATUS_FAILED)
			.message(errorMessage)
			.errorCode(errorCode)
			.errorMessage(errorMessage)
			.updatedAt(LocalDateTime.now())
			.build();
	}

	private String createNoticeMessage(String errorCode, String errorMessage) {
		return errorMessage + " code=" + errorCode + ", message=" + errorMessage;
	}

	private String createTimeoutIdempotencyKey(ToolPlanRun toolPlanRun) {
		return "tool-plan-run-timeout:" + toolPlanRun.getRunId() + ":system";
	}
}
