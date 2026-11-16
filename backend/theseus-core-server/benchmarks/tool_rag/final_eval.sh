set -u
SRV=/c/DEV/Theseus/backend/theseus-core-server
OLD=/c/DEV/Theseus-wt/eval-87df973/backend/theseus-core-server
export PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 THESEUS_EMBED_MODEL_DIR=C:/Users/SSAFY/.theseus/models/e5-small-int8 HF_HUB_OFFLINE=1 HF_HOME=C:/DEV/Theseus-wt/toolrag-env/hf_home
P2=/c/DEV/Theseus-wt/toolrag-env/v2/Scripts/python.exe
P1=/c/DEV/Theseus-wt/toolrag-env/v1/Scripts/python.exe
R=$SRV/benchmarks/tool_rag/results
f() { grep -v -i "warning\|TripleDES\|algorithms\." ; }
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
