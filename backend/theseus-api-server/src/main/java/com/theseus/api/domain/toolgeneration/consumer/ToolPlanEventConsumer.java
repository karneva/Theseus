package com.theseus.api.domain.toolgeneration.consumer;

import com.theseus.api.domain.toolgeneration.event.ToolPlanEvent;
import com.theseus.api.domain.toolgeneration.event.ToolPlanEventType;
import com.theseus.api.domain.toolgeneration.service.ToolPlanEventService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Slf4j
@RequiredArgsConstructor
@Component
public class ToolPlanEventConsumer {

	/**
	 * Core 서버에서 돌아온 PLAN 진행·완료·실패 이벤트를 종류별 저장 로직으로 전달합니다.
	 * 저장된 상태는 Redis와 SSE를 거쳐 해당 runId를 구독 중인 화면에 전달됩니다.
	 */

	private final ToolPlanEventService toolPlanEventService;

	@KafkaListener(
		topics = "${theseus.kafka.topics.tool-plan-event}",
		containerFactory = "toolPlanKafkaListenerContainerFactory"
	)
	public void consume(ToolPlanEvent event) {
		if (event == null) {
			log.warn(">>>> Empty ToolPlan event skipped.");
			return;
		}

		// 하나의 결과 토픽을 사용하므로 eventType으로 실제 처리 경로를 분기합니다.
		ToolPlanEventType eventType = event.getEventTypeValue();
		try {
			if (ToolPlanEventType.TOOL_PLAN_COMPLETED.equals(eventType)) {
				toolPlanEventService.handleCompleted(event);
				return;
			}
			if (ToolPlanEventType.TOOL_PLAN_SKIPPED.equals(eventType)) {
				toolPlanEventService.handleSkipped(event);
				return;
			}
			if (ToolPlanEventType.TOOL_PLAN_FAILED.equals(eventType)) {
				toolPlanEventService.handleFailed(event);
				return;
			}
			if (ToolPlanEventType.PROGRESS.equals(eventType)) {
				toolPlanEventService.handleProgress(event);
				return;
			}
			if (ToolPlanEventType.CHUNK.equals(eventType)) {
				toolPlanEventService.handleChunk(event);
				return;
			}

			log.warn(
				">>>> Unsupported ToolPlan event skipped. runId={}, eventType={}, sequence={}",
				event.getRunId(),
				event.getEventType(),
				event.getEventSequence()
			);
		} catch (Exception exception) {
			log.error(
				">>>> ToolPlan event handling failed. runId={}, eventType={}, sequence={}",
				event.getRunId(),
				event.getEventType(),
				event.getEventSequence(),
				exception
			);
		}
	}
}
