package com.theseus.api.domain.tool.entity;

import com.theseus.api.common.exception.BusinessException;
import com.theseus.api.common.exception.ErrorCode;
import com.theseus.api.domain.chat.entity.ChatSession;
import com.theseus.api.domain.project.entity.Project;
import com.theseus.api.domain.project.entity.ProjectMember;
import com.theseus.api.domain.remoteworkspace.entity.RemoteWorkspace;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.ForeignKey;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import java.time.LocalDateTime;
import java.util.Objects;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * Core에 보낸 PLAN 생성/재생성 또는 Tool 빌드 요청 1건의 실행 기록입니다. runId가 Kafka key이자 SSE 구독 키입니다.
 *
 * <p>상태 전이:
 * <pre>
 * REQUESTED --(첫 progress/chunk 이벤트)--> GENERATING
 * REQUESTED|GENERATING --completed--> COMPLETED
 * REQUESTED|GENERATING --skipped----> SKIPPED   (PLAN이 필요 없다고 Core가 판단)
 * REQUESTED|GENERATING --failed-----> FAILED    (Core 실패 이벤트, Kafka 발행 실패, 타임아웃 스케줄러)
 * </pre>
 * COMPLETED/SKIPPED/FAILED는 종료 상태라 이후 상태 변경 메서드는 TOOL_PLAN_RUN_ALREADY_FINISHED를 던집니다.
 * 이벤트 서비스는 종료된 Run에 늦게 도착한 이벤트를 예외 없이 건너뜁니다.
 *
 * <p>중복 제거: Kafka는 at-least-once라 같은 이벤트가 다시 올 수 있습니다. Core는 runId마다 증가하는
 * eventSequence를 붙이고, 처리한 마지막 값을 {@code lastEventSequence}에 저장합니다.
 * {@link #hasProcessedEventSequence(Long)}가 true인 이벤트(같거나 작은 sequence)는 다시 처리하지 않습니다.
 * sequence가 없는 이벤트는 중복 검사 없이 처리합니다.
 */
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Table(
	name = "tool_plan_runs",
	uniqueConstraints = {
		@UniqueConstraint(name = "uk_tool_plan_runs_run_id", columnNames = "run_id"),
	},
	indexes = {
		@Index(
			name = "idx_tool_plan_runs_project_session_status",
			columnList = "project_id, chat_session_id, status"
		),
	}
)
@Entity
public class ToolPlanRun {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "run_id", nullable = false, length = 64)
	private String runId;

	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(
		name = "project_id",
		nullable = false,
		foreignKey = @ForeignKey(name = "fk_tool_plan_runs_project")
	)
	private Project project;

	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(
		name = "chat_session_id",
		nullable = false,
		foreignKey = @ForeignKey(name = "fk_tool_plan_runs_chat_session")
	)
	private ChatSession chatSession;

	@Enumerated(EnumType.STRING)
	@Column(name = "request_type", nullable = false, length = 30)
	private ToolPlanRunRequestType requestType;

	@Enumerated(EnumType.STRING)
	@Column(nullable = false, length = 30, columnDefinition = "VARCHAR(30) DEFAULT 'PLAN'")
	private ToolPlanMode mode;

	@Enumerated(EnumType.STRING)
	@Column(nullable = false, length = 30, columnDefinition = "VARCHAR(30) DEFAULT 'REQUESTED'")
	private ToolPlanRunStatus status;

	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(
		name = "requested_by_project_member_id",
		nullable = false,
		foreignKey = @ForeignKey(name = "fk_tool_plan_runs_requested_by_project_member")
	)
	private ProjectMember requestedByProjectMember;

	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(
		name = "remote_workspace_id",
		foreignKey = @ForeignKey(name = "fk_tool_plan_runs_remote_workspace")
	)
	private RemoteWorkspace remoteWorkspace;

	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(
		name = "base_tool_plan_id",
		foreignKey = @ForeignKey(name = "fk_tool_plan_runs_base_tool_plan")
	)
	private ToolPlan baseToolPlan;

	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(
		name = "result_tool_plan_id",
		foreignKey = @ForeignKey(name = "fk_tool_plan_runs_result_tool_plan")
	)
	private ToolPlan resultToolPlan;

	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(name = "plan_group_id", foreignKey = @ForeignKey(name = "fk_tool_plan_runs_group"))
	private ToolPlanGroup planGroup;

	@Column(name = "user_message_id")
	private Long userMessageId;

	@Column(name = "request_payload_json", columnDefinition = "LONGTEXT")
	private String requestPayloadJson;

	@Column(name = "history_snapshot_json", columnDefinition = "LONGTEXT")
	private String historySnapshotJson;

	@Column(name = "last_event_type", length = 80)
	private String lastEventType;

	@Column(name = "last_event_sequence")
	private Long lastEventSequence;

	@Column(name = "error_code", length = 120)
	private String errorCode;

	@Column(name = "error_message", columnDefinition = "TEXT")
	private String errorMessage;

	@Column(name = "requested_at", nullable = false, updatable = false)
	private LocalDateTime requestedAt;

	@Column(name = "completed_at")
	private LocalDateTime completedAt;

	@Column(name = "created_at", nullable = false, updatable = false)
	private LocalDateTime createdAt;

	@Column(name = "updated_at", nullable = false)
	private LocalDateTime updatedAt;

	@Builder
	private ToolPlanRun(
		String runId,
		Project project,
		ChatSession chatSession,
		ToolPlanRunRequestType requestType,
		ToolPlanMode mode,
		ToolPlanRunStatus status,
		ProjectMember requestedByProjectMember,
		RemoteWorkspace remoteWorkspace,
		ToolPlan baseToolPlan,
		ToolPlan resultToolPlan,
		ToolPlanGroup planGroup,
		Long userMessageId,
		String requestPayloadJson,
		String historySnapshotJson,
		LocalDateTime requestedAt
	) {
		this.runId = validateRunId(runId);
		this.project = Objects.requireNonNull(project, "project must not be null");
		this.chatSession = Objects.requireNonNull(chatSession, "chatSession must not be null");
		this.requestType = Objects.requireNonNull(requestType, "requestType must not be null");
		this.mode = mode == null ? ToolPlanMode.PLAN : mode;
		this.status = status == null ? ToolPlanRunStatus.REQUESTED : status;
		this.requestedByProjectMember = Objects.requireNonNull(
			requestedByProjectMember,
			"requestedByProjectMember must not be null"
		);
		this.remoteWorkspace = remoteWorkspace;
		this.baseToolPlan = baseToolPlan;
		this.resultToolPlan = resultToolPlan;
		this.planGroup = planGroup;
		this.userMessageId = userMessageId;
		this.requestPayloadJson = requestPayloadJson;
		this.historySnapshotJson = historySnapshotJson;
		this.requestedAt = requestedAt == null ? LocalDateTime.now() : requestedAt;
	}

	public void startGenerating() {
		validateNotFinished();
		status = ToolPlanRunStatus.GENERATING;
	}

	public void startGeneratingIfRequested() {
		validateNotFinished();
		if (ToolPlanRunStatus.REQUESTED.equals(status)) {
			status = ToolPlanRunStatus.GENERATING;
		}
	}

	public void complete(ToolPlan resultToolPlan, LocalDateTime completedAt) {
		validateNotFinished();
		this.resultToolPlan = Objects.requireNonNull(resultToolPlan, "resultToolPlan must not be null");
		this.planGroup = resultToolPlan.getPlanGroup();
		this.status = ToolPlanRunStatus.COMPLETED;
		this.completedAt = Objects.requireNonNull(completedAt, "completedAt must not be null");
		clearError();
	}

	public void fail(String errorCode, String errorMessage, LocalDateTime completedAt) {
		validateNotFinished();
		this.status = ToolPlanRunStatus.FAILED;
		this.errorCode = errorCode;
		this.errorMessage = errorMessage;
		this.completedAt = Objects.requireNonNull(completedAt, "completedAt must not be null");
	}

	public void skip(String errorCode, String errorMessage, LocalDateTime completedAt) {
		validateNotFinished();
		this.status = ToolPlanRunStatus.SKIPPED;
		this.errorCode = errorCode;
		this.errorMessage = errorMessage;
		this.completedAt = Objects.requireNonNull(completedAt, "completedAt must not be null");
	}

	public void attachUserMessageId(Long userMessageId) {
		validateNotFinished();
		this.userMessageId = userMessageId;
	}

	public void attachRequestPayload(String requestPayloadJson, String historySnapshotJson) {
		validateNotFinished();
		this.requestPayloadJson = requestPayloadJson;
		this.historySnapshotJson = historySnapshotJson;
	}

	/**
	 * 마지막으로 처리한 이벤트를 기록합니다. sequence가 없는 이벤트는 기존 lastEventSequence를 유지합니다.
	 */
	public void updateLastEvent(String eventType, Long eventSequence) {
		this.lastEventType = eventType;
		if (eventSequence != null) {
			this.lastEventSequence = eventSequence;
		}
	}

	/**
	 * 이미 처리한 sequence(마지막 값 이하)인지 판단합니다. 재전송·중복 이벤트를 건너뛰는 기준입니다.
	 */
	public boolean hasProcessedEventSequence(Long eventSequence) {
		return eventSequence != null && lastEventSequence != null && eventSequence <= lastEventSequence;
	}

	public boolean isFinished() {
		return (
			ToolPlanRunStatus.COMPLETED.equals(status) ||
			ToolPlanRunStatus.FAILED.equals(status) ||
			ToolPlanRunStatus.SKIPPED.equals(status)
		);
	}

	@PrePersist
	private void prePersist() {
		LocalDateTime now = LocalDateTime.now();
		createdAt = now;
		updatedAt = now;
		if (requestedAt == null) {
			requestedAt = now;
		}
	}

	@PreUpdate
	private void preUpdate() {
		updatedAt = LocalDateTime.now();
	}

	private String validateRunId(String runId) {
		if (runId == null || runId.isBlank()) {
			throw BusinessException.of(ErrorCode.TOOL_PLAN_RUN_ID_REQUIRED);
		}

		return runId;
	}

	private void validateNotFinished() {
		if (isFinished()) {
			throw BusinessException.of(ErrorCode.TOOL_PLAN_RUN_ALREADY_FINISHED);
		}
	}

	private void clearError() {
		errorCode = null;
		errorMessage = null;
	}
}
