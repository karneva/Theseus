package com.theseus.api.common.config.security;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.options;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.theseus.api.common.exception.ErrorCode;
import com.theseus.api.domain.auth.token.JwtTokenProvider;
import com.theseus.api.domain.user.entity.SystemRole;
import com.theseus.api.domain.user.entity.User;
import com.theseus.api.domain.user.entity.UserStatus;
import com.theseus.api.domain.user.repository.UserRepository;
import com.theseus.api.support.IntegrationTestSupport;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

/**
 * 보안 필터 단계와 MVC 단계의 실패 응답이 ApiResponse 형식과 올바른 상태 코드로 나가는지 검증합니다.
 */
@AutoConfigureMockMvc
class SecurityErrorResponseIntegrationTest extends IntegrationTestSupport {

	@Autowired
	private MockMvc mockMvc;

	@Autowired
	private UserRepository userRepository;

	@Autowired
	private JwtTokenProvider jwtTokenProvider;

	@Test
	@DisplayName("토큰 없는 요청은 본문 있는 401 ApiResponse로 응답한다")
	void unauthenticatedRequestReturns401Json() throws Exception {
		mockMvc.perform(get("/api/v1/projects"))
			.andExpect(status().isUnauthorized())
			.andExpect(jsonPath("$.isSuccess").value(false))
			.andExpect(jsonPath("$.code").value(ErrorCode.UNAUTHORIZED.getCode()));
	}

	@Test
	@DisplayName("일반 사용자가 SUPER_ADMIN 경로를 호출하면 403 ApiResponse로 응답한다")
	void forbiddenRequestReturns403Json() throws Exception {
		String accessToken = jwtTokenProvider.createAccessToken(saveUser("SEC-403", UserStatus.ACTIVE));

		mockMvc.perform(get("/api/v1/admin/users").header("Authorization", "Bearer " + accessToken))
			.andExpect(status().isForbidden())
			.andExpect(jsonPath("$.isSuccess").value(false))
			.andExpect(jsonPath("$.code").value(ErrorCode.HANDLE_ACCESS_DENIED.getCode()));
	}

	@Test
	@DisplayName("비활성 사용자의 유효한 access token은 인증되지 않는다")
	void inactiveUserTokenIsRejected() throws Exception {
		String accessToken = jwtTokenProvider.createAccessToken(saveUser("SEC-INACTIVE", UserStatus.INACTIVE));

		mockMvc.perform(get("/api/v1/projects").header("Authorization", "Bearer " + accessToken))
			.andExpect(status().isUnauthorized());
	}

	@Test
	@DisplayName("없는 경로는 500이 아니라 404 ApiResponse로 응답한다")
	void unknownPathReturns404() throws Exception {
		String accessToken = jwtTokenProvider.createAccessToken(saveUser("SEC-404", UserStatus.ACTIVE));

		mockMvc.perform(get("/api/v1/not-existing-path").header("Authorization", "Bearer " + accessToken))
			.andExpect(status().isNotFound())
			.andExpect(jsonPath("$.code").value(ErrorCode.RESOURCE_NOT_FOUND.getCode()));
	}

	@Test
	@DisplayName("깨진 JSON 본문은 500이 아니라 400으로 응답한다")
	void malformedJsonReturns400() throws Exception {
		mockMvc.perform(
			post("/api/v1/auth/login").contentType(MediaType.APPLICATION_JSON).content("{broken")
		)
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.code").value(ErrorCode.INVALID_INPUT_VALUE.getCode()));
	}

	@Test
	@DisplayName("actuator health는 인증 없이 조회할 수 있다")
	void healthIsPublic() throws Exception {
		mockMvc.perform(get("/actuator/health")).andExpect(status().isOk());
	}

	@Test
	@DisplayName("ALLOWED_ORIGINS가 비어 있으면 cross-origin preflight에 CORS 허용 헤더를 주지 않는다")
	void corsIsDisabledWhenOriginsAreEmpty() throws Exception {
		mockMvc.perform(
			options("/api/v1/projects")
				.header("Origin", "https://other.example.test")
				.header("Access-Control-Request-Method", "GET")
		)
			.andExpect(header().doesNotExist("Access-Control-Allow-Origin"));
	}

	private User saveUser(String employeeNumber, UserStatus status) {
		return userRepository.save(
			User.builder()
				.employeeNumber(employeeNumber)
				.name("Security Test " + employeeNumber)
				.password("not-used")
				.systemRole(SystemRole.USER)
				.status(status)
				.build()
		);
	}
}
