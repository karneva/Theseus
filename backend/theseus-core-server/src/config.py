"""Core Server 설정.

환경변수와 1:1로 대응하는 pydantic Settings입니다. 설정은 이 모듈 하나에서만 읽고,
나머지 코드는 `settings` 싱글턴을 import해서 씁니다.

- API Server 호출 URL은 `SPRING_BOOT_INTERNAL_URL`(base) 하나만 받고 경로는 코드 상수로
  조합합니다. 개별 `SPRING_BOOT_*_URL`은 특수한 배포를 위한 선택적 override입니다.
- prod(`ENV=prod`)에서는 필수값 누락이나 localhost 지정을 기동 시점에 실패시킵니다.
"""

from functools import lru_cache
import os
from typing import Annotated, Optional
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}
NON_PRODUCTION_ENVS = {"local", "dev", "test"}

# API Server 내부 엔드포인트 경로. base URL(SPRING_BOOT_INTERNAL_URL) 뒤에 붙입니다.
INTERNAL_AUTH_VERIFY_PATH = "/api/internal/auth/verify"
INTERNAL_PROJECT_PERMISSIONS_PATH = "/api/internal/project/permissions"
INTERNAL_BILLING_USAGE_PATH = "/api/internal/billing/usage"
INTERNAL_HISTORY_MESSAGES_PATH = "/api/internal/history/messages"
INTERNAL_REMOTE_WORKSPACE_CONFIG_PATH = "/api/internal/remote-workspaces/connection-config"


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "TheseusCoreServer"
    # local|prod가 표준 값입니다. dev/test는 기존 배포와 테스트 호환용으로 남겨 둡니다.
    ENV: Literal["local", "dev", "test", "prod"] = "local"
    PORT: int = 8086
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = []

    # Auth Settings
    AUTH_MODE: Literal["mock", "spring"] = "spring"
    SPRING_BOOT_INTERNAL_URL: str = "http://localhost:8080"
    # 선택적 override. 비워 두면 SPRING_BOOT_INTERNAL_URL + 경로 상수로 조합합니다.
    SPRING_BOOT_AUTH_VERIFY_URL: Optional[str] = None
    SPRING_BOOT_PROJECT_PERMISSIONS_URL: Optional[str] = None
    SPRING_BOOT_BILLING_USAGE_URL: Optional[str] = None
    SPRING_BOOT_INTERNAL_HISTORY_MESSAGES_URL: Optional[str] = None
    SPRING_BOOT_REMOTE_WORKSPACE_CONFIG_URL: Optional[str] = None
    # API Server와 공유하는 서버 간 인증 키입니다. 표준 이름은 INTERNAL_API_KEY이고,
    # 기존 배포의 SPRING_BOOT_INTERNAL_API_KEY도 하위호환으로 읽습니다.
    INTERNAL_API_KEY: str = Field(
        "",
        validation_alias=AliasChoices("INTERNAL_API_KEY", "SPRING_BOOT_INTERNAL_API_KEY"),
    )
    AUTH_TIMEOUT_SECONDS: int = 5
    INTERNAL_API_TIMEOUT_SECONDS: int = 10
    BILLING_OUTBOX_SCHEDULER_ENABLED: bool = False
    BILLING_OUTBOX_BATCH_SIZE: int = 10
    BILLING_OUTBOX_FLUSH_INTERVAL_SECONDS: int = 30
    SANDBOX_IMAGE: str = "theseus-sandbox:py311-tools"
    SANDBOX_MEMORY_LIMIT: str = "128m"
    SANDBOX_CPU_QUOTA: int = 50000
    SANDBOX_CPU_PERIOD: int = 100000
    SANDBOX_KEEP_FAILED_CONTAINERS: bool = False
    DOCKER_HOST: Optional[str] = None
    SANDBOX_STARTUP_CHECK: bool = True
    SANDBOX_STARTUP_STRICT: bool = False
    SANDBOX_PULL_ON_STARTUP: bool = False

    # Kafka Settings
    # CORE_KAFKA_CONSUMER_ENABLED는 전체 consumer를 한 번에 끄는 master 스위치입니다.
    # 개별 consumer는 CORE_TOOL_PLAN/BUILD_CONSUMER_ENABLED로 켜고 끕니다(기본 모두 켜짐).
    CORE_KAFKA_CONSUMER_ENABLED: bool = True
    CORE_TOOL_PLAN_CONSUMER_ENABLED: bool = True
    CORE_TOOL_BUILD_CONSUMER_ENABLED: bool = True
    CORE_KAFKA_BOOTSTRAP_SERVERS: str = "localhost:19092"
    CORE_KAFKA_TOOL_PLAN_CONSUMER_GROUP_ID: str = "theseus-core-tool-plan"
    CORE_KAFKA_TOOL_BUILD_CONSUMER_GROUP_ID: str = "theseus-core-tool-build"
    KAFKA_TOPIC_TOOL_PLAN_REQUEST: str = "theseus.tool-plan.request"
    KAFKA_TOPIC_TOOL_PLAN_EVENT: str = "theseus.tool-plan.event"
    CORE_TOOL_PLAN_EXECUTION_SPEC_VALIDATION_MODE: Literal["strict", "warn", "off"] = "strict"
    CORE_TOOL_PLAN_STRUCTURED_OUTPUT_MODE: Literal[
        "auto",
        "response_format",
        "vllm_structured_outputs",
        "strict",
        "off",
    ] = "auto"
    KAFKA_TOPIC_TOOL_BUILD_REQUEST: str = "theseus.tool-build.request"
    KAFKA_TOPIC_TOOL_BUILD_EVENT: str = "theseus.tool-build.event"
    CORE_TOOL_PLAN_MAX_AGENT_TURNS: int = 30
    THESEUS_TOOL_REPAIR_MAX_ATTEMPTS: int = 2
    CORE_TOOL_BUILD_MAX_REPAIR_ATTEMPTS: int = 2
    CORE_TOOL_BUILD_RUN_TIMEOUT_SECONDS: int = 180
    CORE_RUN_LEASE_TTL_SECONDS: int = 60
    CORE_RUN_EVENT_REPUBLISH_BATCH_SIZE: int = 50

    # LLM 호출 한도
    # 출력 토큰 상한입니다. 컨텍스트가 작은 로컬 모델(vLLM/Ollama)은 32768을 거부할 수
    # 있으므로 모델에 맞게 낮춥니다. PLAN/BUILD/repair/audit 호출이 모두 이 값을 씁니다.
    LLM_MAX_OUTPUT_TOKENS: int = Field(32768, ge=1)
    # 채팅 스트림(/stream) ASK/AGENT 엔진의 최대 agent turn 수입니다.
    CORE_STREAM_MAX_AGENT_TURNS: int = Field(30, ge=1)

    # Database Settings (PostgreSQL + pgvector)
    CORE_POSTGRES_HOST: str = Field(
        "localhost",
        validation_alias=AliasChoices("CORE_POSTGRES_HOST", "POSTGRES_HOST"),
    )
    CORE_POSTGRES_PORT: int = Field(
        15432,
        validation_alias=AliasChoices("CORE_POSTGRES_PORT", "POSTGRES_PORT"),
    )
    CORE_POSTGRES_DB: str = Field(
        "theseus_core",
        validation_alias=AliasChoices("CORE_POSTGRES_DB", "POSTGRES_DB"),
    )
    CORE_POSTGRES_USER: str = Field(
        "root",
        validation_alias=AliasChoices("CORE_POSTGRES_USER", "POSTGRES_USER"),
    )
    CORE_POSTGRES_PASSWORD: str = Field(
        "",
        validation_alias=AliasChoices("CORE_POSTGRES_PASSWORD", "POSTGRES_PASSWORD"),
    )
    CORE_POSTGRES_SCHEMA: str = Field(
        "public",
        validation_alias=AliasChoices("CORE_POSTGRES_SCHEMA", "POSTGRES_SCHEMA"),
    )
    CORE_POSTGRES_POOL_SIZE: int = Field(5, ge=1)
    CORE_POSTGRES_MAX_OVERFLOW: int = Field(10, ge=0)

    @property
    def database_url(self) -> URL:
        """SQLAlchemy 접속 URL.

        문자열 결합 대신 `URL.create`를 써서 비밀번호에 `@`, `/`, `#`, `%` 같은 문자가
        있어도 호스트·DB 이름이 잘못 파싱되지 않게 합니다.
        """
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.CORE_POSTGRES_USER,
            password=self.CORE_POSTGRES_PASSWORD or None,
            host=self.CORE_POSTGRES_HOST,
            port=self.CORE_POSTGRES_PORT,
            database=self.CORE_POSTGRES_DB,
        )

    @property
    def database_connect_args(self) -> dict[str, str]:
        """public이 아닌 스키마를 쓰면 search_path에 반영합니다(pgvector 타입은 public에 있음)."""
        schema = (self.CORE_POSTGRES_SCHEMA or "").strip()
        if not schema or schema == "public":
            return {}
        return {"options": f"-csearch_path={schema},public"}

    # RAG Settings
    EMBEDDING_PROVIDER: str = "local"  # local | remote
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    VECTOR_DIMENSION: int = 384
    RAG_TOP_K: int = 5
    RAG_MIN_SCORE: float = 0.3

    # AI / Tools Settings
    # prod에서는 필수입니다. 비어 있으면 기동 시 실패합니다.
    THESEUS_MODEL: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    THESEUS_REMOTE_LOCAL_REPORT_WRITE_ENABLED: bool = True
    THESEUS_LOCAL_REPORT_ROOT: str = "reports"
    THESEUS_REMOTE_WORKSPACE_FILE_WRITE_OVERRIDE: bool = False
    THESEUS_SERVER_SENSITIVE_TOOL_POLICY: Literal["reject", "allow"] = "reject"
    THESEUS_CUSTOM_TOOLS_DIR: Optional[str] = None
    THESEUS_PROJECT_CUSTOM_TOOLS_DIR: Optional[str] = None
    THESEUS_CUSTOM_TOOLS_HOST_DIR: Optional[str] = None

    # Sandbox shared workdir settings.
    # When Core runs inside a Docker container and controls the host Docker daemon,
    # both paths must point at the same bind-mounted directory from each side.
    SANDBOX_HOST_TEMP_ROOT: Optional[str] = None
    SANDBOX_CONTAINER_TEMP_ROOT: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        raise ValueError("ALLOWED_ORIGINS must be a comma-separated string or list")

    def _internal_url(self, override: Optional[str], path: str) -> str:
        if override and override.strip():
            return override.strip()
        return f"{self.SPRING_BOOT_INTERNAL_URL.rstrip('/')}{path}"

    @property
    def spring_auth_verify_url(self) -> str:
        return self._internal_url(self.SPRING_BOOT_AUTH_VERIFY_URL, INTERNAL_AUTH_VERIFY_PATH)

    @property
    def spring_project_permissions_url(self) -> str:
        return self._internal_url(
            self.SPRING_BOOT_PROJECT_PERMISSIONS_URL, INTERNAL_PROJECT_PERMISSIONS_PATH
        )

    @property
    def spring_billing_usage_url(self) -> str:
        return self._internal_url(self.SPRING_BOOT_BILLING_USAGE_URL, INTERNAL_BILLING_USAGE_PATH)

    @property
    def spring_history_messages_url(self) -> str:
        return self._internal_url(
            self.SPRING_BOOT_INTERNAL_HISTORY_MESSAGES_URL, INTERNAL_HISTORY_MESSAGES_PATH
        )

    @property
    def spring_remote_workspace_config_url(self) -> str:
        return self._internal_url(
            self.SPRING_BOOT_REMOTE_WORKSPACE_CONFIG_URL, INTERNAL_REMOTE_WORKSPACE_CONFIG_PATH
        )

    @property
    def is_production(self) -> bool:
        return self.ENV == "prod"

    @property
    def mock_auth_enabled(self) -> bool:
        return self.AUTH_MODE == "mock"

    @property
    def cors_allowed_origins(self) -> list[str]:
        """Core는 브라우저가 직접 호출하지 않으므로(API Server가 프록시) prod 기본값은 CORS off입니다."""
        if self.ALLOWED_ORIGINS:
            return self.ALLOWED_ORIGINS
        if not self.is_production:
            return [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ]
        return []

    @property
    def docker_host(self) -> Optional[str]:
        return self.DOCKER_HOST or os.getenv("DOCKER_HOST")

    @model_validator(mode="after")
    def validate_runtime_safety(self) -> "Settings":
        if self.mock_auth_enabled and self.ENV not in NON_PRODUCTION_ENVS:
            raise ValueError("AUTH_MODE=mock is only allowed in local/dev/test environments")

        if not self.is_production:
            return self

        if self.mock_auth_enabled:
            raise ValueError("AUTH_MODE=mock is not allowed in production")

        required_urls = {
            "SPRING_BOOT_INTERNAL_URL": self.SPRING_BOOT_INTERNAL_URL,
            "SPRING_BOOT_AUTH_VERIFY_URL": self.spring_auth_verify_url,
            "SPRING_BOOT_PROJECT_PERMISSIONS_URL": self.spring_project_permissions_url,
            "SPRING_BOOT_BILLING_USAGE_URL": self.spring_billing_usage_url,
            "SPRING_BOOT_INTERNAL_HISTORY_MESSAGES_URL": self.spring_history_messages_url,
            "SPRING_BOOT_REMOTE_WORKSPACE_CONFIG_URL": self.spring_remote_workspace_config_url,
        }
        for name, value in required_urls.items():
            if not value.strip():
                raise ValueError(f"{name} must be set in production")
            if _is_local_url(value):
                raise ValueError(f"{name} must not point to localhost in production")

        if not self.INTERNAL_API_KEY.strip():
            raise ValueError("INTERNAL_API_KEY must be set in production")

        if not (self.THESEUS_MODEL or "").strip():
            raise ValueError("THESEUS_MODEL must be set in production")

        if any(origin == "*" for origin in self.ALLOWED_ORIGINS):
            raise ValueError("ALLOWED_ORIGINS must not contain '*' in production")

        return self


def _is_local_url(value: str) -> bool:
    hostname = urlparse(value).hostname
    return hostname in LOCAL_HOSTS


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def resolve_model_name(explicit_model: str | None = None) -> str:
    """명시 모델 → THESEUS_MODEL → 개발용 기본값 순으로 모델명을 고릅니다.

    prod에서는 THESEUS_MODEL이 필수라서 개발용 기본값으로 떨어지지 않습니다.
    """
    if explicit_model:
        return explicit_model
    return settings.THESEUS_MODEL or "gpt-4o"
