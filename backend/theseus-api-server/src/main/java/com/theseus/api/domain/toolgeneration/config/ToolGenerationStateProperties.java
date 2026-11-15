package com.theseus.api.domain.toolgeneration.config;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "theseus.tool-generation")
public class ToolGenerationStateProperties {

	private long stateTtlMinutes = 30;
	private long sseTimeoutMillis = 1800000;
	// GENERATING(Core가 처리를 시작함) Run의 제한 시간입니다. 마지막 상태 변경(updatedAt)부터 잽니다.
	private long runTimeoutMinutes = 30;
	// REQUESTED Run의 제한 시간입니다. Core는 요청을 한 번에 하나씩 처리하므로 대기열에 오래 머물 수 있어
	// GENERATING보다 길게 둡니다. 너무 짧으면 Core가 나중에 처리할 Run을 API가 먼저 실패 처리합니다.
	private long requestedRunTimeoutMinutes = 180;
	private long runTimeoutCheckDelayMillis = 60000;
	// Kafka 결과 이벤트가 유실되면 Run이 REQUESTED/GENERATING에 멈추므로 타임아웃 복구는 기본으로 켭니다.
	private boolean runTimeoutSchedulerEnabled = true;
	private int runTimeoutBatchSize = 20;

	public ToolGenerationStateProperties() {}

	public ToolGenerationStateProperties(long stateTtlMinutes, long sseTimeoutMillis) {
		this.stateTtlMinutes = stateTtlMinutes;
		this.sseTimeoutMillis = sseTimeoutMillis;
	}

	public Duration stateTtl() {
		return Duration.ofMinutes(stateTtlMinutes);
	}

	public long sseTimeoutMillis() {
		return sseTimeoutMillis;
	}

	public Duration runTimeout() {
		return Duration.ofMinutes(runTimeoutMinutes);
	}

	public Duration requestedRunTimeout() {
		return Duration.ofMinutes(requestedRunTimeoutMinutes);
	}

	public long getStateTtlMinutes() {
		return stateTtlMinutes;
	}

	public void setStateTtlMinutes(long stateTtlMinutes) {
		this.stateTtlMinutes = stateTtlMinutes;
	}

	public long getSseTimeoutMillis() {
		return sseTimeoutMillis;
	}

	public void setSseTimeoutMillis(long sseTimeoutMillis) {
		this.sseTimeoutMillis = sseTimeoutMillis;
	}

	public long getRunTimeoutMinutes() {
		return runTimeoutMinutes;
	}

	public void setRunTimeoutMinutes(long runTimeoutMinutes) {
		this.runTimeoutMinutes = runTimeoutMinutes;
	}

	public long getRequestedRunTimeoutMinutes() {
		return requestedRunTimeoutMinutes;
	}

	public void setRequestedRunTimeoutMinutes(long requestedRunTimeoutMinutes) {
		this.requestedRunTimeoutMinutes = requestedRunTimeoutMinutes;
	}

	public long getRunTimeoutCheckDelayMillis() {
		return runTimeoutCheckDelayMillis;
	}

	public void setRunTimeoutCheckDelayMillis(long runTimeoutCheckDelayMillis) {
		this.runTimeoutCheckDelayMillis = runTimeoutCheckDelayMillis;
	}

	public boolean isRunTimeoutSchedulerEnabled() {
		return runTimeoutSchedulerEnabled;
	}

	public void setRunTimeoutSchedulerEnabled(boolean runTimeoutSchedulerEnabled) {
		this.runTimeoutSchedulerEnabled = runTimeoutSchedulerEnabled;
	}

	public int runTimeoutBatchSize() {
		return Math.max(1, runTimeoutBatchSize);
	}

	public int getRunTimeoutBatchSize() {
		return runTimeoutBatchSize;
	}

	public void setRunTimeoutBatchSize(int runTimeoutBatchSize) {
		this.runTimeoutBatchSize = runTimeoutBatchSize;
	}
}
