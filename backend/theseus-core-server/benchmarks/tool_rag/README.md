# Tool RAG 평가 하네스

`theseus_engine/core/tool_retriever.py`(도구 검색)를 고정된 평가셋으로 측정하는 오프라인 벤치마크입니다.
검색 기법을 바꿀 때마다 같은 질의, 같은 지표 정의로 베이스라인과 비교할 수 있게 하는 것이 목적입니다.
서버 이미지에는 들어가지 않습니다(`.dockerignore`에서 제외).

| 파일 | 내용 |
|---|---|
| `eval_set.jsonl` | 동결 평가셋 236개 질의(한국어 164 / 영어 72, single 134 · multi 67 · none 35, dev/test 118/118). 수정 금지. 하네스가 sha256으로 검증합니다. |
| `harness.py` | `build_registry`, `Retriever` 프로토콜, `evaluate`, 지표 함수 |
| `baseline.py` | 현재 `ToolRetriever`를 수정 없이 감싼 `BaselineRetriever` |
| `run.py` | CLI |
| `_env.py` | 결정성 고정(피드백 로그를 빈 디렉터리로, HF 오프라인, 바이트코드 끔). 패키지 import 시 먼저 실행됩니다. |
| `results/baseline_{dev,test,all}.json` | 현재 저장소 베이스라인 결과 |

## 평가 프로토콜 (반드시 지킬 것)

1. 기법을 고르고 하이퍼파라미터를 튜닝할 때는 **dev 분할만** 씁니다.
2. **test 분할은 최종 구성과 베이스라인에 대해 한 번만** 평가합니다. test 결과를 보고 다시 튜닝하지 않습니다.
3. `eval_set.jsonl`의 질의와 라벨은 고치지 않습니다. 바뀌면 `load_eval_set`이 해시 불일치로 평가를 거부합니다.
4. 결과를 옮길 때는 측정한 숫자와 그 명령을 그대로 적습니다(결과 JSON의 `meta.command`, `meta.commit`).

## 측정 항목

정의는 동결 베이스라인 벤치(`bench.py`)와 같습니다. 헤드라인 레지스트리는 `core`(ALL_CORE_TOOLS, CLI/TUI/runner와 Remote Workspace 없는 서버)이고, 이때는 `registry == "core"`인 질의 213개만 씁니다. `--registry server`는 Remote Workspace 도구(remote_*)까지 넣은 서버 레지스트리로 236개 전체를 씁니다.

| 지표 | 정의 |
|---|---|
| R@k, nDCG@k, all_gold@k (k=3,5,8) | **유사도 슬롯**만 평가: 필수 도구 8개(`FROZEN_ESSENTIALS`)는 예측과 정답에서 모두 뺍니다. 대상은 정답 type이 none이 아니고 필수가 아닌 정답이 1개 이상인 질의(core 전체 기준 n=129). nDCG 등급은 정답 순서대로 1/(i+1), log2 할인. |
| MRR, Hit@1, primary@1 | 같은 대상. primary@1은 1순위가 첫 번째 정답인지. |
| 언어별 | 위 지표를 `lang=ko`, `lang=en`(그리고 type, split, ambiguous)으로 나눈 값 |
| none 판정 P/R/F1 | 양성 = 정답 type이 `none`인 질의. 예측 = `decide_none(q)`, 없으면 `rag_failed`(전달 집합에 필수 외 도구가 0개 → engine_builder가 tool_search를 붙이는 조건). 예측 양성이 0건이면 precision=0. |
| set_recall_delivered | LLM이 실제로 받는 집합에서 정답(필수 포함 전체 정답)의 재현율. 전달 집합 = `select(q)` → AGENT 모드 가시성 필터(user_level=5) → rag_failed면 tool_search 추가. `select`가 없으면 필수 ∪ 유사도 상위 8. |
| 스키마 토큰 | 전달 집합 도구들의 `to_api_schema()` 압축 JSON을 tiktoken `cl100k_base`로 센 합(로컬 모델 토크나이저의 **프록시**). 평균·p95. |
| 웜 지연 p50/p95 | 모델·인덱스가 준비된 상태에서 `select(q)`(없으면 `rank(q)`) 1회 시간. 매 호출 전 `clear_cache()`로 쿼리 캐시를 비웁니다. 기본 3회 반복. |
| 콜드 로드, RSS 증가 | `load()` 시간과 그 전후 프로세스 RSS 차이. 프로세스에서 처음 `load()`할 때만 의미가 있습니다. `uses_torch=True` 변형은 torch import·시드·스레드(4) 고정 뒤에 기준점을 잡습니다(동결 벤치와 같은 순서). torch를 안 쓰는 변형과 비교할 때는 `rss_after_eval_mb`(절대값)도 함께 보세요. |

