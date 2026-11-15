package com.theseus.api.domain.toolgeneration.consumer;

import com.theseus.api.domain.toolgeneration.event.ToolPlanEvent;
import com.theseus.api.domain.toolgeneration.event.ToolPlanEventType;
import com.theseus.api.domain.toolgeneration.service.ToolPlanEventService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

/**
 * Core 서버에서 돌아온 PLAN 진행·완료·실패 이벤트를 종류별 저장 로직으로 전달합니다.
 * 저장된 상태는 Redis와 SSE를 거쳐 해당 runId를 구독 중인 화면에 전달됩니다.
 *
 * <p>처리 중 예외는 삼키지 않고 다시 던집니다. 재시도와 DLT 전송은
 * {@code ToolGenerationKafkaConsumerConfig}의 에러 핸들러가 맡습니다.
 */
@Slf4j
@RequiredArgsConstructor
@Component
public class ToolPlanEventConsumer {

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
	}
}
