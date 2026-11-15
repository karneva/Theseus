package com.theseus.api.common.config.security;

import com.theseus.api.domain.auth.token.JwtAuthenticationFilter;
import jakarta.servlet.DispatcherType;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

@RequiredArgsConstructor
@Configuration
@EnableWebSecurity
public class SecurityConfig {

	private static final String[] SWAGGER_PATHS = {
		"/swagger-ui.html",
		"/swagger-ui/**",
		"/v3/api-docs",
		"/v3/api-docs/**",
	};

	private static final String[] AUTH_PATHS = {
		"/api/v1/auth/login",
		"/api/v1/auth/refresh",
		"/api/v1/auth/logout",
	};

	// 컨테이너 HEALTHCHECK용입니다. management 노출 범위는 health(상세 정보 없음)로 제한합니다.
	private static final String HEALTH_PATH = "/actuator/health";

	private static final String PROD_PROFILE = "prod";

	private final JwtAuthenticationFilter jwtAuthenticationFilter;
	private final InternalApiAuthenticationFilter internalApiAuthenticationFilter;
	private final SecurityErrorResponseWriter securityErrorResponseWriter;
	private final CorsProperties corsProperties;
	private final Environment environment;

	@Bean
	public PasswordEncoder passwordEncoder() {
		return new BCryptPasswordEncoder();
	}

	@Bean
	public SecurityFilterChain defaultSecurityFilterChain(HttpSecurity http) throws Exception {
		http
			.csrf(AbstractHttpConfigurer::disable)
			.sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
			.formLogin(AbstractHttpConfigurer::disable)
			.httpBasic(AbstractHttpConfigurer::disable)
			.authorizeHttpRequests(auth ->
				auth
					.dispatcherTypeMatchers(DispatcherType.ASYNC, DispatcherType.ERROR)
					.permitAll()
					.requestMatchers(SWAGGER_PATHS)
					.permitAll()
					.requestMatchers(AUTH_PATHS)
					.permitAll()
					.requestMatchers(HEALTH_PATH)
					.permitAll()
					.requestMatchers("/api/internal/**")
					.hasRole("INTERNAL")
					.requestMatchers("/api/v1/admin/**")
					.hasRole("SUPER_ADMIN")
					.anyRequest()
					.authenticated()
			)
			.exceptionHandling(exceptions ->
				exceptions
					.authenticationEntryPoint(securityErrorResponseWriter.authenticationEntryPoint())
					.accessDeniedHandler(securityErrorResponseWriter.accessDeniedHandler())
			)
			.addFilterBefore(internalApiAuthenticationFilter, UsernamePasswordAuthenticationFilter.class)
			.addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter.class);

		CorsConfigurationSource corsConfigurationSource = createCorsConfigurationSource();
		if (corsConfigurationSource == null) {
			http.cors(AbstractHttpConfigurer::disable);
		} else {
			http.cors(cors -> cors.configurationSource(corsConfigurationSource));
		}

		return http.build();
	}

	/**
	 * ALLOWED_ORIGINS에 적힌 origin만 자격 증명(쿠키) 포함 요청을 허용합니다.
	 * 목록이 비어 있으면 same-origin 배포로 보고 CORS를 끕니다(null 반환).
	 * prod에서 '*'는 임의 사이트가 refresh 쿠키로 응답을 읽을 수 있게 하므로 기동을 실패시킵니다.
	 */
	CorsConfigurationSource createCorsConfigurationSource() {
		if (!corsProperties.isEnabled()) {
			return null;
		}

		boolean wildcard = corsProperties.containsWildcard();
		if (wildcard && environment.acceptsProfiles(Profiles.of(PROD_PROFILE))) {
			throw new IllegalStateException(
				"ALLOWED_ORIGINS(theseus.cors.allowed-origins)에 '*'는 prod 프로필에서 허용되지 않습니다. " +
				"허용할 origin을 쉼표로 나열하거나, same-origin 배포라면 비워 두세요."
			);
		}

		CorsConfiguration configuration = new CorsConfiguration();
		if (wildcard) {
			configuration.setAllowedOriginPatterns(List.of(CorsProperties.WILDCARD));
		} else {
			configuration.setAllowedOrigins(corsProperties.allowedOrigins());
		}
		configuration.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"));
		configuration.setAllowedHeaders(List.of("*"));
		configuration.setAllowCredentials(true);

		UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
		source.registerCorsConfiguration("/**", configuration);
		return source;
	}
}