결과 JSON의 `summary`에 위 지표가 평평하게 정리돼 있고, 나머지 블록(`ranking_sim_slots_excl_essentials`, `delivered_set`, `none_detection`, `prompt_tokens_cl100k`, `latency`, `resources`, `hubness_top3_counts`, `per_item`)에 세부 값이 있습니다.

## 실행

준비물: Python 3.12, `requirements.txt`의 런타임 의존성(sentence-transformers, torch CPU, paramiko 등) + `tiktoken`, `psutil`.
임베딩 모델 `intfloat/multilingual-e5-small` 리비전 `614241f6…`이 `HF_HOME` 캐시에 있으면 하네스가 HF를 오프라인으로 고정합니다.

`backend/theseus-core-server`에서 실행합니다(그래야 `benchmarks`와 `theseus_engine`이 import됩니다).

```bash
cd backend/theseus-core-server
export PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 HF_HOME=<모델 캐시> HF_HUB_OFFLINE=1
python -m benchmarks.tool_rag.run --variant baseline --split dev
python -m benchmarks.tool_rag.run --variant baseline --split all --json benchmarks/tool_rag/results/baseline_all.json
```

주요 옵션: `--split dev|test|all`(기본 dev), `--registry core|server`(기본 core), `--json 경로`, `--passes N`(지연 반복, 0이면 생략), `--threads N`(torch 스레드, 기본 4), `--no-per-item`, `--variant-kwargs '{"base_k": 5}'`.

`--variant`에는 `baseline`, `패키지.모듈:클래스`, 또는 `C:/어딘가/my_variant.py:클래스`(저장소 밖 파일)를 줄 수 있습니다.

## 저장소 밖에서 변형 실험하기

스크래치 폴더에 변형 클래스를 만들고 하네스를 import해서 바로 평가합니다. 하네스는 `__file__` 기준으로 평가셋과 서버 코드를 찾으므로 경로 하나만 추가하면 됩니다.

```python
import sys
sys.path.insert(0, r"c:\DEV\Theseus\backend\theseus-core-server")  # theseus_engine보다 먼저
from benchmarks.tool_rag import harness


class MyRetriever:
    name = "my-variant"
    uses_torch = False          # torch를 쓰면 True (시드·스레드 고정)

    def load(self):             # 선택: 모델 로드 (콜드 로드·RSS 측정 구간)
        ...

    def index(self, registry):  # 선택: 평가 레지스트리를 받아 인덱스 구축
        self.tools = registry.list_tools()

    def rank(self, query):      # 필수: [(tool_name, score), ...] 내림차순
        return [(t.name, 0.0) for t in self.tools]

    # 선택: select(query) -> list[str]   실제 LLM 전달 집합(가시성 필터 전)
    # 선택: decide_none(query) -> bool   "맞는 도구 없음" 판정
    # 선택: clear_cache(), meta() -> dict


result = harness.evaluate(MyRetriever(), split="dev")   # 튜닝은 dev만
print(harness.format_summary(result))
print(result["summary"]["r3"], result["summary"]["mrr"])
```

CLI로도 같습니다.

```bash
cd backend/theseus-core-server
python -m benchmarks.tool_rag.run --variant "C:/scratch/my_variant.py:MyRetriever" --split dev --json C:/scratch/my_dev.json
```

