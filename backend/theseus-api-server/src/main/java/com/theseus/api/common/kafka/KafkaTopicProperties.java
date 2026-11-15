package com.theseus.api.common.kafka;

import jakarta.validation.constraints.NotBlank;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/**
 * API와 Core가 공유하는 Tool 생성 Kafka 토픽 이름입니다.
 * application.yaml에서 KAFKA_TOPIC_* 환경변수로 명시적으로 매핑하며, 비어 있으면 기동 시점에 실패시켜
 * send(null, ...) 같은 런타임 오류를 막습니다.
 */
@Validated
@ConfigurationProperties(prefix = "theseus.kafka.topics")
public record KafkaTopicProperties(
	@NotBlank String toolPlanRequest,
	@NotBlank String toolPlanEvent,
	@NotBlank String toolBuildRequest,
	@NotBlank String toolBuildEvent
) {}
