# API 서버 이미지입니다. 테스트는 Testcontainers(Docker)가 필요하므로 이미지 빌드에서는 제외하고 CI에서 별도로 실행합니다.

# Build stage: Java 21 + Gradle wrapper
FROM eclipse-temurin:25-jdk-alpine AS builder

WORKDIR /build

# 빌드 스크립트만 먼저 복사해 소스가 바뀌어도 Gradle 배포본/의존성 레이어를 재사용합니다.
COPY gradlew settings.gradle build.gradle ./
COPY gradle gradle
RUN sed -i 's/\r$//' gradlew && chmod +x gradlew
RUN --mount=type=cache,target=/root/.gradle \
    ./gradlew dependencies --no-daemon > /dev/null

COPY src src
RUN --mount=type=cache,target=/root/.gradle \
    ./gradlew bootJar -x test --no-daemon

# Runtime stage: JRE만 포함하고 비root 사용자로 실행합니다.
FROM eclipse-temurin:25-jre-alpine

RUN apk add --no-cache tzdata \
    && addgroup -S theseus \
    && adduser -S -D -H -u 10001 -G theseus theseus

WORKDIR /app

COPY --from=builder --chown=theseus:theseus /build/build/libs/*.jar app.jar

# TZ와 JVM 옵션은 compose/.env에서 덮어쓸 수 있습니다.
# MaxRAMPercentage는 컨테이너 메모리 제한 기준으로 힙을 잡아 단일 서버에서 다른 컨테이너와 메모리를 나눕니다.
ENV TZ=Asia/Seoul \
    SERVER_PORT=8080 \
    JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75"

USER theseus

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD wget -q -O /dev/null "http://127.0.0.1:${SERVER_PORT}/actuator/health" || exit 1

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
