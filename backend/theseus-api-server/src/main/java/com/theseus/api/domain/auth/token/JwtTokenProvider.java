package com.theseus.api.domain.auth.token;

import com.theseus.api.common.exception.BusinessException;
import com.theseus.api.common.exception.ErrorCode;
import com.theseus.api.domain.user.entity.User;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.UUID;
import javax.crypto.SecretKey;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class JwtTokenProvider {

	private static final String TOKEN_TYPE_CLAIM = "tokenType";
	private static final String ACCESS_TOKEN_TYPE = "access";
	private static final String REFRESH_TOKEN_TYPE = "refresh";
	// HS256 서명 키의 최소 길이(RFC 7518 3.2)입니다. 짧으면 jjwt가 WeakKeyException을 던집니다.
	private static final int MIN_SECRET_BYTES = 32;

	private final SecretKey secretKey;
	private final long accessTokenExpirationMillis;
	private final long refreshTokenExpirationMillis;

	public JwtTokenProvider(
		@Value("${jwt.secret}") String secret,
		@Value("${jwt.access-token-expiration-millis}") long accessTokenExpirationMillis,
		@Value("${jwt.refresh-token-expiration-millis}") long refreshTokenExpirationMillis
	) {
		this.secretKey = Keys.hmacShaKeyFor(validateSecret(secret));
		this.accessTokenExpirationMillis = accessTokenExpirationMillis;
		this.refreshTokenExpirationMillis = refreshTokenExpirationMillis;
	}

	/**
	 * JWT_SECRET 길이를 기동 시점에 검사해 jjwt의 일반 예외 대신 원인과 조치를 바로 알 수 있는 메시지를 냅니다.
	 */
	private static byte[] validateSecret(String secret) {
		byte[] secretBytes = secret == null ? new byte[0] : secret.getBytes(StandardCharsets.UTF_8);
		if (secretBytes.length < MIN_SECRET_BYTES) {
			throw new IllegalStateException(
				"JWT_SECRET(jwt.secret)은 HS256 서명을 위해 최소 %d바이트 이상이어야 합니다. 현재 %d바이트입니다. "
					.formatted(MIN_SECRET_BYTES, secretBytes.length) +
				"예: openssl rand -base64 48 로 생성한 값을 사용하세요."
			);
		}
		return secretBytes;
	}

	public String createAccessToken(User user) {
		return createToken(user, accessTokenExpirationMillis, ACCESS_TOKEN_TYPE);
	}

	public String createRefreshToken(User user) {
		return createToken(user, refreshTokenExpirationMillis, REFRESH_TOKEN_TYPE);
	}

	public Long getUserId(String token) {
		Claims claims = parseClaims(token);

		return Long.valueOf(claims.getSubject());
	}

	public boolean validateToken(String token) {
		return validateAccessToken(token);
	}

	public boolean validateAccessToken(String token) {
		validateTokenType(token, ACCESS_TOKEN_TYPE);

		return true;
	}

	public boolean validateRefreshToken(String token) {
		validateTokenType(token, REFRESH_TOKEN_TYPE);

		return true;
	}

	public long getRefreshTokenExpirationMillis() {
		return refreshTokenExpirationMillis;
	}

	private String createToken(User user, long expirationMillis, String tokenType) {
		Date now = new Date();
		Date expiresAt = new Date(now.getTime() + expirationMillis);

		return Jwts.builder()
			.id(UUID.randomUUID().toString())
			.subject(String.valueOf(user.getId()))
			.claim("role", user.getSystemRole().name())
			.claim(TOKEN_TYPE_CLAIM, tokenType)
			.issuedAt(now)
			.expiration(expiresAt)
			.signWith(secretKey)
			.compact();
	}

	private void validateTokenType(String token, String tokenType) {
		Claims claims = parseClaims(token);

		if (!tokenType.equals(claims.get(TOKEN_TYPE_CLAIM, String.class))) {
			throw BusinessException.of(ErrorCode.INVALID_TOKEN_TYPE);
		}
	}

	private Claims parseClaims(String token) {
		return Jwts.parser().verifyWith(secretKey).build().parseSignedClaims(token).getPayload();
	}
}
