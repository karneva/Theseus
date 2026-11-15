package com.theseus.api.common.config.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.theseus.api.common.exception.ErrorCode;
import com.theseus.api.common.response.ApiResponse;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.security.web.access.AccessDeniedHandler;
import org.springframework.stereotype.Component;

/**
 * 컨트롤러에 도달하기 전 보안 필터 단계의 실패(미인증 401, 권한 부족 403, 내부 키 불일치)를
 * GlobalExceptionHandler와 같은 {@link ApiResponse} 실패 형식으로 씁니다.
 * 기본 동작은 본문 없는 403이라 프런트가 만료 토큰과 권한 부족을 구분할 수 없었습니다.
 */
@RequiredArgsConstructor
@Component
public class SecurityErrorResponseWriter {

	private final ObjectMapper objectMapper;

	public AuthenticationEntryPoint authenticationEntryPoint() {
		return (request, response, authException) -> write(response, ErrorCode.UNAUTHORIZED);
	}

	public AccessDeniedHandler accessDeniedHandler() {
		return (request, response, accessDeniedException) ->
			write(response, ErrorCode.HANDLE_ACCESS_DENIED);
	}

	public void write(HttpServletResponse response, ErrorCode errorCode) throws IOException {
		ApiResponse<Void> body = new ApiResponse<>(
			false,
			errorCode.getCode(),
			errorCode.getMessage(),
			null
		);
		response.setStatus(errorCode.getStatus().value());
		response.setContentType(MediaType.APPLICATION_JSON_VALUE);
		response.setCharacterEncoding(StandardCharsets.UTF_8.name());
		objectMapper.writeValue(response.getWriter(), body);
	}
}
