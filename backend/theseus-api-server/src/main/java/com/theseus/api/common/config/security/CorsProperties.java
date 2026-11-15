package com.theseus.api.common.config.security;

import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.util.StringUtils;

/**
 * 브라우저 CORS 허용 origin 목록입니다(env ALLOWED_ORIGINS, 쉼표 구분).
 * 비어 있으면 nginx가 프런트와 API를 같은 origin으로 서빙한다고 보고 CORS 자체를 끕니다.
 */
@ConfigurationProperties(prefix = "theseus.cors")
public record CorsProperties(List<String> allowedOrigins) {
	static final String WILDCARD = "*";

	public CorsProperties {
		allowedOrigins = allowedOrigins == null
			? List.of()
			: allowedOrigins.stream().map(String::trim).filter(StringUtils::hasText).toList();
	}

	public boolean isEnabled() {
		return !allowedOrigins.isEmpty();
	}

	public boolean containsWildcard() {
		return allowedOrigins.contains(WILDCARD);
	}
}
