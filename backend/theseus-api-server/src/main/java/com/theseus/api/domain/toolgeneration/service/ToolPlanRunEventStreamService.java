package com.theseus.api.domain.toolgeneration.service;

import com.theseus.api.domain.auth.token.AuthenticatedUser;
import com.theseus.api.domain.tool.entity.ToolPlanRun;
import com.theseus.api.domain.toolgeneration.config.ToolGenerationStateProperties;
import com.theseus.api.domain.toolgeneration.dto.ToolPlanRunSseEvent;
import com.theseus.api.domain.toolgeneration.redis.ToolPlanRunStateStore;
import com.theseus.api.domain.toolgeneration.sse.ToolPlanRunSseEmitterRegistry;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Slf4j
@RequiredArgsConstructor
@Transactional(readOnly = true)
@Service
public class ToolPlanRunEventStreamService {

	private final ToolPlanRunAccessService toolPlanRunAccessService;
	private final ToolPlanRunStateStore toolPlanRunStateStore;
	private final ToolGenerationStateProperties properties;
	private final ToolPlanRunSseEmitterRegistry emitterRegistry;

	/**
	 * ToolPlanRun 진행 상태 SSE 구독을 등록하고 Redis 최신 상태가 있으면 즉시 전송합니다.
	 * 순서는 등록 -> connected 이벤트 -> Redis 최신 상태 replay이며, 등록을 먼저 해 replay 직후 도착한
	 * 실시간 이벤트를 놓치지 않습니다. 대신 같은 상태가 replay와 실시간으로 두 번 올 수 있으므로 소비 측은 최신 상태로 덮어쓰는 방식(멱등)으로 처리해야 합니다.
	 */
	public SseEmitter subscribe(
		AuthenticatedUser currentUser,
		Long projectId,
		Long chatSessionId,
		String runId
	) {
		ToolPlanRun toolPlanRun = toolPlanRunAccessService.getAccessibleRun(
			currentUser,
			projectId,
			chatSessionId,
			runId
		);

		SseEmitter emitter = new SseEmitter(properties.sseTimeoutMillis());
		emitterRegistry.register(projectId, chatSessionId, toolPlanRun.getRunId(), emitter);
		emitterRegistry.sendToEmitter(
			projectId,
			chatSessionId,
			toolPlanRun.getRunId(),
			emitter,
			ToolPlanRunSseEvent.connectedOf(projectId, chatSessionId, toolPlanRun.getRunId())
		);
		sendLatestStateIfPresent(projectId, chatSessionId, toolPlanRun.getRunId(), emitter);

		return emitter;
	}

	private void sendLatestStateIfPresent(
		Long projectId,
		Long chatSessionId,
		String runId,
		SseEmitter emitter
	) {
		try {
			toolPlanRunStateStore
				.findByRunId(runId)
				.ifPresent(state ->
					emitterRegistry.sendToEmitter(
						projectId,
						chatSessionId,
						runId,
						emitter,
						ToolPlanRunSseEvent.createReplayFrom(state)
					)
				);
		} catch (RuntimeException exception) {
			log.warn(
				">>>> Failed to replay latest ToolPlanRun state. projectId={}, chatSessionId={}, runId={}",
				projectId,
				chatSessionId,
				runId,
				exception
			);
		}
	}
}
