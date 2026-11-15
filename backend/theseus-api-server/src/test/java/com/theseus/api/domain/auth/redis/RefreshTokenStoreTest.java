package com.theseus.api.domain.auth.redis;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Duration;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.RedisScript;

@ExtendWith(MockitoExtension.class)
class RefreshTokenStoreTest {

	private static final Long USER_ID = 10L;
	private static final String KEY = "RT:10";
	private static final String PREVIOUS_KEY = "RT:prev:10";

	@Mock
	private StringRedisTemplate stringRedisTemplate;

	@Mock
	private ValueOperations<String, String> valueOperations;

	private RefreshTokenStore refreshTokenStore;

	@BeforeEach
	void setUp() {
		refreshTokenStore = new RefreshTokenStore(stringRedisTemplate);
	}

	@Test
	@DisplayName("Refresh Token Redis key를 생성한다.")
	void buildKey() {
		assertThat(refreshTokenStore.buildKey(USER_ID)).isEqualTo(KEY);
	}

	@Test
	@DisplayName("Refresh Token을 사용자 ID key와 TTL로 저장한다.")
	void save() {
		when(stringRedisTemplate.opsForValue()).thenReturn(valueOperations);

		refreshTokenStore.save(USER_ID, "refresh-token", Duration.ofDays(14));

		verify(valueOperations).set(KEY, "refresh-token", Duration.ofDays(14));
	}

	@Test
	@DisplayName("사용자 ID로 Refresh Token을 조회한다.")
	void findByUserId() {
		when(stringRedisTemplate.opsForValue()).thenReturn(valueOperations);
		when(valueOperations.get(KEY)).thenReturn("refresh-token");

		Optional<String> found = refreshTokenStore.findByUserId(USER_ID);

		assertThat(found).contains("refresh-token");
	}

	@Test
	@DisplayName("사용자 ID로 Refresh Token과 직전 토큰 기록을 함께 삭제한다.")
	void deleteByUserId() {
		refreshTokenStore.deleteByUserId(USER_ID);

		verify(stringRedisTemplate).delete(List.of(KEY, PREVIOUS_KEY));
	}

	@Test
	@DisplayName("회전은 현재 key와 직전 토큰 key를 TTL(ms)과 함께 원자적 스크립트로 넘긴다.")
	@SuppressWarnings("unchecked")
	void rotate() {
		when(stringRedisTemplate.execute(
			any(RedisScript.class),
			eq(List.of(KEY, PREVIOUS_KEY)),
			eq("old-token"),
			eq("new-token"),
			eq("1209600000"),
			eq("10000")
		)).thenReturn(1L);

		boolean rotated = refreshTokenStore.rotate(
			USER_ID,
			"old-token",
			"new-token",
			Duration.ofDays(14),
			Duration.ofSeconds(10)
		);

		assertThat(rotated).isTrue();
	}

	@Test
	@DisplayName("저장된 토큰이 달라 스크립트가 0을 돌려주면 회전하지 않은 것으로 본다.")
	@SuppressWarnings("unchecked")
	void rotateReturnsFalseWhenTokenChanged() {
		when(stringRedisTemplate.execute(
			any(RedisScript.class),
			any(List.class),
			any(),
			any(),
			any(),
			any()
		)).thenReturn(0L);

		assertThat(refreshTokenStore.rotate(USER_ID, "old", "new", Duration.ofDays(1), Duration.ofSeconds(10)))
			.isFalse();
	}

	@Test
	@DisplayName("직전 토큰은 별도 key에서 조회한다.")
	void findPreviousByUserId() {
		when(stringRedisTemplate.opsForValue()).thenReturn(valueOperations);
		when(valueOperations.get(PREVIOUS_KEY)).thenReturn("old-token");

		assertThat(refreshTokenStore.findPreviousByUserId(USER_ID)).contains("old-token");
	}
}
