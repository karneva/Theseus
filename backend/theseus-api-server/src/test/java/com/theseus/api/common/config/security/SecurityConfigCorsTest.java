package com.theseus.api.common.config.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;

class SecurityConfigCorsTest {

	@Test
	@DisplayName("ALLOWED_ORIGINS가 비어 있으면 CORS를 끈다")
	void disablesCorsWhenOriginsAreEmpty() {
		SecurityConfig securityConfig = createSecurityConfig(List.of(" ", ""), "prod");

		assertThat(securityConfig.createCorsConfigurationSource()).isNull();
	}

	@Test
	@DisplayName("지정한 origin만 허용하고 다른 origin은 거부한다")
	void allowsOnlyConfiguredOrigins() {
		SecurityConfig securityConfig = createSecurityConfig(List.of("https://app.example.test"), "prod");

		CorsConfiguration configuration = resolve(securityConfig.createCorsConfigurationSource());

		assertThat(configuration.checkOrigin("https://app.example.test")).isEqualTo("https://app.example.test");
		assertThat(configuration.checkOrigin("https://evil.example.test")).isNull();
		assertThat(configuration.getAllowCredentials()).isTrue();
	}

	@Test
	@DisplayName("prod 프로필에서 '*'는 기동 실패로 거부한다")
	void rejectsWildcardInProd() {
		SecurityConfig securityConfig = createSecurityConfig(List.of("*"), "prod");

		assertThatThrownBy(securityConfig::createCorsConfigurationSource)
			.isInstanceOf(IllegalStateException.class)
			.hasMessageContaining("ALLOWED_ORIGINS");
	}

	@Test
	@DisplayName("prod가 아니면 '*'를 origin pattern으로 허용한다")
	void allowsWildcardOutsideProd() {
		SecurityConfig securityConfig = createSecurityConfig(List.of("*"), "local");

		CorsConfiguration configuration = resolve(securityConfig.createCorsConfigurationSource());

		assertThat(configuration.checkOrigin("http://localhost:5173")).isEqualTo("http://localhost:5173");
	}

	private SecurityConfig createSecurityConfig(List<String> origins, String profile) {
		MockEnvironment environment = new MockEnvironment();
		environment.setActiveProfiles(profile);
		return new SecurityConfig(null, null, null, new CorsProperties(origins), environment);
	}

	private CorsConfiguration resolve(CorsConfigurationSource source) {
		MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/projects");
		return source.getCorsConfiguration(request);
	}
}
