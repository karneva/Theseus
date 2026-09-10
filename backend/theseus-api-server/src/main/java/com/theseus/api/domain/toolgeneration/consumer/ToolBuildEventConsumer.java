package com.theseus.api.domain.toolgeneration.consumer;

import com.theseus.api.domain.toolgeneration.event.ToolBuildEvent;
import com.theseus.api.domain.toolgeneration.event.ToolBuildEventType;
import com.theseus.api.domain.toolgeneration.service.ToolBuildEventService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Slf4j
@RequiredArgsConstructor
@Component
public class ToolBuildEventConsumer {

	/**
	 * Core 서버의 Tool 빌드 상태 이벤트를 소비해 실행 기록과 사용자 화면 상태를 갱신합니다.
	 */

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
		try {
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
		} catch (Exception exception) {
			log.error(
				">>>> ToolBuild event handling failed. runId={}, eventType={}, sequence={}",
				event.getRunId(),
				event.getEventType(),
				event.getEventSequence(),
				exception
			);
		}
	}
}
