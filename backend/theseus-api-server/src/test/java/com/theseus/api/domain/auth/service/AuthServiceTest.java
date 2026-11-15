package com.theseus.api.domain.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.theseus.api.common.exception.BusinessException;
import com.theseus.api.common.exception.ErrorCode;
import com.theseus.api.domain.auth.dto.request.LoginRequest;
import com.theseus.api.domain.auth.dto.response.TokenReissueResult;
import com.theseus.api.domain.auth.redis.RefreshTokenStore;
import com.theseus.api.domain.auth.token.JwtTokenProvider;
import com.theseus.api.domain.user.entity.SystemRole;
import com.theseus.api.domain.user.entity.User;
import com.theseus.api.domain.user.entity.UserStatus;
import com.theseus.api.domain.user.repository.UserRepository;
import java.time.Duration;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

@ExtendWith(MockitoExtension.class)
class AuthServiceTest {

	private static final Long USER_ID = 10L;
	private static final long REFRESH_TOKEN_EXPIRATION_MILLIS = 1_209_600_000L;

	@Mock
	private UserRepository userRepository;

	@Mock
	private RefreshTokenStore refreshTokenStore;

	@Mock
	private PasswordEncoder passwordEncoder;

	@Mock
	private JwtTokenProvider jwtTokenProvider;

	private AuthService authService;

	@BeforeEach
	void setUp() {
		authService = new AuthService(
			userRepository,
			refreshTokenStore,
			passwordEncoder,
			jwtTokenProvider
		);
	}

	@Test
	@DisplayName("Redis에 저장된 Refresh Token과 쿠키 값이 같으면 토큰을 재발급하고 Refresh Token을 회전한다.")
	void reissueAccessTokenRotatesRefreshToken() {
		User user = createUser();
		when(jwtTokenProvider.validateRefreshToken("old-refresh-token")).thenReturn(true);
		when(jwtTokenProvider.getUserId("old-refresh-token")).thenReturn(USER_ID);
		when(refreshTokenStore.findByUserId(USER_ID)).thenReturn(Optional.of("old-refresh-token"));
		when(userRepository.findById(USER_ID)).thenReturn(Optional.of(user));
		when(jwtTokenProvider.createAccessToken(user)).thenReturn("new-access-token");
		when(jwtTokenProvider.createRefreshToken(user)).thenReturn("new-refresh-token");
		when(jwtTokenProvider.getRefreshTokenExpirationMillis()).thenReturn(REFRESH_TOKEN_EXPIRATION_MILLIS);
		when(refreshTokenStore.rotate(
			USER_ID,
			"old-refresh-token",
			"new-refresh-token",
			Duration.ofMillis(REFRESH_TOKEN_EXPIRATION_MILLIS),
			AuthService.REFRESH_TOKEN_ROTATION_GRACE
		)).thenReturn(true);

		TokenReissueResult result = authService.reissueAccessToken("old-refresh-token");

		assertThat(result.response().getTokenType()).isEqualTo("Bearer");
		assertThat(result.response().getAccessToken()).isEqualTo("new-access-token");
		assertThat(result.refreshToken()).isEqualTo("new-refresh-token");
		verify(refreshTokenStore, never()).deleteByUserId(USER_ID);
	}

	@Test
	@DisplayName("grace 안에 직전 Refresh Token으로 다시 요청하면(다른 탭 동시 재발급) 회전하지 않고 현재 토큰을 돌려준다.")
	void reissueAccessTokenAcceptsJustRotatedRefreshToken() {
		User user = createUser();
		when(jwtTokenProvider.validateRefreshToken("old-refresh-token")).thenReturn(true);
		when(jwtTokenProvider.getUserId("old-refresh-token")).thenReturn(USER_ID);
		when(refreshTokenStore.findByUserId(USER_ID)).thenReturn(Optional.of("current-refresh-token"));
		when(refreshTokenStore.findPreviousByUserId(USER_ID)).thenReturn(Optional.of("old-refresh-token"));
		when(userRepository.findById(USER_ID)).thenReturn(Optional.of(user));
		when(jwtTokenProvider.createAccessToken(user)).thenReturn("new-access-token");

		TokenReissueResult result = authService.reissueAccessToken("old-refresh-token");

		assertThat(result.response().getAccessToken()).isEqualTo("new-access-token");
		assertThat(result.refreshToken()).isEqualTo("current-refresh-token");
		verify(refreshTokenStore, never()).deleteByUserId(USER_ID);
		verify(refreshTokenStore, never()).rotate(any(), any(), any(), any(), any());
		verify(jwtTokenProvider, never()).createRefreshToken(user);
	}

