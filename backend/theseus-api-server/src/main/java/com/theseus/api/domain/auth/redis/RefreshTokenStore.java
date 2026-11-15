package com.theseus.api.domain.auth.redis;

import java.time.Duration;
import java.util.List;
import java.util.Optional;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.stereotype.Component;

@RequiredArgsConstructor
@Component
public class RefreshTokenStore {

	private static final String KEY_PREFIX = "RT:";
	private static final String PREVIOUS_KEY_PREFIX = "RT:prev:";

	/**
	 * 저장된 토큰이 ARGV[1]일 때만 ARGV[2]로 바꾸고, ARGV[1]을 직전 토큰으로 잠깐(ARGV[4] ms) 남깁니다.
	 * 같은 토큰으로 동시에 들어온 재발급 중 하나만 회전하도록 비교와 저장을 원자적으로 처리합니다.
	 */
	private static final RedisScript<Long> ROTATE_SCRIPT = new DefaultRedisScript<>(
		"if redis.call('GET', KEYS[1]) == ARGV[1] then "
			+ "redis.call('SET', KEYS[1], ARGV[2], 'PX', ARGV[3]) "
			+ "redis.call('SET', KEYS[2], ARGV[1], 'PX', ARGV[4]) "
			+ "return 1 end "
			+ "return 0",
		Long.class
	);

	private final StringRedisTemplate stringRedisTemplate;

	public void save(Long userId, String refreshToken, Duration ttl) {
		stringRedisTemplate.opsForValue().set(buildKey(userId), refreshToken, ttl);
	}

	public Optional<String> findByUserId(Long userId) {
		return Optional.ofNullable(stringRedisTemplate.opsForValue().get(buildKey(userId)));
	}

	/**
	 * 저장된 토큰이 expectedRefreshToken일 때만 newRefreshToken으로 회전합니다.
	 * 회전한 직전 토큰은 grace 동안 {@link #findPreviousByUserId}로 조회할 수 있습니다.
	 *
	 * @return 회전했으면 true, 그사이 다른 요청이 먼저 회전했거나 토큰이 없으면 false
	 */
	public boolean rotate(
		Long userId,
		String expectedRefreshToken,
		String newRefreshToken,
		Duration ttl,
		Duration grace
	) {
		Long rotated = stringRedisTemplate.execute(
			ROTATE_SCRIPT,
			List.of(buildKey(userId), buildPreviousKey(userId)),
			expectedRefreshToken,
			newRefreshToken,
			String.valueOf(ttl.toMillis()),
			String.valueOf(grace.toMillis())
		);
		return Long.valueOf(1L).equals(rotated);
	}

	/**
	 * 직전에 회전된 Refresh Token을 조회합니다(회전 후 grace 동안만 남아 있습니다).
	 */
	public Optional<String> findPreviousByUserId(Long userId) {
		return Optional.ofNullable(stringRedisTemplate.opsForValue().get(buildPreviousKey(userId)));
	}

	public void deleteByUserId(Long userId) {
		stringRedisTemplate.delete(List.of(buildKey(userId), buildPreviousKey(userId)));
	}

	String buildKey(Long userId) {
		return KEY_PREFIX + requireUserId(userId);
	}

	String buildPreviousKey(Long userId) {
		return PREVIOUS_KEY_PREFIX + requireUserId(userId);
	}

	private Long requireUserId(Long userId) {
		if (userId == null) {
			throw new IllegalArgumentException("userId must not be null.");
		}
		return userId;
	}
}
