package com.theseus.api.domain.toolgeneration.service;

import com.theseus.api.domain.toolgeneration.dto.ToolPlanRunSseEvent;
import com.theseus.api.domain.toolgeneration.dto.ToolPlanRunState;
import com.theseus.api.domain.toolgeneration.redis.ToolPlanRunStateStore;
import com.theseus.api.domain.toolgeneration.sse.ToolPlanRunSseEmitterRegistry;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

@Slf4j
@RequiredArgsConstructor
@Component
public class ToolPlanRunStatePublisher {

	/**
	 * Kafka로 받은 최신 실행 상태를 Redis에 보관하고 SSE 구독자에게 실시간 전달합니다.
	 * 최종 상태는 DB 커밋 이후에만 노출해 화면과 영속 데이터가 서로 다른 상태가 되지 않게 합니다.
	 */

	private final ToolPlanRunStateStore toolPlanRunStateStore;
	private final ToolPlanRunSseEmitterRegistry toolPlanRunSseEmitterRegistry;

	/**
	 * 진행률 이벤트를 Redis에 저장하고 같은 runId의 SSE 구독자에게 전달합니다.
	 */
	public void publishProgress(ToolPlanRunState state) {
		saveStateAndSend("progress", state, () -> toolPlanRunStateStore.saveProgress(state));
	}

	/**
	 * chunk 이벤트를 Redis에 저장하고 같은 runId의 SSE 구독자에게 전달합니다.
	 */
	public void publishChunk(ToolPlanRunState state) {
		saveStateAndSend("chunk", state, () -> toolPlanRunStateStore.saveChunk(state));
	}

	/**
	 * completed 상태는 DB 커밋 이후 Redis 저장과 SSE 전송을 수행합니다.
	 */
	public void publishCompletedAfterCommit(ToolPlanRunState state) {
		saveStateAfterCommit(() -> {
			if (saveStateSafely("completed", state, () -> toolPlanRunStateStore.saveCompleted(state))) {
				sendStateToSse(state);
				completeSse(state);
			}
		});
	}

	/**
	 * skipped 상태는 DB 커밋 이후 Redis 저장과 SSE 전송을 수행합니다.
	 */
	public void publishSkippedAfterCommit(ToolPlanRunState state) {
		saveStateAfterCommit(() -> {
			if (saveStateSafely("skipped", state, () -> toolPlanRunStateStore.saveSkipped(state))) {
				sendStateToSse(state);
				completeSse(state);
			}
		});
	}

	/**
	 * failed 상태는 DB 커밋 이후 Redis 저장과 SSE 전송을 수행합니다.
	 */
	public void publishFailedAfterCommit(ToolPlanRunState state) {
		saveStateAfterCommit(() -> {
			if (saveStateSafely("failed", state, () -> toolPlanRunStateStore.saveFailed(state))) {
				sendStateToSse(state);
				completeSse(state);
			}
		});
	}

	private void saveStateAndSend(String eventType, ToolPlanRunState state, Runnable saveAction) {
		if (saveStateSafely(eventType, state, saveAction)) {
			sendStateToSse(state);
		}
	}

	private void saveStateAfterCommit(Runnable saveAction) {
		if (!TransactionSynchronizationManager.isSynchronizationActive()) {
			saveAction.run();
			return;
		}

		TransactionSynchronizationManager.registerSynchronization(
			new TransactionSynchronization() {
				@Override
				public void afterCommit() {
					saveAction.run();
				}
			}
		);
	}

	private boolean saveStateSafely(String eventType, ToolPlanRunState state, Runnable saveAction) {
		try {
			saveAction.run();
			return true;
		} catch (RuntimeException exception) {
			log.warn(
				">>>> Failed to save ToolPlanRun Redis state. eventType={}, runId={}",
				eventType,
				state.getRunId(),
				exception
			);
			return false;
		}
	}

	private void sendStateToSse(ToolPlanRunState state) {
		toolPlanRunSseEmitterRegistry.sendToRun(
			state.getProjectId(),
			state.getChatSessionId(),
			state.getRunId(),
			ToolPlanRunSseEvent.createFrom(state)
		);
	}

	private void completeSse(ToolPlanRunState state) {
		toolPlanRunSseEmitterRegistry.complete(
			state.getProjectId(),
			state.getChatSessionId(),
			state.getRunId()
		);
	}
}
