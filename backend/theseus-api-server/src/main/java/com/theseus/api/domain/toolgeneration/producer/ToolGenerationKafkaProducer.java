package com.theseus.api.domain.toolgeneration.producer;

import com.theseus.api.common.kafka.KafkaTopicProperties;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;
import org.springframework.stereotype.Component;

@Slf4j
@RequiredArgsConstructor
@Component
public class ToolGenerationKafkaProducer {

	/**
	 * PLAN 생성과 Tool 빌드 요청을 작업별 Kafka 토픽으로 비동기 발행합니다.
	 * runId를 key로 사용하므로 동일 작업의 메시지는 같은 파티션에서 순서를 유지합니다.
	 */

	private final KafkaTemplate<String, Object> kafkaTemplate;
	private final KafkaTopicProperties kafkaTopicProperties;

	public CompletableFuture<SendResult<String, Object>> sendToolPlanRequest(
		String key,
		Object event
	) {
		return send(kafkaTopicProperties.toolPlanRequest(), key, event);
	}

	public CompletableFuture<SendResult<String, Object>> sendToolBuildRequest(
		String key,
		Object event
	) {
		return send(kafkaTopicProperties.toolBuildRequest(), key, event);
	}

	private CompletableFuture<SendResult<String, Object>> send(
		String topic,
		String key,
		Object event
	) {
		Objects.requireNonNull(event, "Kafka event must not be null");

		// 호출 스레드를 기다리게 하지 않고 발행 결과는 CompletableFuture로 처리합니다.
		CompletableFuture<SendResult<String, Object>> future = kafkaTemplate.send(topic, key, event);
		future.whenComplete((result, exception) -> {
			if (exception != null) {
				log.warn(
					"Failed to send Kafka message. topic={}, key={}, eventType={}",
					topic,
					key,
					event.getClass().getSimpleName(),
					exception
				);
				return;
			}

			logSuccess(topic, key, result);
		});
		return future;
	}

	private void logSuccess(String topic, String key, SendResult<String, Object> result) {
		if (result == null || result.getRecordMetadata() == null) {
			log.info("Sent Kafka message. topic={}, key={}", topic, key);
			return;
		}

		log.info(
			"Sent Kafka message. topic={}, key={}, partition={}, offset={}",
			topic,
			key,
			result.getRecordMetadata().partition(),
			result.getRecordMetadata().offset()
		);
	}
}
