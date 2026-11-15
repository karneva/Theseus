"""Core Settings의 prod fail-fast 검증과 env 조합 규칙 테스트.

scratch/test_config_validation.py(print 기반 수동 스크립트)를 pytest로 옮긴 것입니다.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy.engine import make_url

from src.config import Settings

VALID_PROD_ENV = {
    "ENV": "prod",
    "AUTH_MODE": "spring",
    "INTERNAL_API_KEY": "prod-internal-key",
    "SPRING_BOOT_INTERNAL_URL": "http://api:8080",
    "THESEUS_MODEL": "ollama/llama3.1",
}


def _settings(env: dict[str, str]) -> Settings:
    with patch.dict(os.environ, env, clear=True):
        return Settings(_env_file=None)


class ProdValidationTest(unittest.TestCase):
    def test_valid_prod_config_is_accepted_with_only_base_url(self) -> None:
        settings = _settings(VALID_PROD_ENV)

        self.assertTrue(settings.is_production)
        self.assertEqual(
            settings.spring_auth_verify_url, "http://api:8080/api/internal/auth/verify"
        )
        self.assertEqual(
            settings.spring_remote_workspace_config_url,
            "http://api:8080/api/internal/remote-workspaces/connection-config",
        )
        # Core는 브라우저가 직접 호출하지 않으므로 prod에서 ALLOWED_ORIGINS가 비어 있으면 CORS off.
        self.assertEqual(settings.cors_allowed_origins, [])

    def test_mock_auth_is_rejected_in_prod(self) -> None:
        with self.assertRaises(ValidationError):
            _settings({**VALID_PROD_ENV, "AUTH_MODE": "mock"})

    def test_localhost_internal_url_is_rejected_in_prod(self) -> None:
        with self.assertRaises(ValidationError):
            _settings({**VALID_PROD_ENV, "SPRING_BOOT_INTERNAL_URL": "http://localhost:8080"})

    def test_localhost_override_url_is_rejected_in_prod(self) -> None:
        with self.assertRaises(ValidationError):
            _settings(
                {
                    **VALID_PROD_ENV,
                    "SPRING_BOOT_AUTH_VERIFY_URL": "http://127.0.0.1:8080/api/internal/auth/verify",
                }
            )

    def test_missing_internal_api_key_is_rejected_in_prod(self) -> None:
        env = dict(VALID_PROD_ENV)
        env.pop("INTERNAL_API_KEY")
        with self.assertRaises(ValidationError):
            _settings(env)

    def test_missing_model_is_rejected_in_prod(self) -> None:
        env = dict(VALID_PROD_ENV)
        env.pop("THESEUS_MODEL")
        with self.assertRaises(ValidationError):
            _settings(env)

    def test_wildcard_origin_is_rejected_in_prod(self) -> None:
        with self.assertRaises(ValidationError):
            _settings({**VALID_PROD_ENV, "ALLOWED_ORIGINS": "*"})

    def test_mock_auth_is_allowed_in_local(self) -> None:
        settings = _settings({"ENV": "local", "AUTH_MODE": "mock"})
        self.assertTrue(settings.mock_auth_enabled)


class DefaultsTest(unittest.TestCase):
    def test_defaults_match_env_contract(self) -> None:
        settings = _settings({})

        self.assertEqual(settings.ENV, "local")
        self.assertEqual(settings.PORT, 8086)
        self.assertTrue(settings.CORE_TOOL_PLAN_CONSUMER_ENABLED)
        self.assertTrue(settings.CORE_TOOL_BUILD_CONSUMER_ENABLED)
        self.assertEqual(settings.LLM_MAX_OUTPUT_TOKENS, 32768)
        self.assertEqual(settings.CORE_STREAM_MAX_AGENT_TURNS, 30)
        self.assertEqual(settings.KAFKA_TOPIC_TOOL_PLAN_REQUEST, "theseus.tool-plan.request")
        self.assertEqual(settings.KAFKA_TOPIC_TOOL_BUILD_EVENT, "theseus.tool-build.event")

    def test_override_url_wins_over_base(self) -> None:
        settings = _settings(
            {
                "SPRING_BOOT_INTERNAL_URL": "http://api:8080/",
                "SPRING_BOOT_PROJECT_PERMISSIONS_URL": "http://perm:9000/custom",
            }
        )
        self.assertEqual(settings.spring_project_permissions_url, "http://perm:9000/custom")
        self.assertEqual(
            settings.spring_history_messages_url, "http://api:8080/api/internal/history/messages"
        )


class DatabaseUrlTest(unittest.TestCase):
    def test_special_characters_in_password_are_escaped(self) -> None:
        password = "p@ss/w:rd#100%"
        settings = _settings(
            {
                "CORE_POSTGRES_HOST": "postgres",
                "CORE_POSTGRES_PORT": "5432",
                "CORE_POSTGRES_DB": "theseus_core",
                "CORE_POSTGRES_USER": "theseus",
                "CORE_POSTGRES_PASSWORD": password,
            }
        )

        parsed = make_url(settings.database_url.render_as_string(hide_password=False))
        self.assertEqual(parsed.host, "postgres")
        self.assertEqual(parsed.port, 5432)
        self.assertEqual(parsed.database, "theseus_core")
        self.assertEqual(parsed.username, "theseus")
        self.assertEqual(parsed.password, password)

    def test_non_public_schema_sets_search_path(self) -> None:
        self.assertEqual(_settings({}).database_connect_args, {})
        self.assertEqual(
            _settings({"CORE_POSTGRES_SCHEMA": "core"}).database_connect_args,
            {"options": "-csearch_path=core,public"},
        )


if __name__ == "__main__":
    unittest.main()
