package com.theseus.api.domain.toolgeneration.producer;

import com.theseus.api.domain.tool.service.ToolApprovalService;
import com.theseus.api.domain.toolgeneration.event.ToolBuildKafkaPublishEvent;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

@RequiredArgsConstructor
@Component
public class ToolBuildKafkaPublishListener {

	private final ToolGenerationKafkaProducer toolGenerationKafkaProducer;
	private final ToolApprovalService toolApprovalService;

	@TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
	public void publish(ToolBuildKafkaPublishEvent event) {
		// 승인 결과와 빌드 실행 기록이 커밋된 후에만 Core 서버에 작업을 전달합니다.
		try {
			toolGenerationKafkaProducer
				.sendToolBuildRequest(event.key(), event.payload())
				.whenComplete((result, exception) -> {
					if (exception != null) {
						toolApprovalService.markBuildRunPublishFailed(event.key(), exception);
					}
				});
		} catch (RuntimeException exception) {
			toolApprovalService.markBuildRunPublishFailed(event.key(), exception);
		}
	}
}
