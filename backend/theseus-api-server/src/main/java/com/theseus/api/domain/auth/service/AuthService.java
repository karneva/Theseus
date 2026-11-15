package com.theseus.api.domain.auth.service;

import com.theseus.api.common.exception.BusinessException;
import com.theseus.api.common.exception.ErrorCode;
import com.theseus.api.domain.auth.dto.request.LoginRequest;
import com.theseus.api.domain.auth.dto.response.LoginResponse;
import com.theseus.api.domain.auth.dto.response.LoginResult;
import com.theseus.api.domain.auth.dto.response.TokenReissueResponse;
import com.theseus.api.domain.auth.dto.response.TokenReissueResult;
import com.theseus.api.domain.auth.redis.RefreshTokenStore;
import com.theseus.api.domain.auth.token.JwtTokenProvider;
import com.theseus.api.domain.user.entity.User;
import com.theseus.api.domain.user.entity.UserStatus;
import com.theseus.api.domain.user.repository.UserRepository;
import io.jsonwebtoken.JwtException;
import java.time.Duration;
import java.util.Optional;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@RequiredArgsConstructor
@Transactional(readOnly = true)
@Service
public class AuthService {

	private static final String TOKEN_TYPE = "Bearer";
	/**
	 * 회전된 직전 Refresh Token을 받아 주는 시간입니다. 여러 탭이 거의 동시에 같은 쿠키로 재발급하면
	 * 늦게 도착한 요청이 재사용으로 판정되어 사용자 토큰이 모두 지워지므로, 이 시간 안의 직전 토큰은
	 * 새로 회전하지 않고 이미 회전된 현재 토큰을 함께 돌려줍니다.
	 */
	static final Duration REFRESH_TOKEN_ROTATION_GRACE = Duration.ofSeconds(10);

	private final UserRepository userRepository;
	private final RefreshTokenStore refreshTokenStore;
	private final PasswordEncoder passwordEncoder;
	private final JwtTokenProvider jwtTokenProvider;

	/**
	 * 로그인 ID와 비밀번호를 검증하고 Access Token과 Refresh Token을 발급합니다.
	 * 비활성(INACTIVE) 계정은 비밀번호가 맞아도 토큰을 발급하지 않습니다.
	 */
	@Transactional
	public LoginResult login(LoginRequest request) {
		User user = findLoginUser(request.getLoginId());
		validatePassword(request.getPassword(), user);
		validateActiveUser(user);
		String accessToken = jwtTokenProvider.createAccessToken(user);
		String refreshToken = issueRefreshToken(user);

		LoginResponse response = LoginResponse.builder()
			.tokenType(TOKEN_TYPE)
			.accessToken(accessToken)
			.userId(user.getId())
			.name(user.getName())
			.systemRole(user.getSystemRole())
			.build();

		return new LoginResult(response, refreshToken);
	}

	/**
	 * 유효한 Refresh Token으로 새 Access Token과 Refresh Token을 재발급합니다.
	 */
	@Transactional
	public TokenReissueResult reissueAccessToken(String refreshToken) {
		ValidatedRefreshToken validated = validateAndFindRefreshTokenUser(refreshToken);
		User user = validated.user();
		String accessToken = jwtTokenProvider.createAccessToken(user);
		String newRefreshToken = validated.alreadyRotatedTo() != null
			? validated.alreadyRotatedTo()
			: rotateRefreshToken(user, refreshToken);

		TokenReissueResponse response = TokenReissueResponse.builder()
			.tokenType(TOKEN_TYPE)
			.accessToken(accessToken)
			.build();

		return new TokenReissueResult(response, newRefreshToken);
	}

	/**
	 * 저장된 Refresh Token을 제거하여 로그아웃을 처리합니다.
	 */
	@Transactional
	public void logout(String refreshToken) {
		if (refreshToken == null || refreshToken.isBlank()) {
			return;
		}

		try {
			jwtTokenProvider.validateRefreshToken(refreshToken);
			refreshTokenStore.deleteByUserId(jwtTokenProvider.getUserId(refreshToken));
		} catch (JwtException | IllegalArgumentException | BusinessException exception) {
			return;
		}
	}

	private User findLoginUser(String loginId) {
		return userRepository
			.findByEmployeeNumber(loginId)
			.or(() -> userRepository.findByEmail(loginId))
			.orElseThrow(() -> BusinessException.of(ErrorCode.LOGIN_FAILED));
	}

