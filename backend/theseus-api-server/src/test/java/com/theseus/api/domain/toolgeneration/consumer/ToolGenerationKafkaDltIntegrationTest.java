package com.theseus.api.domain.toolgeneration.consumer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

import com.theseus.api.common.exception.BusinessException;
import com.theseus.api.common.exception.ErrorCode;
import com.theseus.api.domain.toolgeneration.event.ToolPlanEvent;
import com.theseus.api.domain.toolgeneration.service.ToolPlanEventService;
import com.theseus.api.support.IntegrationTestSupport;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.admin.AdminClientConfig;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.serialization.ByteArrayDeserializer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.testcontainers.kafka.KafkaContainer;

/**
 * Tool 생성 결과 consumer가 처리할 수 없는 메시지를 삼키지 않고 DLT로 보내는지 실제 Kafka로 검증합니다.
 */
class ToolGenerationKafkaDltIntegrationTest extends IntegrationTestSupport {

	private static final String PLAN_EVENT_TOPIC = "theseus.tool-plan.event";
	private static final String PLAN_EVENT_DLT = PLAN_EVENT_TOPIC + ".DLT";
	private static final Duration DLT_WAIT = Duration.ofSeconds(60);

	private static final KafkaContainer KAFKA = new KafkaContainer("apache/kafka:3.9.1");

	static {
		KAFKA.start();
		createTopics(PLAN_EVENT_TOPIC, PLAN_EVENT_DLT, "theseus.tool-build.event", "theseus.tool-build.event.DLT");
	}

	@MockitoBean
	private ToolPlanEventService toolPlanEventService;

	@DynamicPropertySource
	static void kafkaProperties(DynamicPropertyRegistry registry) {
		registry.add("spring.kafka.bootstrap-servers", KAFKA::getBootstrapServers);
		registry.add("spring.kafka.listener.auto-startup", () -> "true");
		registry.add("spring.kafka.consumer.group-id", () -> "theseus-api-dlt-test");
	}

	@Test
	@DisplayName("역직렬화할 수 없는 메시지는 재시도 없이 원본 바이트 그대로 DLT로 보낸다")
	void poisonPillGoesToDlt() {
		String key = "poison-" + UUID.randomUUID();
		send(PLAN_EVENT_TOPIC, key, "{not-json");

		ConsumerRecord<String, byte[]> dltRecord = awaitDltRecord(key);

		assertThat(new String(dltRecord.value(), StandardCharsets.UTF_8)).isEqualTo("{not-json");
	}

	@Test
	@DisplayName("BusinessException은 재시도하지 않고 한 번 처리한 뒤 DLT로 보낸다")
	void businessExceptionGoesToDltWithoutRetry() {
		doThrow(BusinessException.of(ErrorCode.TOOL_PLAN_EVENT_INVALID))
			.when(toolPlanEventService)
			.handleCompleted(any(ToolPlanEvent.class));
		String key = "business-" + UUID.randomUUID();
		send(
			PLAN_EVENT_TOPIC,
			key,
			"{\"eventType\":\"TOOL_PLAN_COMPLETED\",\"runId\":\"%s\",\"eventSequence\":1}".formatted(key)
		);

		ConsumerRecord<String, byte[]> dltRecord = awaitDltRecord(key);

		assertThat(new String(dltRecord.value(), StandardCharsets.UTF_8)).contains(key);
		verify(toolPlanEventService, times(1)).handleCompleted(any(ToolPlanEvent.class));
	}

	private static void createTopics(String... topics) {
		try (
			AdminClient adminClient = AdminClient.create(
				Map.of(AdminClientConfig.BOOTSTRAP_SERVERS_CONFIG, KAFKA.getBootstrapServers())
			)
		) {
			List<NewTopic> newTopics = new ArrayList<>();
			for (String topic : topics) {
				newTopics.add(new NewTopic(topic, 1, (short) 1));
			}
			adminClient.createTopics(newTopics).all().get();
		} catch (Exception exception) {
			throw new IllegalStateException("Failed to create test topics.", exception);
		}
	}

	private void send(String topic, String key, String value) {
		Map<String, Object> properties = Map.of(
			ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, KAFKA.getBootstrapServers(),
			ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class,
			ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class
		);
		try (KafkaProducer<String, String> producer = new KafkaProducer<>(properties)) {
			producer.send(new ProducerRecord<>(topic, key, value)).get();
		} catch (Exception exception) {
			throw new IllegalStateException("Failed to send test record.", exception);
		}
	}

	private ConsumerRecord<String, byte[]> awaitDltRecord(String key) {
		Map<String, Object> properties = Map.of(
			ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, KAFKA.getBootstrapServers(),
			ConsumerConfig.GROUP_ID_CONFIG, "dlt-reader-" + UUID.randomUUID(),
			ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest",
			ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class,
			ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, ByteArrayDeserializer.class
		);
		try (KafkaConsumer<String, byte[]> consumer = new KafkaConsumer<>(properties)) {
			consumer.subscribe(List.of(PLAN_EVENT_DLT));
			long deadline = System.nanoTime() + DLT_WAIT.toNanos();
			while (System.nanoTime() < deadline) {
				for (ConsumerRecord<String, byte[]> record : consumer.poll(Duration.ofMillis(500))) {
					if (key.equals(record.key())) {
						return record;
					}
				}
			}
		}
		throw new AssertionError("DLT record was not published. key=" + key);
	}
}
