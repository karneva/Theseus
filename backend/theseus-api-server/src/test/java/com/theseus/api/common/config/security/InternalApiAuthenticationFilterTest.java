package com.theseus.api.common.config.security;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;

class InternalApiAuthenticationFilterTest {

	private static final String INTERNAL_PATH = "/api/internal/auth/verify";

	@AfterEach
	void tearDown() {
		SecurityContextHolder.clearContext();
	}

	@Test
	@DisplayName("내부 API 키가 일치하면 INTERNAL 권한으로 인증한다")
	void authenticatesMatchingKey() throws Exception {
		InternalApiAuthenticationFilter filter = createFilter("internal-test-key");
		MockHttpServletRequest request = createRequest("internal-test-key");
		MockHttpServletResponse response = new MockHttpServletResponse();
		MockFilterChain chain = new MockFilterChain();

		filter.doFilter(request, response, chain);

		assertThat(chain.getRequest()).isNotNull();
		assertThat(SecurityContextHolder.getContext().getAuthentication().getAuthorities())
			.extracting(Object::toString)
			.containsExactly("ROLE_INTERNAL");
	}

	@Test
	@DisplayName("키가 다르거나 헤더가 없으면 401로 거부한다")
	void rejectsWrongOrMissingKey() throws Exception {
		InternalApiAuthenticationFilter filter = createFilter("internal-test-key");

		for (String requestKey : new String[] { "internal-test-kez", null }) {
			MockHttpServletResponse response = new MockHttpServletResponse();
			MockFilterChain chain = new MockFilterChain();

			filter.doFilter(createRequest(requestKey), response, chain);

			assertThat(response.getStatus()).isEqualTo(401);
			assertThat(response.getContentAsString()).contains("\"isSuccess\":false", "AUTH-004");
			assertThat(chain.getRequest()).isNull();
		}
	}

	@Test
	@DisplayName("서버 키가 비어 있으면 빈 헤더 요청도 거부한다")
	void rejectsWhenServerKeyIsBlank() throws Exception {
		InternalApiAuthenticationFilter filter = createFilter("");
		MockHttpServletResponse response = new MockHttpServletResponse();
		MockFilterChain chain = new MockFilterChain();

		filter.doFilter(createRequest(""), response, chain);

		assertThat(response.getStatus()).isEqualTo(401);
		assertThat(chain.getRequest()).isNull();
	}

	private InternalApiAuthenticationFilter createFilter(String serverKey) {
		InternalApiAuthenticationFilter filter = new InternalApiAuthenticationFilter(
			new SecurityErrorResponseWriter(new ObjectMapper())
		);
		ReflectionTestUtils.setField(filter, "internalApiKey", serverKey);
		return filter;
	}

	private MockHttpServletRequest createRequest(String apiKey) {
		MockHttpServletRequest request = new MockHttpServletRequest("POST", INTERNAL_PATH);
		if (apiKey != null) {
			request.addHeader("X-Internal-Api-Key", apiKey);
		}
		return request;
	}
}
