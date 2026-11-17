# Tool RAG 최종 평가(홀드아웃 1회 + test·all 재측정)를 만든 명령입니다. 결과는 results/에 씁니다.
#
# 사용법 (Git Bash/Linux):
#   export PY_V2=<v2 환경 python>            # onnxruntime 등 requirements.txt + tiktoken, psutil
#   export PY_V1=<v1 베이스라인 환경 python>  # torch + sentence-transformers (requirements-torch.txt)
#   export OLD_TREE=<개선 전 커밋(87df973) worktree 루트>
#                                            # git worktree add <경로> 87df973 뒤, 현재 benchmarks/tool_rag/의
#                                            # 하네스(harness.py, run.py 등, holdout 분할 지원)를 그 worktree에 복사합니다.
#   export THESEUS_EMBED_MODEL_DIR=<e5-small-int8 모델 디렉터리>
#   export HF_HOME=<intfloat/multilingual-e5-small 캐시가 있는 HF 캐시>   # v1 베이스라인용
#   bash benchmarks/tool_rag/final_eval.sh
#
# 홀드아웃은 최종 구성에 대해 한 번만 평가합니다. 이 스크립트를 다시 돌려 결과를 보고 튜닝하지 않습니다.
# 3ef5ee0의 실행 뒤에 추가한 것: 실패한 실행이 커밋된 옛 JSON을 compare에 넘기지 않도록 -e·pipefail로 멈추고(f는 grep이 줄을
# 하나도 안 남겨도 실패로 보지 않음), v1 per_item의 필수 도구 순서(집합 순회)가 실행마다 같도록 PYTHONHASHSEED=0을 둡니다.
# 둘 다 지표에는 영향이 없습니다.
set -euo pipefail
for v in PY_V2 PY_V1 OLD_TREE THESEUS_EMBED_MODEL_DIR HF_HOME; do
  if [ -z "${!v:-}" ]; then
    echo "final_eval.sh: 환경 변수 $v가 비어 있습니다. 파일 맨 위 사용법을 보세요." >&2
    exit 2
  fi
done
SRV=$(cd "$(dirname "$0")/../.." && pwd)
OLD=$OLD_TREE/backend/theseus-core-server
if [ ! -d "$OLD/benchmarks/tool_rag" ]; then
  echo "final_eval.sh: $OLD/benchmarks/tool_rag가 없습니다. OLD_TREE는 개선 전 커밋 worktree의 루트여야 합니다." >&2
  exit 2
fi
export PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 THESEUS_EMBED_MODEL_DIR HF_HOME
P2=$PY_V2
P1=$PY_V1
R=$SRV/benchmarks/tool_rag/results
f() { grep -v -i "warning\|TripleDES\|algorithms\." || true; }
cd $SRV
for reg in core server server-default; do
  sfx=$([ $reg = core ] && echo "" || echo "_${reg//-/_}")
  ps=$([ $reg = core ] && echo 3 || echo 0)
  echo "=== v2 holdout $reg"; $P2 -m benchmarks.tool_rag.run --variant v2 --split holdout --registry $reg --passes $ps --json $R/v2_holdout$sfx.json 2>&1 | f
  echo "=== all-visible holdout $reg"; $P2 -m benchmarks.tool_rag.run --variant all-visible --split holdout --registry $reg --passes 0 --json $R/all_visible_holdout$sfx.json 2>&1 | f
  echo "=== baseline holdout $reg"; $P1 -m benchmarks.tool_rag.run --variant baseline --split holdout --registry $reg --passes $ps --json $R/baseline_holdout$sfx.json 2>&1 | f
  echo "=== v2-pre(87df973) holdout $reg"; (cd $OLD && $P2 -m benchmarks.tool_rag.run --variant v2 --split holdout --registry $reg --passes 0 --json $R/v2pre_holdout$sfx.json 2>&1 | f)
done
for sp in test all; do
  echo "=== v2 $sp core"; $P2 -m benchmarks.tool_rag.run --variant v2 --split $sp --json $R/v2_$sp.json 2>&1 | f
  for reg in server server-default; do echo "=== v2 $sp $reg"; $P2 -m benchmarks.tool_rag.run --variant v2 --split $sp --registry $reg --passes 0 --json $R/v2_${reg//-/_}_$sp.json 2>&1 | f; done
done
for sfx in "" _server _server_default; do
  echo "=== compare baseline vs v2 holdout$sfx"; $P2 -m benchmarks.tool_rag.compare $R/baseline_holdout$sfx.json $R/v2_holdout$sfx.json --json $R/compare_baseline_v2_holdout$sfx.json 2>&1 | f
  echo "=== compare v2pre vs v2 holdout$sfx"; $P2 -m benchmarks.tool_rag.compare $R/v2pre_holdout$sfx.json $R/v2_holdout$sfx.json --json $R/compare_v2pre_v2_holdout$sfx.json 2>&1 | f
done
for sp in test all; do echo "=== compare baseline vs v2 $sp"; $P2 -m benchmarks.tool_rag.compare $R/baseline_$sp.json $R/v2_$sp.json --json $R/compare_baseline_v2_$sp.json 2>&1 | f; done
echo FINAL_DONE
