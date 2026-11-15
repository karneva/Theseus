package com.theseus.api.common.config.security;

import com.theseus.api.common.exception.ErrorCode;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

@RequiredArgsConstructor
@Component
public class InternalApiAuthenticationFilter extends OncePerRequestFilter {

	private static final String INTERNAL_API_PATH_PREFIX = "/api/internal/";
	private static final String INTERNAL_API_KEY_HEADER = "X-Internal-Api-Key";
	private static final String INTERNAL_API_PRINCIPAL = "internal-api";
	private static final String INTERNAL_ROLE = "ROLE_INTERNAL";

	private final SecurityErrorResponseWriter securityErrorResponseWriter;

	@Value("${internal.api-key:}")
	private String internalApiKey;

	@Override
	protected boolean shouldNotFilter(HttpServletRequest request) {
		return !request.getRequestURI().startsWith(INTERNAL_API_PATH_PREFIX);
	}

	@Override
	protected void doFilterInternal(
		HttpServletRequest request,
		HttpServletResponse response,
		FilterChain filterChain
	) throws ServletException, IOException {
		String requestApiKey = request.getHeader(INTERNAL_API_KEY_HEADER);

		if (!matchesInternalApiKey(requestApiKey)) {
			SecurityContextHolder.clearContext();
			securityErrorResponseWriter.write(response, ErrorCode.INTERNAL_API_UNAUTHORIZED);
			return;
		}

		UsernamePasswordAuthenticationToken authentication = new UsernamePasswordAuthenticationToken(
			INTERNAL_API_PRINCIPAL,
			null,
			List.of(new SimpleGrantedAuthority(INTERNAL_ROLE))
		);
		SecurityContextHolder.getContext().setAuthentication(authentication);

		filterChain.doFilter(request, response);
	}

	/**
	 * 서버 키가 비어 있으면 모든 내부 요청을 거부하고, 비교는 고정 시간(MessageDigest.isEqual)으로 해
	 * 응답 시간 차이로 키를 한 글자씩 추측하는 타이밍 공격을 막습니다.
	 */
	private boolean matchesInternalApiKey(String requestApiKey) {
		if (!StringUtils.hasText(internalApiKey) || requestApiKey == null) {
			return false;
		}
		return MessageDigest.isEqual(
			internalApiKey.getBytes(StandardCharsets.UTF_8),
			requestApiKey.getBytes(StandardCharsets.UTF_8)
		);
	}
}
