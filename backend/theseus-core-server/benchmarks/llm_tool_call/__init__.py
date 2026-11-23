"""LLM 도구 호출 평가 하네스.

운영 서버와 같은 경로(src.builder.engine.get_query_engine → QueryEngine → TheseusLLMClient)로 첫 턴
요청을 만들어 LLM에 보내고, 모델이 고른 도구와 인자를 채점합니다. 자세한 내용은 README.md.

import 시 benchmarks.tool_rag._env가 먼저 실행되어 피드백 로그·HF 오프라인·바이트코드 설정을 고정합니다.
"""

from benchmarks.tool_rag import _env  # noqa: F401  # 반드시 가장 먼저