	@Test
	@DisplayName("같은 토큰으로 동시에 들어온 다른 요청이 먼저 회전했으면 그 결과 토큰을 함께 쓴다.")
	void reissueAccessTokenUsesConcurrentRotationResult() {
		User user = createUser();
		when(jwtTokenProvider.validateRefreshToken("old-refresh-token")).thenReturn(true);
		when(jwtTokenProvider.getUserId("old-refresh-token")).thenReturn(USER_ID);
		when(refreshTokenStore.findByUserId(USER_ID))
			.thenReturn(Optional.of("old-refresh-token"))
			.thenReturn(Optional.of("rotated-by-other-request"));
		when(refreshTokenStore.findPreviousByUserId(USER_ID)).thenReturn(Optional.of("old-refresh-token"));
		when(userRepository.findById(USER_ID)).thenReturn(Optional.of(user));
		when(jwtTokenProvider.createAccessToken(user)).thenReturn("new-access-token");
		when(jwtTokenProvider.createRefreshToken(user)).thenReturn("new-refresh-token");
		when(jwtTokenProvider.getRefreshTokenExpirationMillis()).thenReturn(REFRESH_TOKEN_EXPIRATION_MILLIS);
		when(refreshTokenStore.rotate(any(), any(), any(), any(), any())).thenReturn(false);

		TokenReissueResult result = authService.reissueAccessToken("old-refresh-token");

		assertThat(result.refreshToken()).isEqualTo("rotated-by-other-request");
		verify(refreshTokenStore, never()).deleteByUserId(USER_ID);
	}

	@Test
	@DisplayName("회전 경쟁에서 지고 직전 토큰 기록도 맞지 않으면 재발급을 거부한다.")
	void reissueAccessTokenRejectsWhenRotationLostWithoutGraceRecord() {
		User user = createUser();
		when(jwtTokenProvider.validateRefreshToken("old-refresh-token")).thenReturn(true);
		when(jwtTokenProvider.getUserId("old-refresh-token")).thenReturn(USER_ID);
		when(refreshTokenStore.findByUserId(USER_ID)).thenReturn(Optional.of("old-refresh-token"));
		when(userRepository.findById(USER_ID)).thenReturn(Optional.of(user));
		when(jwtTokenProvider.createAccessToken(user)).thenReturn("new-access-token");
		when(jwtTokenProvider.createRefreshToken(user)).thenReturn("new-refresh-token");
		when(jwtTokenProvider.getRefreshTokenExpirationMillis()).thenReturn(REFRESH_TOKEN_EXPIRATION_MILLIS);
		when(refreshTokenStore.rotate(any(), any(), any(), any(), any())).thenReturn(false);

		assertThatThrownBy(() -> authService.reissueAccessToken("old-refresh-token"))
			.isInstanceOf(BusinessException.class)
			.extracting(exception -> ((BusinessException) exception).getErrorCode())
			.isEqualTo(ErrorCode.INVALID_REFRESH_TOKEN);
	}

	@Test
	@DisplayName("쿠키 Refresh Token과 Redis 저장값이 다르면 Redis 값을 삭제하고 예외를 던진다.")
	void reissueAccessTokenRejectsMismatchedRefreshToken() {
		when(jwtTokenProvider.validateRefreshToken("cookie-refresh-token")).thenReturn(true);
		when(jwtTokenProvider.getUserId("cookie-refresh-token")).thenReturn(USER_ID);
		when(refreshTokenStore.findByUserId(USER_ID)).thenReturn(Optional.of("redis-refresh-token"));

		assertThatThrownBy(() -> authService.reissueAccessToken("cookie-refresh-token"))
			.isInstanceOf(BusinessException.class);
		verify(refreshTokenStore).deleteByUserId(USER_ID);
	}

