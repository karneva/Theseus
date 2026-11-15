package com.theseus.api.domain.toolgeneration.consumer;

import com.theseus.api.domain.toolgeneration.event.ToolBuildEvent;
import com.theseus.api.domain.toolgeneration.event.ToolBuildEventType;
import com.theseus.api.domain.toolgeneration.service.ToolBuildEventService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

/**
 * Core 서버의 Tool 빌드 상태 이벤트를 소비해 실행 기록과 사용자 화면 상태를 갱신합니다.
 *
 * <p>처리 중 예외는 삼키지 않고 다시 던집니다. 재시도와 DLT 전송은
 * {@code ToolGenerationKafkaConsumerConfig}의 에러 핸들러가 맡습니다.
 */
@Slf4j
@RequiredArgsConstructor
@Component
public class ToolBuildEventConsumer {

	private final ToolBuildEventService toolBuildEventService;

	@KafkaListener(
		topics = "${theseus.kafka.topics.tool-build-event}",
		containerFactory = "toolBuildKafkaListenerContainerFactory"
	)
	public void consume(ToolBuildEvent event) {
		if (event == null) {
			log.warn(">>>> Empty ToolBuild event skipped.");
			return;
		}

		// 진행률과 코드 조각은 계속 전달하고, 완료·실패 이벤트는 실행을 최종 상태로 전환합니다.
		ToolBuildEventType eventType = event.getEventTypeValue();
		if (ToolBuildEventType.TOOL_BUILD_COMPLETED.equals(eventType)) {
			toolBuildEventService.handleCompleted(event);
			return;
		}
		if (ToolBuildEventType.TOOL_BUILD_FAILED.equals(eventType)) {
			toolBuildEventService.handleFailed(event);
			return;
		}
		if (ToolBuildEventType.PROGRESS.equals(eventType)) {
			toolBuildEventService.handleProgress(event);
			return;
		}
		if (ToolBuildEventType.CHUNK.equals(eventType)) {
			toolBuildEventService.handleChunk(event);
			return;
		}

		log.warn(
			">>>> Unsupported ToolBuild event skipped. runId={}, eventType={}, sequence={}",
			event.getRunId(),
			event.getEventType(),
			event.getEventSequence()
		);
	}
}
