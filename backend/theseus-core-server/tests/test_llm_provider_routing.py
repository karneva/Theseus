"""LLM provider 라우팅 테스트.

명시적 `provider/` 접두사가 모델명 부분 문자열 추정보다 우선해야 합니다.
예전에는 `ollama/deepseek-r1`이 이름의 deepseek 때문에 DeepSeek 클라우드로 갔습니다.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from theseus_engine.config import (
    PROVIDER_ANTHROPIC,
    PROVIDER_DEEPSEEK,
    PROVIDER_GEMINI,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    PROVIDER_VLLM,
    get_llm_settings,
    resolve_provider,
)
from theseus_engine.wrappers.llm_clients.anthropic_client import TheseusAnthropicClient
from theseus_engine.wrappers.llm_clients.openai_compat_client import TheseusOpenAICompatClient
from theseus_engine.wrappers.llm_clients.theseus_client import (
    TheseusGeminiClient,
    TheseusLLMClient,
)

LLM_ENV_KEYS = (
    "OLLAMA_BASE_URL",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_BASE_URL",
    "DEEPSEEK_BASE_URL",
    "THESEUS_LLM_TIMEOUT_SECONDS",
    "THESEUS_LLM_MAX_RETRIES",
    "LLM_MAX_OUTPUT_TOKENS",
    "THESEUS_MODEL_ROUTING",
)


class _CleanLLMEnv:
    """LLM 관련 환경변수를 비운 상태에서 주어진 값만 설정합니다."""

    def __init__(self, **values: str) -> None:
        self._values = values
        self._patch = patch.dict(os.environ, {}, clear=False)

    def __enter__(self) -> None:
        self._patch.start()
        for key in LLM_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update(self._values)

    def __exit__(self, *exc: object) -> None:
        self._patch.stop()


class ResolveProviderTest(unittest.TestCase):
    def test_explicit_prefix_wins_over_substring_guess(self) -> None:
        cases = {
            "ollama/deepseek-r1": (PROVIDER_OLLAMA, "deepseek-r1"),
            "ollama/deepseek-r1:7b": (PROVIDER_OLLAMA, "deepseek-r1:7b"),
            "vllm/claude-x": (PROVIDER_VLLM, "claude-x"),
            "vllm/meta-llama/Llama-3.1-8B-Instruct": (
                PROVIDER_VLLM,
                "meta-llama/Llama-3.1-8B-Instruct",
            ),
            "openai/gemini-lookalike": (PROVIDER_OPENAI, "gemini-lookalike"),
            "anthropic/claude-sonnet-4": (PROVIDER_ANTHROPIC, "claude-sonnet-4"),
            "gemini/gemini-2.5-pro": (PROVIDER_GEMINI, "gemini-2.5-pro"),
            "google/gemini-1.5-flash": (PROVIDER_GEMINI, "gemini-1.5-flash"),
            "deepseek/deepseek-chat": (PROVIDER_DEEPSEEK, "deepseek-chat"),
            "Ollama/Qwen2.5": (PROVIDER_OLLAMA, "Qwen2.5"),
        }
        for model, (provider, model_id) in cases.items():
            with self.subTest(model=model):
                route = resolve_provider(model)
                self.assertEqual(route.provider, provider)
                self.assertEqual(route.model_id, model_id)
                self.assertTrue(route.explicit)

    def test_substring_guess_without_prefix(self) -> None:
        cases = {
            "claude-3-5-sonnet-20241022": PROVIDER_ANTHROPIC,
            "gemini-1.5-pro": PROVIDER_GEMINI,
            "deepseek-chat": PROVIDER_DEEPSEEK,
            "gpt-4o": PROVIDER_OPENAI,
            "o1-mini": PROVIDER_OPENAI,
        }
        for model, provider in cases.items():
            with self.subTest(model=model):
                route = resolve_provider(model)
                self.assertEqual(route.provider, provider)
                self.assertEqual(route.model_id, model)
                self.assertFalse(route.explicit)

    def test_bare_vllm_keeps_auto_discovery_name(self) -> None:
        route = resolve_provider("vllm")
        self.assertEqual(route.provider, PROVIDER_VLLM)
        self.assertEqual(route.model_id, "vllm")

    def test_unknown_prefix_is_not_stripped(self) -> None:
        route = resolve_provider("meta-llama/Llama-3.1-8B")
        self.assertEqual(route.provider, PROVIDER_OPENAI)
        self.assertEqual(route.model_id, "meta-llama/Llama-3.1-8B")


class LLMSettingsTest(unittest.TestCase):
    def test_defaults(self) -> None:
        with _CleanLLMEnv():
            llm = get_llm_settings()
        self.assertEqual(llm.ollama_base_url, "http://localhost:11434/v1")
        self.assertIsNone(llm.openai_base_url)
        self.assertEqual(llm.vllm_base_url, "http://localhost:8000/v1")
        self.assertEqual(llm.timeout_seconds, 120.0)
        self.assertEqual(llm.max_retries, 3)
        self.assertEqual(llm.max_output_tokens, 32768)

    def test_env_overrides_and_invalid_values_fall_back(self) -> None:
        with _CleanLLMEnv(
            OLLAMA_BASE_URL="http://ollama:11434/v1",
            OPENAI_BASE_URL="http://vllm:8000/v1",
            THESEUS_LLM_TIMEOUT_SECONDS="45",
            THESEUS_LLM_MAX_RETRIES="not-a-number",
            LLM_MAX_OUTPUT_TOKENS="4096",
        ):
            llm = get_llm_settings()
        self.assertEqual(llm.ollama_base_url, "http://ollama:11434/v1")
        self.assertEqual(llm.vllm_base_url, "http://vllm:8000/v1")
        self.assertEqual(llm.timeout_seconds, 45.0)
        self.assertEqual(llm.max_retries, 3)
        self.assertEqual(llm.max_output_tokens, 4096)


class BackendSelectionTest(unittest.TestCase):
    def test_ollama_deepseek_uses_ollama_base_url_without_deepseek_key(self) -> None:
        with _CleanLLMEnv(OLLAMA_BASE_URL="http://ollama:11434/v1"):
            client = TheseusLLMClient("ollama/deepseek-r1")

        backend = client._backend
        self.assertIsInstance(backend, TheseusOpenAICompatClient)
        self.assertNotIsInstance(backend, TheseusGeminiClient)
        self.assertEqual(str(backend._client.base_url).rstrip("/"), "http://ollama:11434/v1")

    def test_vllm_claude_uses_vllm_backend(self) -> None:
        with _CleanLLMEnv(OPENAI_BASE_URL="http://vllm:8000/v1", THESEUS_LLM_MAX_RETRIES="1"):
            client = TheseusLLMClient("vllm/claude-x")

        backend = client._backend
        self.assertIsInstance(backend, TheseusOpenAICompatClient)
        self.assertEqual(str(backend._client.base_url).rstrip("/"), "http://vllm:8000/v1")
        self.assertEqual(backend._max_retries, 1)

    def test_anthropic_prefix_uses_anthropic_backend(self) -> None:
        with _CleanLLMEnv(ANTHROPIC_API_KEY="sk-ant-unit-test-key"):
            client = TheseusLLMClient("anthropic/claude-sonnet-4")
        self.assertIsInstance(client._backend, TheseusAnthropicClient)

    def test_gemini_prefix_uses_gemini_backend(self) -> None:
        with _CleanLLMEnv(GEMINI_API_KEY="gemini-unit-test-key"):
            client = TheseusLLMClient("gemini/gemini-2.5-pro")
        self.assertIsInstance(client._backend, TheseusGeminiClient)


if __name__ == "__main__":
    unittest.main()