	@Test
	@DisplayName("grace가 지난 옛 Refresh Token 재사용은 탈취로 보고 Redis 값을 삭제한다.")
	void reissueAccessTokenRejectsStaleRefreshTokenAfterGrace() {
		when(jwtTokenProvider.validateRefreshToken("stale-refresh-token")).thenReturn(true);
		when(jwtTokenProvider.getUserId("stale-refresh-token")).thenReturn(USER_ID);
		when(refreshTokenStore.findByUserId(USER_ID)).thenReturn(Optional.of("redis-refresh-token"));
		when(refreshTokenStore.findPreviousByUserId(USER_ID)).thenReturn(Optional.of("other-previous-token"));

		assertThatThrownBy(() -> authService.reissueAccessToken("stale-refresh-token"))
			.isInstanceOf(BusinessException.class);
		verify(refreshTokenStore).deleteByUserId(USER_ID);
	}

	@Test
	@DisplayName("비활성 사용자는 비밀번호가 맞아도 로그인할 수 없다.")
	void loginRejectsInactiveUser() {
		User user = createUser();
		user.updateStatus(UserStatus.INACTIVE);
		LoginRequest request = new LoginRequest();
		ReflectionTestUtils.setField(request, "loginId", "A001");
		ReflectionTestUtils.setField(request, "password", "raw-password");
		when(userRepository.findByEmployeeNumber("A001")).thenReturn(Optional.of(user));
		when(passwordEncoder.matches("raw-password", "encoded-password")).thenReturn(true);

		assertThatThrownBy(() -> authService.login(request))
			.isInstanceOf(BusinessException.class)
			.extracting(exception -> ((BusinessException) exception).getErrorCode())
			.isEqualTo(ErrorCode.INACTIVE_USER);
		verify(jwtTokenProvider, never()).createAccessToken(user);
		verify(refreshTokenStore, never()).save(eq(USER_ID), anyString(), any(Duration.class));
	}

	@Test
	@DisplayName("비활성 사용자의 Refresh Token 재발급은 거부하고 저장된 토큰을 삭제한다.")
	void reissueAccessTokenRejectsInactiveUser() {
		User user = createUser();
		user.updateStatus(UserStatus.INACTIVE);
		when(jwtTokenProvider.validateRefreshToken("refresh-token")).thenReturn(true);
		when(jwtTokenProvider.getUserId("refresh-token")).thenReturn(USER_ID);
		when(refreshTokenStore.findByUserId(USER_ID)).thenReturn(Optional.of("refresh-token"));
		when(userRepository.findById(USER_ID)).thenReturn(Optional.of(user));

		assertThatThrownBy(() -> authService.reissueAccessToken("refresh-token"))
			.isInstanceOf(BusinessException.class)
			.extracting(exception -> ((BusinessException) exception).getErrorCode())
			.isEqualTo(ErrorCode.INVALID_REFRESH_TOKEN);
		verify(refreshTokenStore).deleteByUserId(USER_ID);
		verify(jwtTokenProvider, never()).createAccessToken(user);
	}

	@Test
	@DisplayName("로그아웃 시 Refresh Token의 사용자 ID 기준으로 Redis key를 삭제한다.")
	void logoutDeletesRefreshTokenByUserId() {
		when(jwtTokenProvider.validateRefreshToken("refresh-token")).thenReturn(true);
		when(jwtTokenProvider.getUserId("refresh-token")).thenReturn(USER_ID);

		authService.logout("refresh-token");

		verify(refreshTokenStore).deleteByUserId(USER_ID);
	}

	private User createUser() {
		User user = User.builder()
			.employeeNumber("A001")
			.name("Auth User")
			.email("auth@example.com")
			.password("encoded-password")
			.systemRole(SystemRole.USER)
			.build();
		ReflectionTestUtils.setField(user, "id", USER_ID);
		return user;
	}
}
