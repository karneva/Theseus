package com.theseus.api.domain.toolgeneration.config;

import com.theseus.api.common.exception.BusinessException;
import com.theseus.api.domain.toolgeneration.event.ToolBuildEvent;
import com.theseus.api.domain.toolgeneration.event.ToolPlanEvent;
import java.util.LinkedHashMap;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.TopicPartition;
import org.apache.kafka.common.serialization.ByteArraySerializer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;
import org.springframework.boot.autoconfigure.kafka.KafkaProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.ConcurrentKafkaListenerContainerFactory;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaOperations;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.CommonErrorHandler;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.kafka.support.ExponentialBackOffWithMaxRetries;
import org.springframework.kafka.support.serializer.ErrorHandlingDeserializer;
import org.springframework.kafka.support.serializer.JsonDeserializer;

/**
 * Core가 발행하는 PLAN/BUILD 결과 이벤트용 Kafka listener 설정입니다.
 *
 * <p>처리 흐름: listener가 예외를 던지면 {@link DefaultErrorHandler}가 지수 백오프로 재시도하고,
 * 재시도를 모두 실패하거나 재시도해도 소용없는 예외(역직렬화 실패, {@link BusinessException})는
 * 원본 토픽 이름 뒤에 {@value #DLT_SUFFIX}를 붙인 DLT로 보낸 뒤 offset을 커밋합니다.
 * 이전에는 consumer가 예외를 삼켜 이벤트가 조용히 사라졌습니다. DLT로 간 Run은
 * ToolPlanRunTimeoutScheduler가 제한 시간 후 FAILED로 정리합니다.
 */
@Slf4j
@Configuration
public class ToolGenerationKafkaConsumerConfig {

	public static final String DLT_SUFFIX = ".DLT";

	private static final String TRUSTED_PACKAGES =
		"com.theseus.api.domain.toolgeneration.event,java.util,java.lang,com.fasterxml.jackson.databind";
	private static final long RETRY_INITIAL_INTERVAL_MILLIS = 1_000L;
	private static final double RETRY_MULTIPLIER = 2.0;
	private static final long RETRY_MAX_INTERVAL_MILLIS = 10_000L;
	private static final int RETRY_MAX_ATTEMPTS = 4;

	@Bean
	public ConcurrentKafkaListenerContainerFactory<
		String,
		ToolPlanEvent
	> toolPlanKafkaListenerContainerFactory(
		KafkaProperties kafkaProperties,
		CommonErrorHandler toolGenerationKafkaErrorHandler
	) {
		return createFactory(ToolPlanEvent.class, kafkaProperties, toolGenerationKafkaErrorHandler);
	}

	@Bean
	public ConcurrentKafkaListenerContainerFactory<
		String,
		ToolBuildEvent
	> toolBuildKafkaListenerContainerFactory(
		KafkaProperties kafkaProperties,
		CommonErrorHandler toolGenerationKafkaErrorHandler
	) {
		return createFactory(ToolBuildEvent.class, kafkaProperties, toolGenerationKafkaErrorHandler);
	}

	/**
	 * 재시도 후 DLT로 보내는 공통 에러 핸들러입니다.
	 * 역직렬화에 실패한 레코드는 값이 원본 byte[]로 복원되므로 byte[] 전용 템플릿으로, 나머지는 JSON 템플릿으로 보냅니다.
	 * DLT 파티션은 -1로 두어 원본 토픽과 파티션 수가 달라도 발행되게 합니다.
	 */
	@Bean
	public CommonErrorHandler toolGenerationKafkaErrorHandler(
		KafkaProperties kafkaProperties,
		KafkaTemplate<String, Object> kafkaTemplate
	) {
		Map<Class<?>, KafkaOperations<?, ?>> templates = new LinkedHashMap<>();
		templates.put(byte[].class, createByteArrayTemplate(kafkaProperties));
		templates.put(Object.class, kafkaTemplate);

		DeadLetterPublishingRecoverer recoverer = new DeadLetterPublishingRecoverer(
			templates,
			(record, exception) -> {
				log.error(
					">>>> Kafka record sent to DLT. topic={}, partition={}, offset={}, key={}",
					record.topic(),
					record.partition(),
					record.offset(),
					record.key(),
					exception
				);
				return new TopicPartition(record.topic() + DLT_SUFFIX, -1);
			}
		);

		ExponentialBackOffWithMaxRetries backOff = new ExponentialBackOffWithMaxRetries(RETRY_MAX_ATTEMPTS);
		backOff.setInitialInterval(RETRY_INITIAL_INTERVAL_MILLIS);
		backOff.setMultiplier(RETRY_MULTIPLIER);
		backOff.setMaxInterval(RETRY_MAX_INTERVAL_MILLIS);

		DefaultErrorHandler errorHandler = new DefaultErrorHandler(recoverer, backOff);
		// 이벤트 내용 자체가 잘못된 비즈니스 검증 실패는 재시도해도 결과가 같으므로 바로 DLT로 보냅니다.
		errorHandler.addNotRetryableExceptions(BusinessException.class);
		return errorHandler;
	}

	/**
	 * spring.kafka.* 설정(bootstrap, group-id, 보안 설정 등)을 그대로 쓰고 값 역직렬화만 이벤트 타입별로 바꿉니다.
	 * JsonDeserializer를 ErrorHandlingDeserializer로 감싸 깨진 메시지가 poll 루프를 막지 않고 에러 핸들러로 가게 합니다.
	 */
	private <T> ConcurrentKafkaListenerContainerFactory<String, T> createFactory(
		Class<T> valueType,
		KafkaProperties kafkaProperties,
		CommonErrorHandler errorHandler
	) {
		Map<String, Object> properties = new LinkedHashMap<>(kafkaProperties.buildConsumerProperties());
		properties.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
		properties.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, ErrorHandlingDeserializer.class);
		properties.put(ErrorHandlingDeserializer.VALUE_DESERIALIZER_CLASS, JsonDeserializer.class);
		properties.put(JsonDeserializer.TRUSTED_PACKAGES, TRUSTED_PACKAGES);
		properties.put(JsonDeserializer.VALUE_DEFAULT_TYPE, valueType.getName());
		properties.put(JsonDeserializer.USE_TYPE_INFO_HEADERS, false);

		ConcurrentKafkaListenerContainerFactory<String, T> factory =
			new ConcurrentKafkaListenerContainerFactory<>();
		factory.setConsumerFactory(new DefaultKafkaConsumerFactory<>(properties));
		factory.setCommonErrorHandler(errorHandler);
		factory.setAutoStartup(kafkaProperties.getListener().isAutoStartup());
		return factory;
	}

	private KafkaTemplate<String, byte[]> createByteArrayTemplate(KafkaProperties kafkaProperties) {
		Map<String, Object> properties = new LinkedHashMap<>(kafkaProperties.buildProducerProperties());
		properties.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
		properties.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, ByteArraySerializer.class);
		return new KafkaTemplate<>(new DefaultKafkaProducerFactory<>(properties));
	}
}