규칙:
- `rank()`가 레지스트리에 없는 이름을 내면 오류입니다. 필수 도구를 포함해도 되고 빼도 됩니다(지표 계산에서 제외).
- 저장소 코드를 수정한 변형은 결과 `meta.engine_src_dirty`가 true로 기록됩니다.
- 하네스는 피드백 로그(`tool_usage.jsonl`)를 빈 임시 디렉터리로 돌려 개발자 사용 이력이 few-shot에 섞이지 않게 합니다.
- `harness.build_registry("core" | "server")`로 평가 레지스트리를 직접 만들 수도 있습니다.

## 베이스라인 결과 (현재 저장소, core 레지스트리)

커밋 3b9467e, Windows 11 / Python 3.12.13 / torch 2.15.0+cpu (4 스레드) / sentence-transformers 6.3.0.
명령: `python -m benchmarks.tool_rag.run --variant baseline --split {dev,test,all} --json benchmarks/tool_rag/results/baseline_{split}.json`

| split | n | R@3 | R@3 KO | R@3 EN | R@5 | R@8 | nDCG@5 | MRR | Hit@1 | set_recall_delivered | 스키마 토큰 평균 / p95 | none F1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 59 | 0.568 | 0.512 | 0.684 | 0.658 | 0.751 | 0.555 | 0.619 | 0.508 | 0.829 | 1897 / 2444 | 0.000 |
| test | 70 | 0.636 | 0.550 | 0.812 | 0.681 | 0.773 | 0.576 | 0.608 | 0.486 | 0.816 | 1939 / 2393 | 0.000 |
| all | 129 | 0.605 | 0.533 | 0.754 | 0.671 | 0.763 | 0.566 | 0.613 | 0.496 | 0.822 | 1918 / 2417 | 0.000 |

- none F1 0: 임계값 0.3이 한 번도 걸리지 않아(rag_failed 0건) none 질의 35개를 하나도 잡지 못합니다.
- 전체 도구 스키마 5318 토큰, 필수 도구만 1697 토큰.
- 웜 지연 p50 16–17 ms / p95 23–25 ms, 콜드 로드 10.5–10.9 s, 모델 로드 RSS 증가 약 955 MB(측정마다 조금씩 다름).

### 동결 베이스라인(2026-11-15)과의 차이

동결 원본은 R@3 0.597 / MRR 0.607 / 스키마 토큰 평균 1909였고, 현재 저장소는 R@3 0.605 / MRR 0.613 / 1918입니다.
원인은 지표 코드가 아니라 레지스트리 변경입니다. 원본 측정 뒤 커밋 4a2d1f0에서 데모 도구 `dummy_echo`, `system_reboot`가
`ALL_CORE_TOOLS`에서 빠져 core 도구가 38개에서 36개가 됐습니다. 이 두 도구가 영어 질의에서 상위 슬롯을 차지하던 자리가 비면서
R@3(EN 0.730 → 0.754)이 올랐고, 그 자리에 스키마가 더 긴 도구가 들어와 토큰 평균이 조금 늘었습니다.

`--legacy-demo-tools`로 두 도구를 맨 앞에 다시 넣으면 동결 원본을 그대로 재현합니다.
core·server 두 레지스트리 모두 유사도 슬롯 지표 전 항목(모든 분할·언어·type 분해)의 최대 차이 0, set_recall_delivered 0.822097 /
0.764096, 토큰 평균 1908.98 / 1887.90, 상위 3 hubness 집계까지 동일했습니다.

```bash
python -m benchmarks.tool_rag.run --variant baseline --split all --legacy-demo-tools --passes 0
# [baseline] split=all registry=core n=129
#   R@3 0.597 (KO 0.533 / EN 0.730)  R@5 0.660  R@8 0.763  nDCG@5 0.557  MRR 0.607  Hit@1 0.488
```

새 변형은 현재 저장소 베이스라인(`results/baseline_*.json`)과 비교합니다. `--legacy-demo-tools`는 재현 확인용으로만 씁니다.