	private void validatePassword(String password, User user) {
		if (!passwordEncoder.matches(password, user.getPassword())) {
			throw BusinessException.of(ErrorCode.LOGIN_FAILED);
		}
	}

	private void validateActiveUser(User user) {
		if (!UserStatus.ACTIVE.equals(user.getStatus())) {
			throw BusinessException.of(ErrorCode.INACTIVE_USER);
		}
	}

	private String issueRefreshToken(User user) {
		String refreshToken = jwtTokenProvider.createRefreshToken(user);
		refreshTokenStore.save(
			user.getId(),
			refreshToken,
			Duration.ofMillis(jwtTokenProvider.getRefreshTokenExpirationMillis())
		);

		return refreshToken;
	}

	/**
	 * 저장된 토큰이 아직 currentRefreshToken일 때만 회전합니다. 같은 토큰으로 동시에 들어온 다른 요청이
	 * 먼저 회전했으면 그 결과(현재 토큰)를 함께 씁니다.
	 */
	private String rotateRefreshToken(User user, String currentRefreshToken) {
		String newRefreshToken = jwtTokenProvider.createRefreshToken(user);
		boolean rotated = refreshTokenStore.rotate(
			user.getId(),
			currentRefreshToken,
			newRefreshToken,
			Duration.ofMillis(jwtTokenProvider.getRefreshTokenExpirationMillis()),
			REFRESH_TOKEN_ROTATION_GRACE
		);
		if (rotated) {
			return newRefreshToken;
		}
		return findTokenRotatedFrom(user.getId(), currentRefreshToken)
			.orElseThrow(() -> BusinessException.of(ErrorCode.INVALID_REFRESH_TOKEN));
	}

	/**
	 * refreshToken이 grace 안에 회전된 직전 토큰이면 현재 토큰을 돌려줍니다.
	 */
	private Optional<String> findTokenRotatedFrom(Long userId, String refreshToken) {
		boolean justRotated = refreshTokenStore
			.findPreviousByUserId(userId)
			.map(refreshToken::equals)
			.orElse(false);
		return justRotated ? refreshTokenStore.findByUserId(userId) : Optional.empty();
	}

	private ValidatedRefreshToken validateAndFindRefreshTokenUser(String refreshToken) {
		if (refreshToken == null || refreshToken.isBlank()) {
			throw BusinessException.of(ErrorCode.INVALID_REFRESH_TOKEN);
		}

		try {
			jwtTokenProvider.validateRefreshToken(refreshToken);
			Long tokenUserId = jwtTokenProvider.getUserId(refreshToken);
			String savedRefreshToken = refreshTokenStore
				.findByUserId(tokenUserId)
				.orElseThrow(() -> BusinessException.of(ErrorCode.INVALID_REFRESH_TOKEN));

			String alreadyRotatedTo = null;
			if (!savedRefreshToken.equals(refreshToken)) {
				alreadyRotatedTo = findTokenRotatedFrom(tokenUserId, refreshToken).orElse(null);
				if (alreadyRotatedTo == null) {
					// grace를 지난 재사용은 탈취로 보고 사용자 토큰을 모두 지웁니다.
					refreshTokenStore.deleteByUserId(tokenUserId);
					throw BusinessException.of(ErrorCode.INVALID_REFRESH_TOKEN);
				}
			}

			User user = userRepository
				.findById(tokenUserId)
				.orElseThrow(() -> BusinessException.of(ErrorCode.INVALID_REFRESH_TOKEN));
			// 재발급 시점에 비활성화된 계정이면 저장된 토큰을 지워 이후 재시도도 막습니다.
			if (!UserStatus.ACTIVE.equals(user.getStatus())) {
				refreshTokenStore.deleteByUserId(tokenUserId);
				throw BusinessException.of(ErrorCode.INACTIVE_USER);
			}
			return new ValidatedRefreshToken(user, alreadyRotatedTo);
		} catch (JwtException | IllegalArgumentException | BusinessException exception) {
			throw BusinessException.of(ErrorCode.INVALID_REFRESH_TOKEN, exception);
		}
	}

	/**
	 * @param alreadyRotatedTo 직전 토큰으로 들어와 이미 회전된 경우의 현재 토큰. 아니면 null
	 */
	private record ValidatedRefreshToken(User user, String alreadyRotatedTo) {
	}
}
