# LLM 도구 호출 평가 하네스

운영 서버와 같은 코드 경로로 LLM의 도구 호출을 측정하는 오프라인 벤치마크입니다. 3단계(로컬 LLM 파인튜닝·양자화)에서
기성 모델과 튜닝한 모델, 양자화 수준별 모델을 같은 정의로 비교하는 것이 목적입니다. 서버 이미지에는 들어가지 않습니다
(`.dockerignore`에서 `benchmarks/` 제외).

## 무엇을 재현하나

질의마다 `src.builder.engine.get_query_engine(EngineBuildContext(...))`으로 서버 엔진을 그대로 조립하고, LLM 클라이언트만
`RecordingClient`로 감쌉니다. 그래서 다음이 모두 운영 코드 그대로입니다.

- 시스템 프롬프트(모드, 보낸 도구에 따른 capability 섹션, 런타임 리마인더)
- 가시성·RBAC 필터(AGENT 모드, user_level=5, 서버 기본값으로 엔진 RAG 도구 숨김), Remote Workspace 질의는 더미 설정으로 remote 도구 포함
- Tool RAG v2 선택(필수 도구 + `tool_search` + 비용 인식 슬롯)
- 도구 스키마 변환, 메시지 변환, Ollama OpenAI 호환 스트리밍 호출과 `tool_calls` 파싱, 도구 실행, 훅

운영과 다른 점은 재현성 때문에 둔 것뿐입니다.

| 항목 | 하네스 | 운영 |
|---|---|---|
| 환경 섹션 | 운영 Core 컨테이너 값으로 고정(날짜만 상수) | 실행 환경 값 |
| 샘플링 | 요청에 `seed`만 추가(`--temperature`를 주면 그 값도) | 아무 값도 보내지 않음(Modelfile 기본값: temperature 0.7, top_p 0.8, top_k 20) |
| Tool RAG | 미리 워밍업 | 워밍업 전 요청은 보이는 도구 전부를 받음 |
| 작업 디렉터리 | fixture: 이 서버 코드의 git HEAD 스냅샷(`benchmarks/` 제외) + 질의에 나온 파일의 자리표시 | `/app` |

## 에피소드와 채점

한 질의는 최대 `--max-turns`(기본 3) LLM 턴까지 진행합니다. 모델이 탐색용 읽기 전용 도구(`SAFE_TOOLS`: read_file, glob,
grep, lsp, tool_search, memory/skill/task 조회 등)만 부르면 엔진이 fixture에서 실제로 실행하고 다음 턴으로 갑니다. 다음 경우에
멈춥니다. 멈출 때 부른 도구는 실행하지 않습니다(부작용 없음).

- 정답 도구를 불렀을 때(`relevant_call`)
- 탐색 도구가 아닌 다른 도구를 불렀을 때(`other_action`)
- 도구 없이 답했을 때(`text_answer`), `max_turns`에 닿았을 때

| 지표 | 정의 |
|---|---|
| `success_at_1` | 답이 있는 질의(type ≠ none)에서 첫 턴 호출 중 하나가 정답 도구인 비율. 환경(fixture)의 영향을 받지 않는 **주 지표** |
| `success_at_k` | k턴 안에 정답 도구를 부른 비율. `_valid`는 그 호출의 인자가 스키마 검증을 통과한 경우만 |
| `success_at_k_retrievable` | Tool RAG가 정답 도구를 보낸 질의만 본 `success_at_k`(검색 실패를 뺀 LLM 몫) |
| `none_at_1`, `none_at_k` | 정답이 none인 질의에서, 도구를 안 부르거나 `tool_search`/`create_tool`만 부른 비율(k턴은 탐색 도구 허용) |
| `wrong_action_rate` | 정답이 아닌 작업 도구를 불러 멈춘 비율 |
| `text_answer_rate`, `max_turns_rate` | 도구 없이 답하고 끝난 비율, 탐색만 하다 턴이 끝난 비율 |
| `call_args_valid` | 모든 호출 중 인자가 운영과 같은 기준(`input_model.model_validate`, JSON 파싱 오류 없음)을 통과한 비율 |
| `not_offered_call_rate` | 그 턴에 보내지 않은 도구 이름을 부른 질의 비율 |
| `text_tool_call_leak_rate` | `tool_calls` 없이 본문에 도구 호출처럼 보이는 텍스트를 쓴 비율(운영 파서는 이를 버림) |
| 지연 | 첫 턴 지연 p50/p95, 에피소드 전체 지연 p50 |

`--samples` 회 반복(seed = `seed_base + i`)한 샘플별 지표의 평균과 표준편차를 `summary`에, 질의별 평균 성공률로 낸 언어·유형·
분할·레지스트리별 값을 `breakdown`에, 샘플 사이에 결과가 갈린 질의를 `unstable_cases`에 씁니다.

운영 요청은 도구가 있으면 `stream_options.include_usage`를 빼므로 Ollama가 토큰 수를 돌려주지 않습니다. 그래서 토큰 지표는 없습니다.

## 데이터와 평가 프로토콜

질의와 라벨은 Tool RAG 하네스의 동결 세트를 그대로 씁니다(`benchmarks/tool_rag/`, sha256 검증).

- `--split dev`: `eval_set.jsonl` dev 118개. **개발·튜닝은 이것만** 씁니다.
- `--split final`: `eval_set.jsonl` test 118개 + `holdout_set.jsonl` 140개. 최종 구성과 비교 대상에 **한 번만** 씁니다.
- 학습 데이터는 이 세트들의 질의를 보지 않고 만들고, 근접 중복(임베딩·n-gram)을 제거한 뒤 씁니다.
- 결과를 옮길 때는 결과 JSON의 `meta.command`, `meta.commit`, `meta.model`을 함께 적습니다.

## 실행

결과에 쓰는 측정은 **Core 이미지 컨테이너 안에서** 돌립니다. 도구 결과에는 작업 디렉터리의 절대 경로가 들어가는데, 호스트(Windows)에서
돌리면 모델이 운영(`/app`, Linux)과 다른 경로를 보고, 결과 JSON에 개인 로컬 경로가 남습니다. 컨테이너에서는 운영과 같은 venv·Python·
임베딩 모델을 쓰고, 이미지의 `/app`(서버 코드, `benchmarks/` 없음)이 그대로 fixture가 됩니다.

```bash
# backend/theseus-core-server에서 이미지를 빌드하고, 노트북 llm-gateway 네트워크로 필터(운영이 터널로 쓰는 경로)에 붙습니다.
docker build -t theseus-core:phase3-eval .
docker run --rm --user root --network theseus-llm_default \
  -v "$PWD:/src:ro" -v "$PWD/benchmarks/llm_tool_call/results:/out" -w /src \
  -e BENCH_COMMIT="$(git rev-parse --short=12 HEAD)" -e BENCH_RUNTIME=core-image \
  theseus-core:phase3-eval python -m benchmarks.llm_tool_call.run \
    --split dev --model qwen3:4b-instruct-2507-q4_K_M --base-url http://llm-filter:8080/v1 \
    --fixture-dir /app --samples 3 --out /out/base_q4km_dev.json
```

- `--user root`: 질의에 나온 파일의 자리표시를 `/app`에 쓰기 위해서입니다(컨테이너는 실행 후 지워짐).
- 하네스 코드는 `/src`(읽기 전용)에서 import하고, 작업 디렉터리만 `/app`으로 바꿉니다.
- 호스트 venv에서 `--fixture-dir` 없이 돌리면 git 스냅샷을 임시 fixture로 씁니다. 빠른 점검용이고 결과에는 쓰지 않습니다.
