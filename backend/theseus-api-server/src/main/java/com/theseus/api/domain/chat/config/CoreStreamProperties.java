package com.theseus.api.domain.chat.config;

import jakarta.validation.constraints.NotBlank;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.util.UriUtils;

/**
 * Core 서버 base URL(THESEUS_CORE_BASE_URL)입니다.
 * 운영에서 값이 빠졌을 때 조용히 localhost로 붙지 않도록 기본값 없이 필수로 검증합니다.
 */
@Validated
@ConfigurationProperties(prefix = "theseus.core")
public record CoreStreamProperties(@NotBlank String baseUrl) {

	public URI streamUri(Long projectId, Long sessionId) {
		String normalizedBaseUrl = baseUrl.endsWith("/")
			? baseUrl.substring(0, baseUrl.length() - 1)
			: baseUrl;
		String query = "chat_session_id=%d&project_id=%d".formatted(sessionId, projectId);
		return URI.create(normalizedBaseUrl + "/api/v1/stream?" + query);
	}

	public URI remoteWorkspaceConnectionTestUri() {
		String normalizedBaseUrl = baseUrl.endsWith("/")
			? baseUrl.substring(0, baseUrl.length() - 1)
			: baseUrl;
		return URI.create(normalizedBaseUrl + "/api/v1/remote-workspaces/test-connection");
	}

	public URI deleteToolUri(Long projectId, String toolName) {
		String normalizedBaseUrl = baseUrl.endsWith("/")
			? baseUrl.substring(0, baseUrl.length() - 1)
			: baseUrl;
		return URI.create(
			normalizedBaseUrl + "/api/v1/tools/%d/%s".formatted(projectId, encodePathSegment(toolName))
		);
	}

	public URI updateToolPermissionLevelUri(Long projectId, String toolName) {
		String normalizedBaseUrl = baseUrl.endsWith("/")
			? baseUrl.substring(0, baseUrl.length() - 1)
			: baseUrl;
		return URI.create(
			normalizedBaseUrl +
			"/api/v1/tools/%d/%s/permission-level".formatted(projectId, encodePathSegment(toolName))
		);
	}

	/**
	 * Tool 파일명은 LLM이 만든 값이라 '/', '?', '#', 공백 등이 들어오면 다른 Core 경로를 가리킬 수 있으므로
	 * path segment 단위로 인코딩합니다.
	 */
	private static String encodePathSegment(String value) {
		return UriUtils.encodePathSegment(value, StandardCharsets.UTF_8);
	}
}
