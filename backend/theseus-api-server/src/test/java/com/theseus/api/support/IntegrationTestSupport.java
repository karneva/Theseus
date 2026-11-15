package com.theseus.api.support;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.utility.DockerImageName;

/**
 * DB와 Redis가 필요한 @SpringBootTest의 공통 부모입니다.
 *
 * <p>컨테이너는 JVM당 한 번만 띄우고(static 초기화) 모든 테스트 클래스가 공유합니다.
 * {@link ServiceConnection}이 datasource/redis 접속 정보를 컨테이너 주소로 덮어쓰므로 로컬 DB가 필요 없습니다.
 * 스키마는 운영과 같은 경로(Flyway V1 + ddl validate)로 만들어 마이그레이션과 엔티티 불일치도 함께 검증합니다.
 */
@SpringBootTest
public abstract class IntegrationTestSupport {

	@ServiceConnection
	protected static final MySQLContainer<?> MYSQL = new MySQLContainer<>(
		DockerImageName.parse("mysql:8.4")
	);

	@ServiceConnection(name = "redis")
	protected static final GenericContainer<?> REDIS = new GenericContainer<>(
		DockerImageName.parse("redis:7.4-alpine")
	).withExposedPorts(6379);

	static {
		MYSQL.start();
		REDIS.start();
	}
}
