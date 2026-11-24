"""도구 호출 SFT 데이터 생성 파이프라인(교사 모델 + 운영 경로 + 자동 검증).

단계(각 단계는 앞 단계 JSONL을 읽고 다음 JSONL을 씁니다). 유료 단계는 표시했습니다.
  catalog   운영 서버 엔진이 AGENT 모드(user_level=5)에서 보이는 도구와 /app 파일 목록을 씁니다.
  queries   [유료] 범주별로 교사 모델이 질의를 만듭니다. 문체·길이·단서는 코드가 뽑은 "스타일 카드"로 정하고,
            파일을 다루는 범주는 /app의 실제 코드 조각을 근거로 줍니다. 평가 세트 질의는 교사에게 보여주지 않습니다.
            만든 뒤 경로가 /app에 실제로 있는지, 따옴표·백틱으로 인용한 코드가 그 파일에 있는지 확인해 거릅니다.
  dedup     평가 세트(eval_set + holdout)와 근접 중복인 질의, 같은 범주·언어 안의 근접 중복을 뺍니다.
  stats     질의 분포(길이, 문장 수, 단서, 경로, 존댓말 수준)를 목표 범위와 비교합니다.
  episodes  [유료] 질의마다 운영 엔진을 그대로 조립하고 LLM 백엔드만 교사 모델로 바꿔 최대 3턴 궤적을 만듭니다.
            탐색용 읽기 전용 도구(harness.SAFE_TOOLS)는 /app에서 실제로 실행하고, 목표 도구나 다른 작업 도구를
            부르면 실행하지 않고 멈춥니다(평가 하네스와 같은 규칙). 턴마다 운영이 보낸 요청을 그대로 기록합니다.
  validate  궤적을 범주별 규칙과 운영 기준(보낸 도구인가, input_model 검증, 반복 호출 없음, edit_file은 실제 파일에
            적용해 봄)으로 검증해, 통과한 궤적의 턴마다 SFT 예제(그 턴의 messages + tools → 정답 assistant 턴)를 씁니다.

모든 유료 호출은 공유 지출 기록(--spend-log)에 한 줄씩 남기고, 호출 전에 최악 비용을 예약해 --budget-usd를 넘지
않게 합니다. 가격을 모르는 모델은 거부합니다. 결과는 한 건씩 바로 파일에 덧붙이고, 다시 실행하면 끝난 id는 건너뜁니다.
API 키는 환경 변수 OPENAI_API_KEY로만 받고 어디에도 쓰지 않습니다. 교사 요청은 store=False로 보냅니다.

catalog·queries·episodes·validate는 Core 이미지 컨테이너(/app = 운영 코드)에서 돌립니다(README.md "학습 데이터 생성").
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import os
import random
import re
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from benchmarks.tool_rag import _env  # noqa: F401  # 반드시 가장 먼저

# 100만 토큰당 USD(OpenAI 공식 표준 요금). 여기 없는 모델은 예산을 지킬 수 없으므로 거부합니다.
PRICES = {
    "gpt-6.1-sol": {"input": 2.00, "cached": 0.10, "output": 10.00},
}

APP_DIRS = ("src", "theseus_engine")  # Core 이미지가 /app에 복사하는 것(Dockerfile COPY)

# ── 범주 ─────────────────────────────────────────────────────
# target: 궤적이 끝나야 하는 도구(clarify는 ask_user 또는 되묻는 본문, none은 본문).
# via: 목표 전에 허용하는 탐색 도구(SAFE_TOOLS의 부분집합). 빈 튜플이면 첫 턴에 목표를 불러야 합니다.
# anchors: 스타일 카드의 단서 종류와 비율. snippets: 실제 코드 조각을 근거로 줄지.
CATEGORIES: dict[str, dict[str, Any]] = {  # 각 항목에 name이 아래에서 채워짐
    "read_direct": {
        "target": "read_file",
        "via": (),
        "gloss": "show, open, or explain the contents of one specific existing file (optionally a part of it)",
        "anchors": {"path": 1.0},
        "snippets": True,
    },
    "read_loose": {
        "target": "read_file",
        "via": ("glob", "grep"),
        "gloss": "look at the code of a file the user describes only by what it does or roughly where it is (no exact path), so the agent must locate it first",
        "anchors": {"none": 0.6, "identifier": 0.25, "directory": 0.15},
        "snippets": True,
    },
    "edit": {
        "target": "edit_file",
        "via": ("read_file", "grep", "glob"),
        "gloss": "make a small, concrete change to existing code shown in the snippets (rename, change a default value, add a log line or check, fix a message, adjust a condition). Describe the intent; do not paste the exact old text",
        "anchors": {"path": 0.6, "identifier": 0.25, "none": 0.15},
        "snippets": True,
    },
    "grep": {
        "target": "grep",
        "via": (),
        "gloss": "find where a string, identifier, pattern, or error message appears across the code",
        "anchors": {"identifier": 0.5, "error_text": 0.25, "directory": 0.25},
        "snippets": True,
    },
    "bash": {
        "target": "bash",
        "via": (),
        "gloss": "run a read-only shell command to inspect the runtime environment: installed package versions, python version, disk usage, processes, open ports, environment variables, a quick python -c / syntax check, a localhost health request. The server has no git",
        "anchors": {"none": 0.85, "path": 0.15},
        "snippets": False,
    },
    "memory": {
        "target": "memory_read",
        "via": ("memory_list",),
        "family": ("memory_list", "memory_read"),
        "gloss": "recall something the user or team saved earlier in the agent's memory notes (user/project/local scope)",
        "anchors": {"memory_name": 0.4, "none": 0.6},
        "snippets": False,
        "memory_seed": True,
    },
    # 되묻기는 본문으로만(운영 서버에서 ask_user는 사용자에게 닿지 않음, #59). 교사에게는 ask_user를 보내지 않습니다.
    "clarify": {
        "target": None,
        "final": "clarify_text",
        "via": ("read_file", "grep", "glob"),
        "gloss": "a request the agent cannot carry out correctly without first asking the user: a required value, choice, or attachment is missing or contradictory. Sometimes it names a real file, sometimes not",
        "anchors": {"none": 0.5, "path": 0.5},
        "snippets": True,
    },
    "none": {
        "target": None,
        "final": "text",
        "via": ("tool_search",),
        "gloss": "an ordinary work request that needs an outside service or capability the agent does not have (chat/issue trackers, calendars, email, design tools, image generation/OCR, cloud consoles, phone, payments). Just ask for the action; never ask whether an integration exists",
        "anchors": {"none": 1.0},
        "snippets": False,
    },
    # ── run2에서 더한 범주(run1 오류 분석: 학습 정답에 한 번도 없던 도구, 묻지 말고 해야 할 요청 등) ──
    "none_direct": {  # none과 같은 요청이지만 tool_search 없이 바로 못 한다고 답하는 예(교사에게 tool_search를 숨김)
        "target": None,
        "final": "text",
        "via": (),
        "teacher_hide": ("tool_search",),
        "gloss": "an ordinary work request that needs an outside service or capability the agent does not have (chat/issue trackers, calendars, email, design tools, image generation/OCR, cloud consoles, phone, payments). Just ask for the action; never ask whether an integration exists",
        "anchors": {"none": 1.0},
        "snippets": False,
    },
    "web": {
        "target": ("web_search", "deep_research", "web_fetch"),
        "via": (),
        "gloss": "something that needs the public internet: the latest version, changelog, or release date of a public library or tool; official docs of a public API; searching an error message or a CVE; comparing libraries (a deeper multi-source research request); or reading a web page whose URL the user pasted",
        "anchors": {"none": 0.75, "url": 0.25},
        "snippets": False,
        "max_turns": 4,
    },
    "skill": {
        "target": "skill_read",
        "via": ("skill_list",),
        "family": ("skill_list", "skill_read"),
        "gloss": "reuse a recipe, workflow, or know-how the team saved earlier as an agent skill (e.g. how we release, how we set up a service, our review checklist). Sound like asking for saved know-how, not for code",
        "anchors": {"memory_name": 0.4, "none": 0.6},
        "snippets": False,
        "skill_seed": True,
    },
    "memory_save": {
        "target": "memory_write",
        "via": (),
        "family": ("memory_write",),
        "gloss": "tell the agent to remember a preference, rule, or fact for later (the request itself contains the exact thing to remember)",
        "anchors": {"content": 1.0},
        "snippets": False,
        "grounded_arg": ("content", 0.3),
    },
    "skill_save": {
        "target": "skill_save",
        "via": (),
        "family": ("skill_save",),
        "gloss": "tell the agent to save a short procedure or checklist as a reusable skill (the request itself contains the steps, 2-5 short steps inline)",
        "anchors": {"content": 1.0},
        "snippets": False,
        "grounded_arg": ("content", 0.4),
        "length_override": {"ko": (50, 220), "en": (90, 360)},
    },
    "task": {
        "target": "task_create",
        "gloss": "start a long-running or continuous command that should keep running in the background: a dev server, a file watcher, a long build or test run, a log follower. The command should fit the /app Python project",
        "via": ("read_file", "grep", "glob"),  # 실행할 명령을 정하려고 진입점을 찾아 읽는 것은 자연스러움(습관 필터는 그대로)
        "anchors": {"none": 0.6, "path": 0.4},
        "snippets": False,
        "max_turns": 4,
    },
    "memory_empty": {  # 메모가 하나도 없는 상태의 회상 요청: 목록을 보고 없다고 정직하게 답하거나 스킬을 찾아봄
        "target": ("skill_list", "skill_read"),
        "final": "call_or_text",
        "via": ("memory_list",),
        "family": ("memory_list", "memory_read"),
        "gloss": "recall something the user or team saved earlier in the agent's memory notes (user/project/local scope)",
        "anchors": {"none": 1.0},
        "snippets": False,
    },
    "bash_dev": {
        "target": "bash",
        "via": (),
        "gloss": "run a one-shot development command that finishes quickly in the /app Python project: install or upgrade one package with pip, run a linter or formatter check (ruff, black --check, pyflakes), compile all files, run one module's quick self-check with python -m or python -c, list outdated packages. Not a long-running server or watcher. The server has no git",
        "anchors": {"none": 0.7, "path": 0.3},
        "snippets": False,
    },
}

# 운영 서버(웹 채팅)에서 ask_user는 사용자에게 닿지 않으므로(#59) 교사에게 보내지 않습니다. 학생 예제의 도구 목록은 운영 그대로입니다.
TEACHER_HIDE_ALWAYS = ("ask_user",)


def targets_of(cat: dict) -> frozenset[str]:
    t = cat.get("target")
    if t is None:
        return frozenset()
    return frozenset((t,) if isinstance(t, str) else t)


def family_of(cat: dict) -> frozenset[str]:
    """이 도구 중 보낸 것을 아직 안 써 봤으면 tool_search로 찾을 이유가 없음(run1 회귀: 보낸 도구를 두고 tool_search부터 부름).

    family를 적은 범주는 그것만(memory_empty는 대안인 skill_*가 아니라 memory_*가 기준), 아니면 목표 도구입니다.
    """
    return frozenset(cat["family"]) if "family" in cat else targets_of(cat)

# 짧은 질의가 서로 비슷해지기 쉬운 범주는 카드마다 다른 주제를 줍니다(근접 중복 제거로 많이 빠지는 것을 막음).
TOPICS = {
    "bash": ["installed version of one specific package", "python version and venv path", "disk usage of a directory", "free memory", "top processes by CPU or memory",
             "listening ports", "an environment variable value", "server uptime and load", "timezone/locale/date", "CPU count and model",
             "line or file counts under a directory", "syntax-check one python file", "import check of a module with python -c", "a localhost HTTP health request",
             "DNS resolution of a host", "open file limits", "size of the largest files", "python path / site-packages location", "current user and permissions of a path", "kernel and OS release"],
    "none": ["team chat message", "issue tracker ticket", "calendar event", "email", "design tool comment", "image generation", "OCR of an image", "cloud console change",
             "phone call or SMS", "payment or invoice", "spreadsheet in a cloud drive", "wiki page edit", "CI/CD pipeline button in an external system", "video meeting",
             "translation of a PDF attachment", "customer support ticket", "monitoring dashboard alert silence", "VPN/SSO account change", "app store release", "printing a document"],
    "memory": ["coding style preference", "deployment checklist", "incident postmortem notes", "API naming rules", "review conventions", "environment setup steps",
               "a decision and its reason", "a known bug workaround", "test data locations", "release schedule", "on-call rules", "performance tuning notes",
               "prompt writing guidelines", "database migration notes", "security review notes", "customer requirements summary"],
    "web": ["latest released version of a public Python package", "changelog or breaking changes of a library major version", "official docs for one function of a public library",
            "searching a specific error message", "a CVE or security advisory for a dependency", "release date or EOL of a Python version", "rate limits of a public API",
            "compare two libraries in depth (research)", "best practices for a technique, gathered from several sources (research)", "read a docs page at a URL the user pasted",
            "read a GitHub issue or release page at a URL the user pasted", "a migration guide between two framework versions (research)", "a standard or RFC detail",
            "install instructions of a CLI tool", "pricing or limits of a public cloud service tier"],
    "skill": ["release procedure", "new service setup recipe", "code review checklist", "incident response runbook", "local dev environment setup", "database backup steps",
              "API versioning workflow", "performance profiling method", "onboarding checklist", "dependency upgrade routine", "log investigation method", "prompt tuning workflow"],
    "memory_save": ["commit message language and style", "preferred test command", "code style rule", "which branch to deploy from", "a teammate's area of ownership",
                    "an API naming convention", "timezone for reports", "a known flaky module", "preferred logging format", "a decision and its reason",
                    "the staging server name", "max line length", "how to name feature flags", "the default reviewer", "a library we must not use"],
    "skill_save": ["hotfix procedure", "how to add a new tool", "release checklist", "rotating an API key", "adding a DB migration", "triaging a bug report",
                   "setting up a new venv", "profiling a slow endpoint", "writing a changelog entry", "reviewing a PR"],
    "task": ["a FastAPI/uvicorn dev server with reload", "a file watcher that re-runs a check", "a long full-project lint or compile run", "following a log file",
             "a long-running python script", "a local http.server for static files", "a periodic health check loop", "a background benchmark run"],
    "bash_dev": ["install one package with pip", "upgrade one package", "ruff check on a directory", "black --check on a file", "compileall on a package",
                 "pyflakes on a module", "pip list --outdated", "python -m a module's self-test", "python -c a quick import timing", "pip check for broken requirements"],
}

TOPICS["none_direct"] = TOPICS["none"]
TOPICS["memory_empty"] = TOPICS["memory"]

for _name, _cat in CATEGORIES.items():
    _cat["name"] = _name

PILOT2_PLAN = {"read_direct": 4, "read_loose": 4, "edit": 8, "grep": 4, "bash": 5, "memory": 6, "clarify": 5, "none": 4}
# run2: run1 에피소드(기존 8개 범주)는 새 규칙으로 다시 검증해 재사용하고, 아래만 새로 만듭니다(수락률 약 2/3을 감안한 질의 수).
# 파일럿(2차까지)에서 뺀 범주: brief(교사가 앞뒤 줄 자르기 도구 대신 직접 요약), worktree(운영은 git이 없어 실패),
# lsp(교사가 grep을 고집하고, 숨기면 tool_search로 grep을 찾음), write_new·act_not_ask(교사가 탐색을 길게 하거나 루트 전체 glob부터 함).
RUN2_NEW = ("none_direct", "web", "skill", "memory_save", "skill_save", "task", "memory_empty", "bash_dev", "clarify")
RUN2_PILOT_PLAN = {c: 3 for c in RUN2_NEW}
# 파일럿 수락률로 정한 질의 수(목표 수락 에피소드 약 127개: web 30, clarify 20, skill 15, memory_save·task·none_direct 12, skill_save·bash_dev 10, memory_empty 6).
RUN2_PLAN = {"web": 55, "skill": 33, "memory_save": 40, "skill_save": 33, "task": 33, "memory_empty": 20, "none_direct": 20, "bash_dev": 17, "clarify": 66}

# 스타일 카드 분포(운영 채팅에서 기대하는 모습: 한국어 위주, 한 문장, 짧은 반말 지시가 많고 단서 문구는 드묾).
KO_RATIO = 0.7
LENGTH_BUCKETS = {"ko": {"short": (10, 30), "medium": (30, 60), "long": (60, 110)}, "en": {"short": (20, 55), "medium": (55, 110), "long": (110, 190)}}
LENGTH_WEIGHTS = {"short": 0.45, "medium": 0.4, "long": 0.15}
KO_REGISTERS = {
    "반말 지시(…해줘/…봐줘)": 0.6,
    "해요체(…해 주세요/…할까요?)": 0.22,
    "명사형·구어 조각(…확인, …좀)": 0.12,
    "합니다체(…부탁드립니다)": 0.06,
}
EN_REGISTERS = {"casual imperative": 0.6, "polite request": 0.3, "terse fragment": 0.1}
HEDGE_RATE = 0.05

# 생성 질의 분포의 목표 범위(stats 단계). 평가 세트 원문은 쓰지 않고 dev 분할의 집계 수준 경향만 참고했습니다.
TARGET_BANDS = {
    "ko_len_median": (20, 55),
    "en_len_median": (40, 110),
    "single_sentence_share": (0.7, 1.0),
    "hedge_share": (0.0, 0.12),
    "path_share": (0.15, 0.5),
}


# ── 공통 ─────────────────────────────────────────────────────


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


def hangul_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum(1 for c in letters if "가" <= c <= "힣") / len(letters) if letters else 0.0


class BudgetExceeded(Exception):
    pass


class Ledger:
    """유료 호출의 예산 예약·정산과 공유 지출 기록(append-only JSONL)."""

    def __init__(self, model: str, budget_usd: float, spend_log: Path, stage: str) -> None:
        if model not in PRICES:
            raise SystemExit(f"가격을 모르는 모델입니다: {model} (PRICES에 추가해야 예산을 지킬 수 있음)")
        self.model = model
        self.price = PRICES[model]
        self.budget_usd = budget_usd
        self.spend_log = spend_log
        self.stage = stage
        self.spent = 0.0
        self.reserved = 0.0
        self.totals = {"calls": 0, "input": 0, "cached": 0, "output": 0, "reasoning": 0}
        self._lock = asyncio.Lock()

    def cost_of(self, usage: dict[str, int]) -> float:
        p = self.price
        return ((usage["input"] - usage["cached"]) * p["input"] + usage["cached"] * p["cached"] + usage["output"] * p["output"]) / 1e6

    def worst_case(self, est_input_tokens: int, max_output_tokens: int) -> float:
        return (est_input_tokens * self.price["input"] + max_output_tokens * self.price["output"]) / 1e6

    async def reserve(self, amount: float) -> None:
        async with self._lock:
            if self.spent + self.reserved + amount > self.budget_usd:
                raise BudgetExceeded(f"budget ${self.budget_usd:.2f}: spent ${self.spent:.4f} + reserved ${self.reserved:.4f} + next ${amount:.4f}")
            self.reserved += amount

    async def settle(self, amount: float, usage: dict[str, int] | None, ref: str) -> float:
        async with self._lock:
            self.reserved -= amount
            if usage is None:
                return 0.0
            cost = self.cost_of(usage)
            self.spent += cost
            self.totals["calls"] += 1
            for k in ("input", "cached", "output", "reasoning"):
                self.totals[k] += usage[k]
            append_jsonl(self.spend_log, {"t": round(time.time(), 1), "stage": self.stage, "ref": ref, "model": self.model, **usage, "cost_usd": round(cost, 6)})
            return cost

    def summary(self) -> dict:
        return {"model": self.model, "stage": self.stage, **self.totals, "cost_usd": round(self.spent, 4), "prices_per_mtok": self.price}

    @staticmethod
    def usage_of(resp: Any) -> dict[str, int]:
        """Chat Completions(prompt_/completion_tokens)와 Responses(input_/output_tokens) 사용량을 같은 키로."""
        u = getattr(resp, "usage", None)
        if u is None:
            return {"input": 0, "cached": 0, "output": 0, "reasoning": 0}
        if hasattr(u, "input_tokens"):
            itd, otd = getattr(u, "input_tokens_details", None), getattr(u, "output_tokens_details", None)
            return {
                "input": int(u.input_tokens or 0),
                "cached": int(getattr(itd, "cached_tokens", 0) or 0) if itd else 0,
                "output": int(u.output_tokens or 0),
                "reasoning": int(getattr(otd, "reasoning_tokens", 0) or 0) if otd else 0,
            }
        ptd, ctd = getattr(u, "prompt_tokens_details", None), getattr(u, "completion_tokens_details", None)
        return {
            "input": int(getattr(u, "prompt_tokens", 0) or 0),
            "cached": int(getattr(ptd, "cached_tokens", 0) or 0) if ptd else 0,
            "output": int(getattr(u, "completion_tokens", 0) or 0),
            "reasoning": int(getattr(ctd, "reasoning_tokens", 0) or 0) if ctd else 0,
        }


def _openai_client():
    from openai import AsyncOpenAI

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY가 없습니다")
    return AsyncOpenAI(timeout=180.0, max_retries=3)


def _est_tokens(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False)) // 3 + 200  # 보수적으로(예약용)


# ── 엔진 조립 ─────────────────────────────────────────────────


def _build_assembly(query: str, *, remote: bool, session: str):
    from src.builder.engine import EngineBuildContext, get_query_engine
    from theseus_engine.models.modes import AgentMode

    from benchmarks.llm_tool_call.harness import _remote_workspace_config

    context = EngineBuildContext(
        user_level=5,
        project_tool_permissions={},
        mode=AgentMode.AGENT,
        approval_policy="reject",
        user_query=query,
        history_messages=[],
        session_id=session,
        remote_workspace_id=1 if remote else None,
        remote_workspace=_remote_workspace_config() if remote else None,
    )
    return get_query_engine(context)


def _app_files(root: Path) -> list[str]:
    files = []
    for top in APP_DIRS:
        for p in (root / top).rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts and not any(part.startswith(".") for part in p.relative_to(root).parts):
                files.append(p.relative_to(root).as_posix())
    return sorted(files)


# ── catalog ──────────────────────────────────────────────────


def cmd_catalog(args: argparse.Namespace) -> None:
    from benchmarks.llm_tool_call import harness

    harness.pin_environment_section()
    harness.enter_fixture(Path(args.fixture_dir).resolve(), _env.SERVER_DIR)
    assembly = _build_assembly("catalog", remote=False, session="datagen:catalog")
    registry = assembly.engine.tool_metadata["tool_registry"]
    schemas = {s["name"]: s for s in registry.to_api_schema()}
    tools = [{"name": n, "description": schemas[n].get("description", ""), "input_schema": schemas[n].get("input_schema", {})} for n in assembly.allowed_tools]
    out = {"allowed_tools": list(assembly.allowed_tools), "tools": tools, "files": _app_files(Path.cwd())}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(tools)} tools, {len(out['files'])} files -> {args.out}")


# ── queries ──────────────────────────────────────────────────

_GEN_SYSTEM = """You write realistic chat messages that software developers send to "Theseus", an AI coding agent, to build
training data. Each message must be one plausible thing a busy developer types into a web chat, nothing more.

Setting (facts, do not contradict them):
- The agent runs on a Linux server. Its working directory is /app, which contains only two Python packages: src/ (a FastAPI
  web backend: routes, auth, db, remote workspace, tool planning) and theseus_engine/ (the agent engine: tools, prompts, LLM
  clients, tool retrieval, memory). There is no tests/ directory, no Dockerfile, no requirements file, and no git in /app.
- Python 3.11 in /opt/venv. Users are developers on the team, mostly Korean.

How to write:
- Follow each style card exactly: language, length range in characters, register, anchor, hedge flag, and topic if given.
- Write it the way people really type in chat: usually one sentence, often no final punctuation in Korean, English tech
  terms and identifiers mixed into Korean as developers do. A typo or missing space now and then is fine.
- Anchor: "path" = mention one real file path from the material; "identifier" = mention a real function/class/variable name
  from the material but no path; "directory" = mention only a directory; "error_text" = quote a short real message string
  from the material; "memory_name" = mention the saved note or skill by its name; "url" = include one realistic public
  https URL (official docs, a GitHub issue/release page, a PyPI page) that the request is about; "content" = the message
  itself contains the exact rule, fact, or steps to save; "pasted_text" = the message contains the long text itself
  (several lines) after a short instruction; "none" = describe the target loosely, no names.
- Hedge flag off (the default): do NOT add clauses that restrict the agent ("don't modify", "only", "just show", "no need to
  ...", "without running"), method hints, line counts, or flags unless they are the point of the request.
- Never mention the agent's tool names. Never copy sentences from the material or from the task description.
- Only reference files, names, and strings that appear in the material. Do not invent code.
"""


def _weighted(rng: random.Random, table: dict[str, float]) -> str:
    keys = list(table)
    return rng.choices(keys, weights=[table[k] for k in keys], k=1)[0]


def _style_cards(rng: random.Random, cat: dict, n: int) -> list[dict]:
    n_ko = round(n * KO_RATIO)
    langs = ["ko"] * n_ko + ["en"] * (n - n_ko)
    rng.shuffle(langs)
    cards = []
    for i, lang in enumerate(langs):
        bucket = _weighted(rng, LENGTH_WEIGHTS)
        override = cat.get("length_override")  # 내용을 질의에 담아야 하는 범주(저장할 절차, 붙여 넣은 로그)는 더 깁니다
        lo, hi = override[lang] if override else LENGTH_BUCKETS[lang][bucket]
        cards.append(
            {
                "card": i,
                "lang": lang,
                "length_chars": f"{lo}-{hi}",
                "register": _weighted(rng, KO_REGISTERS if lang == "ko" else EN_REGISTERS),
                "anchor": _weighted(rng, cat["anchors"]),
                "hedge": rng.random() < HEDGE_RATE,
            }
        )
    topics = TOPICS.get(cat.get("name", ""))
    if topics:
        for c, t in zip(cards, rng.sample(topics, min(len(topics), len(cards))) * 2):
            c["topic"] = t
    return cards


def _snippets(rng: random.Random, root: Path, files: list[str], k: int = 3, lines: int = 36) -> list[dict]:
    pool = [f for f in files if f.endswith(".py")]
    out = []
    for rel in rng.sample(pool, min(len(pool) * 3, len(pool)))[: k * 4]:
        text = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        if len(text) < 12:
            continue
        start = rng.randint(0, max(0, len(text) - lines))
        body = text[start : start + lines]
        if sum(1 for line in body if line.strip()) < 8:
            continue
        out.append({"path": rel, "start_line": start + 1, "code": "\n".join(body)})
        if len(out) >= k:
            break
    return out


def _tool_brief(tools: list[dict]) -> str:
    return "\n".join(f"- {(t['description'] or '').strip().splitlines()[0][:140]}" for t in tools if t["description"])


_REQ_SCHEMA = {
    "name": "requests",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "requests": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "card": {"type": "integer"},
                        "query": {"type": "string"},
                        "lang": {"type": "string", "enum": ["ko", "en"]},
                        "path": {"type": "string", "description": "the real /app-relative file path the request is about, or empty"},
                        "memory_notes": {
                            "type": "array",
                            "description": "memory and skill categories only: 3-5 saved notes (or skills) that exist before the request (one is the one the request is about); empty otherwise",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "scope": {"type": "string", "enum": ["user", "project", "local"]},
                                    "name": {"type": "string", "description": "kebab-case file name ending in .md"},
                                    "content": {"type": "string"},
                                    "is_target": {"type": "boolean"},
                                },
                                "required": ["scope", "name", "content", "is_target"],
                            },
                        },
                    },
                    "required": ["card", "query", "lang", "path", "memory_notes"],
                },
            }
        },
        "required": ["requests"],
    },
}


def _gen_prompt(cat_name: str, cat: dict, cards: list[dict], snippets: list[dict], tools: list[dict], files: list[str], rng: random.Random) -> str:
    parts = [f"Task category: {cat['gloss']}."]
    if cat_name in ("none", "none_direct"):
        parts.append("What the agent CAN do (so your requests must need something outside this list):\n" + _tool_brief(tools))
    extra = {
        "skill": (
            "For each request, also invent 3-5 saved skills in memory_notes (scope \"project\", kebab-case name ending in .md, "
            "content = a 2-6 line recipe). Exactly one is_target=true: the skill the request is about. If the card anchor is "
            "memory_name, the request names that skill (it may drop the .md); if none, the request describes the topic only. "
            "Other skills should be on different topics."
        ),
        "memory_empty": "Nothing has been saved yet (leave memory_notes empty), but write the request as if the user believes it was saved earlier.",
        "web": "These requests are about public, external information, not about the code in /app. Name the public library, tool, or service explicitly (e.g. FastAPI, httpx, Pydantic, uv); never say \"our framework\". If the card anchor is url, the request is to read or summarize that page.",
        "memory_save": "Each request contains the exact rule, preference, or fact to remember (one short sentence of content), plus a phrase like remember/기억해/메모해 둬.",
        "skill_save": "Each request contains the procedure itself (2-5 short steps written inline) and asks to save it as a reusable skill/recipe.",
        "task": "Each request is about starting something that keeps running; the agent should not wait for it to finish. /app is a FastAPI backend (src/) plus the agent engine (theseus_engine/).",
    }.get(cat_name)
    if extra:
        parts.append(extra)
    if cat_name == "memory":
        parts.append(
            "For each request, also invent 3-5 saved memory notes (scope, kebab-case name, 1-4 line content) that exist before "
            "the request. Exactly one is_target=true: the note the request is about. If the card anchor is memory_name, the "
            "request names that note (it may drop the .md); if none, the request describes the topic only, so the agent must "
            "list the notes to find it. Other notes should be on different topics."
        )
    if cat_name == "clarify":
        parts.append(
            "Each request must be missing something only the user can supply (a value, a choice between options, an attachment "
            "or text they forgot to include, conflicting requirements). It must be impossible to do correctly by guessing."
        )
    if snippets:
        parts.append(
            "Material (real code from /app):\n"
            + "\n\n".join(f"### {s['path']} (from line {s['start_line']})\n{s['code']}" for s in snippets)
        )
    parts.append("Other real paths in /app (for directory or path anchors):\n" + "\n".join(sorted(rng.sample(files, min(25, len(files))))))
    parts.append("Style cards (write exactly one request per card, in this order):\n" + json.dumps(cards, ensure_ascii=False, indent=1))
    if snippets:
        parts.append('Each card names its "material": base that request on that file\'s snippet, and make every request about a different thing.')
    parts.append('Set "path" to the /app-relative file the request is about when there is one (even if the request does not name it), else "".')
    return "\n\n".join(parts)


_QUOTED = re.compile(r"`([^`]{3,80})`|'([^'\s][^']{2,60})'|\"([^\"\s][^\"]{2,60})\"")
_URL = re.compile(r"https?://[^\s<>\"'`)\]가-힣]+")  # 한글 조사·백틱이 바로 붙어도 끊음


def _check_query(row: dict, files: set[str], root: Path) -> str | None:
    """생성 질의 사후 검사: 언어, 경로 존재, 인용한 코드가 실제 파일에 있는지."""
    q = row["query"]
    hangul = sum(1 for c in q if "가" <= c <= "힣")
    if row["lang"] == "ko" and hangul < 2:  # 경로·식별자가 대부분인 한국어 질의도 있으므로 한글이 있기만 하면 됨
        return "lang_mismatch"
    if row["lang"] == "en" and hangul:
        return "lang_mismatch"
    path = row.get("path") or ""
    cat = CATEGORIES[row["category"]]
    if path:
        path = path.lstrip("./")
        if path.startswith("app/"):
            path = path[4:]
        row["path"] = path
        if path not in files:
            return "path_not_in_app"
    for m in (_QUOTED.finditer(q) if cat["snippets"] else ()):  # 코드 조각 없는 범주(bash_dev·task)의 인용은 셸 명령
        frag = next(g for g in m.groups() if g)
        if "/" in frag or frag.endswith(".py") or frag.endswith(".md"):
            continue
        if path and frag not in (root / path).read_text(encoding="utf-8", errors="replace"):
            return "quoted_text_not_in_file"
    if cat.get("memory_seed") or cat.get("skill_seed"):
        notes = row.get("memory_notes") or []
        if sum(1 for n in notes if n["is_target"]) != 1 or not 2 <= len(notes) <= 6 or any(not n["content"].strip() for n in notes):
            return "bad_memory_notes"
    if row["category"] == "web" and row["card"].get("anchor") == "url" and not _URL.search(q):
        return "url_missing"
    return None


async def cmd_queries(args: argparse.Namespace) -> None:
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    root = Path(args.fixture_dir)
    files = catalog["files"]
    out_path = Path(args.out)
    done_batches = {r["batch"] for r in read_jsonl(out_path)} | {r["batch"] for r in read_jsonl(out_path.with_suffix(".rejected.jsonl"))}
    client = _openai_client()
    ledger = Ledger(args.model, args.budget_usd, Path(args.spend_log), "queries")
    named = {"pilot2": PILOT2_PLAN, "run2-pilot": RUN2_PILOT_PLAN, "run2": RUN2_PLAN}
    plan = named[args.plan] if args.plan in named else (json.loads(args.plan) if args.plan else PILOT2_PLAN)
    per_call = args.per_call
    errors = 0
    try:
        for cat_name, total in plan.items():
            cat = CATEGORIES[cat_name]
            for b in range((total + per_call - 1) // per_call):
                batch = f"s{args.seed}-{cat_name}-b{b:02d}"
                if batch in done_batches:
                    continue
                rng = random.Random(f"{args.seed}:{batch}")
                n = min(per_call, total - b * per_call)
                cards = _style_cards(rng, cat, n)
                snippets = _snippets(rng, root, files, k=n) if cat["snippets"] else []
                for c in cards:  # 카드마다 다른 코드 조각을 근거로(같은 조각에 요청이 몰리지 않게)
                    if snippets:
                        c["material"] = snippets[c["card"] % len(snippets)]["path"]
                prompt = _gen_prompt(cat_name, cat, cards, snippets, catalog["tools"], files, rng)
                reserve = ledger.worst_case(_est_tokens(_GEN_SYSTEM + prompt), args.max_output_tokens)
                await ledger.reserve(reserve)
                usage = None
                try:
                    kwargs: dict[str, Any] = {}
                    if args.reasoning_effort:
                        kwargs["reasoning"] = {"effort": args.reasoning_effort}
                    resp = await client.responses.create(
                        model=args.model,
                        input=[{"role": "system", "content": _GEN_SYSTEM}, {"role": "user", "content": prompt}],
                        text={"format": {"type": "json_schema", **_REQ_SCHEMA}},
                        max_output_tokens=args.max_output_tokens,
                        store=False,
                        **kwargs,
                    )
                    usage = Ledger.usage_of(resp)
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    print(f"[queries] {batch}: ERROR {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
                    if errors >= 3:
                        print("[queries] 3 consecutive API errors; stopping", file=sys.stderr)
                        break
                    continue
                finally:
                    cost = await ledger.settle(reserve, usage, batch)
                errors = 0
                if resp.status != "completed":
                    print(f"[queries] {batch}: status={resp.status}", file=sys.stderr)
                    continue
                data = json.loads(resp.output_text)
                cards_by_id = {c["card"]: c for c in cards}
                for item in data["requests"]:
                    card = cards_by_id.get(item["card"], {})
                    row = {
                        "id": f"{batch}-{item['card']:02d}",
                        "batch": batch,
                        "category": cat_name,
                        "query": item["query"].strip(),
                        "lang": item["lang"],
                        "path": item["path"],
                        "card": card,
                        "registry": "server",
                        "type": "none" if cat_name in ("none", "none_direct") else "single",
                        "relevant": sorted(targets_of(cat)),
                        "memory_notes": item["memory_notes"] if (cat.get("memory_seed") or cat.get("skill_seed")) else [],
                        "source_snippets": [s["path"] for s in snippets],
                    }
                    reason = _check_query(row, set(files), root)
                    if reason:
                        row["rejected"] = reason
                        append_jsonl(out_path.with_suffix(".rejected.jsonl"), row)
                    else:
                        append_jsonl(out_path, row)
                print(f"[queries] {batch}: {len(data['requests'])} rows ${cost:.4f} (total ${ledger.spent:.4f})", file=sys.stderr, flush=True)
    except BudgetExceeded as exc:
        print(f"[queries] stopped: {exc}", file=sys.stderr)
    rows = read_jsonl(out_path)
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate query ids"
    print(json.dumps({"kept": len(rows), "rejected": len(read_jsonl(out_path.with_suffix(".rejected.jsonl"))), **ledger.summary()}, ensure_ascii=False))


# ── dedup ────────────────────────────────────────────────────


def _grams(q: str, n: int = 3) -> set[str]:
    s = re.sub(r"\s+", "", q.lower())
    return {s[i : i + n] for i in range(max(1, len(s) - n + 1))}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def cmd_dedup(args: argparse.Namespace) -> None:
    import numpy as np

    from benchmarks.llm_tool_call import harness
    from benchmarks.tool_rag.harness import load_eval_set
    from theseus_engine.core.tool_rag import get_tool_retriever

    harness.warmup_tool_rag()
    retriever = get_tool_retriever()
    evals = load_eval_set("all", registry=None) + load_eval_set("holdout", registry=None)
    eval_g = [_grams(r["query"]) for r in evals]
    eval_v = np.stack([retriever.query_vector(r["query"]) for r in evals])
    kept, dropped = [], []
    kept_by_group: dict[tuple[str, str], list[tuple[Any, set[str]]]] = {}
    near = []
    for r in read_jsonl(Path(args.inp)):
        g, v = _grams(r["query"]), retriever.query_vector(r["query"])
        jac = [_jaccard(g, e) for e in eval_g]
        cos = eval_v @ v
        j_i, c_i = int(np.argmax(jac)), int(np.argmax(cos))
        r["near_eval"] = {"jaccard": round(jac[j_i], 3), "cosine": round(float(cos[c_i]), 3)}
        near.append(float(cos[c_i]))
        group = kept_by_group.setdefault((r["category"], r["lang"]), [])
        reason = None
        if jac[j_i] >= args.max_jaccard:
            reason = "near_eval_jaccard"
        elif cos[c_i] >= args.max_cosine:
            reason = "near_eval_cosine"
        elif group and max(float(kv @ v) for kv, _ in group) >= args.max_cosine_self:
            reason = "near_self_cosine"
        elif any(_jaccard(g, kg) >= args.max_jaccard for _, kg in group):
            reason = "near_self_jaccard"
        if reason:
            r["dropped"] = reason
            dropped.append(r)
        else:
            kept.append(r)
            group.append((v, g))
    write_jsonl(Path(args.out), kept)
    write_jsonl(Path(args.out).with_suffix(".dropped.jsonl"), dropped)
    pct = lambda q: round(float(np.percentile(near, q)), 3) if near else None  # noqa: E731
    print(json.dumps({"kept": len(kept), "dropped": {k: sum(1 for d in dropped if d["dropped"] == k) for k in sorted({d["dropped"] for d in dropped})}, "near_eval_cosine_p50_p90_max": [pct(50), pct(90), pct(100)]}, ensure_ascii=False))


# ── stats ────────────────────────────────────────────────────

_HEDGE = re.compile(r"하지\s*마|건드리지|수정(은|하지)\s*(말|마)|만\s*(보여|알려|확인)|없이|필요\s*없|don't|do not|without|no need|only|just", re.IGNORECASE)
_PATHLIKE = re.compile(r"[A-Za-z0-9_./-]+\.(py|md|json|toml|ya?ml|txt|sh)\b|\b(src|theseus_engine)/")
_SENT_SPLIT = re.compile(r"[.!?。]\s+|\n")


def query_stats(rows: list[dict]) -> dict:
    def med(xs):
        return statistics.median(xs) if xs else None

    ko = [len(r["query"]) for r in rows if r["lang"] == "ko"]
    en = [len(r["query"]) for r in rows if r["lang"] == "en"]
    n = len(rows) or 1
    stats = {
        "n": len(rows),
        "ko_len_median": med(ko),
        "ko_len_p90": sorted(ko)[int(0.9 * (len(ko) - 1))] if ko else None,
        "en_len_median": med(en),
        "single_sentence_share": round(sum(1 for r in rows if len([s for s in _SENT_SPLIT.split(r["query"].strip()) if s.strip()]) == 1) / n, 3),
        "hedge_share": round(sum(1 for r in rows if _HEDGE.search(r["query"])) / n, 3),
        "path_share": round(sum(1 for r in rows if _PATHLIKE.search(r["query"])) / n, 3),
        "by_category": {c: sum(1 for r in rows if r["category"] == c) for c in sorted({r["category"] for r in rows})},
    }
    stats["out_of_band"] = {k: stats[k] for k, (lo, hi) in TARGET_BANDS.items() if stats.get(k) is not None and not lo <= stats[k] <= hi}
    return stats


def cmd_stats(args: argparse.Namespace) -> None:
    print(json.dumps(query_stats(read_jsonl(Path(args.inp))), ensure_ascii=False, indent=1))


# ── episodes ─────────────────────────────────────────────────


class _StopEpisode(Exception):
    pass


def _to_responses_input(messages: list[dict]) -> list[dict]:
    """운영이 Ollama에 보내는 Chat Completions 메시지를 Responses API 입력으로(내용은 그대로)."""
    items: list[dict] = []
    for m in messages:
        role = m["role"]
        if role in ("system", "user"):
            items.append({"role": role, "content": m["content"] if isinstance(m["content"], str) else json.dumps(m["content"], ensure_ascii=False)})
        elif role == "assistant":
            if m.get("content"):
                items.append({"role": "assistant", "content": m["content"]})
            for tc in m.get("tool_calls") or []:
                items.append({"type": "function_call", "call_id": tc["id"], "name": tc["function"]["name"], "arguments": tc["function"]["arguments"]})
        elif role == "tool":
            items.append({"type": "function_call_output", "call_id": m["tool_call_id"], "output": m["content"] if isinstance(m["content"], str) else json.dumps(m["content"], ensure_ascii=False)})
    return items


def _to_responses_tools(tools: list[dict]) -> list[dict]:
    return [
        {"type": "function", "name": t["function"]["name"], "description": t["function"].get("description", ""), "parameters": t["function"].get("parameters", {}), "strict": False}
        for t in tools
    ]


class TeacherBackend:
    """TheseusLLMClient의 백엔드 자리에 들어가 교사 모델을 부르고, 평가 하네스와 같은 규칙으로 궤적을 멈춥니다.

    TheseusLLMClient.stream_message(도구 오류 표시, 라우팅, ApiMessageRequest 구성)는 운영 그대로 거칩니다.
    """

    def __init__(self, client, ledger: Ledger, *, row: dict, cat: dict, model: str, effort: str | None, max_output_tokens: int, max_turns: int) -> None:
        self.client = client
        self.ledger = ledger
        self.row = row
        self.cat = cat
        self.model = model
        self.effort = effort
        self.max_output_tokens = max_output_tokens
        self.max_turns = max_turns
        self.turns: list[dict] = []
        self.stop: str | None = None
        self.error: str | None = None
        self.budget_hit: str | None = None  # 엔진이 일반 예외를 삼키므로 예산 초과는 여기에 남김

    async def stream_message(self, request: Any):
        from benchmarks.llm_tool_call.harness import SAFE_TOOLS
        from theseus_engine.models.messages import ConversationMessage, TextBlock, ToolUseBlock
        from theseus_engine.wrappers.llm_clients.api_types import ApiMessageCompleteEvent, UsageSnapshot
        from theseus_engine.wrappers.llm_clients.openai_compat_client import _convert_messages_to_openai, _convert_tools_to_openai

        if not request.tools or request.response_format:
            self.stop = self.stop or "aux_call"
            raise _StopEpisode("auxiliary LLM call")
        if len(self.turns) >= self.max_turns:
            self.stop = "max_turns"
            raise _StopEpisode("max turns")
        messages = _convert_messages_to_openai(request.messages, request.system_prompt)
        tools = _convert_tools_to_openai(request.tools)
        hide = set(TEACHER_HIDE_ALWAYS) | set(self.cat.get("teacher_hide", ()))
        teacher_tools = [t for t in tools if t["function"]["name"] not in hide]  # 기록(request.tools)은 운영 그대로
        tool_key = hashlib.sha1(",".join(sorted(t["function"]["name"] for t in teacher_tools)).encode()).hexdigest()[:16]
        reserve = self.ledger.worst_case(_est_tokens(messages) + _est_tokens(teacher_tools), self.max_output_tokens)
        try:
            await self.ledger.reserve(reserve)
        except BudgetExceeded as exc:
            self.budget_hit = str(exc)
            self.stop = "budget"
            raise _StopEpisode("budget") from exc
        usage = None
        started = time.perf_counter()
        try:
            kwargs: dict[str, Any] = {}
            if self.effort:
                kwargs["reasoning"] = {"effort": self.effort}
            resp = await self.client.responses.create(
                model=self.model,
                input=_to_responses_input(messages),
                tools=_to_responses_tools(teacher_tools),
                max_output_tokens=self.max_output_tokens,
                store=False,
                prompt_cache_key=f"theseus-sft-{tool_key}",
                **kwargs,
            )
            usage = Ledger.usage_of(resp)
        except Exception as exc:  # noqa: BLE001
            self.error = f"{type(exc).__name__}: {str(exc)[:300]}"
            self.stop = "api_error"
            raise _StopEpisode(self.error) from exc
        finally:
            cost = await self.ledger.settle(reserve, usage, f"{self.row['id']}#t{len(self.turns)}")
        calls, texts, refusal = [], [], None
        for item in resp.output:
            if item.type == "function_call":
                calls.append({"id": item.call_id, "name": item.name, "arguments": item.arguments})
            elif item.type == "message":
                for c in item.content:
                    if getattr(c, "type", "") == "output_text":
                        texts.append(c.text)
                    elif getattr(c, "type", "") == "refusal":
                        refusal = getattr(c, "refusal", "refusal")
        turn = {
            "request": {"messages": messages, "tools": tools},
            "teacher_hidden": sorted(hide & {t["function"]["name"] for t in tools}),
            "teacher": {"content": "".join(texts) or None, "tool_calls": calls, "status": resp.status, "refusal": refusal},
            "usage": usage,
            "cost_usd": round(cost, 6),
            "latency_s": round(time.perf_counter() - started, 2),
        }
        self.turns.append(turn)
        names = [c["name"] for c in calls]
        if resp.status != "completed" or refusal:
            self.stop = f"status_{resp.status}" if resp.status != "completed" else "refusal"
            raise _StopEpisode(self.stop)
        if not names:
            self.stop = "text_answer"
            raise _StopEpisode("text")
        if targets_of(self.cat) & set(names):
            self.stop = "target_call"
            raise _StopEpisode("target")
        if any(n not in SAFE_TOOLS for n in names):
            self.stop = "other_action"
            raise _StopEpisode("other action")
        content: list[Any] = []
        if texts:
            content.append(TextBlock(text="".join(texts)))
        for c in calls:
            try:
                parsed = json.loads(c["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                parsed = {"_parse_error": str(exc), "_raw": (c["arguments"] or "")[:200]}
            content.append(ToolUseBlock(id=c["id"], name=c["name"], input=parsed if isinstance(parsed, dict) else {"_parse_error": "arguments is not an object"}))
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(role="assistant", content=content),
            usage=UsageSnapshot(input_tokens=usage["input"], output_tokens=usage["output"]),
            stop_reason="tool_calls",
        )


def _memory_dir(scope: str, app: Path) -> Path:
    if scope == "user":
        return Path(os.environ["THESEUS_DATA_DIR"]) / "memory"
    return app / (".theseus/memory" if scope == "project" else ".theseus/memory-local")


def _seed_memory(row: dict, app: Path) -> list[Path]:
    made = []
    for note in row.get("memory_notes") or []:
        d = _memory_dir(note["scope"], app)
        d.mkdir(parents=True, exist_ok=True)
        name = note["name"] if note["name"].endswith(".md") else note["name"] + ".md"
        p = d / Path(name).name
        p.write_text(note["content"].strip() + "\n", encoding="utf-8")
        made.append(p)
    return made


def _seed_skills(row: dict, app: Path) -> list[Path]:
    """skill 범주: 질의와 함께 만든 스킬을 운영 저장 형식(/app/skills/<이름>/SKILL.md, YAML 앞머리)으로 심습니다.

    /app 아래라 에피소드 뒤 _reset_dir(app)가 지웁니다.
    """
    import yaml

    made = []
    for note in row.get("memory_notes") or []:
        name = Path(note["name"]).name.removesuffix(".md")
        folder = app / "skills" / name.lower().replace(" ", "-")
        folder.mkdir(parents=True, exist_ok=True)
        body = note["content"].strip() or name
        meta = yaml.safe_dump({"name": name, "description": body.splitlines()[0][:120]}, allow_unicode=True, sort_keys=False).strip()
        p = folder / "SKILL.md"
        p.write_text(f"---\n{meta}\n---\n\n{body}\n", encoding="utf-8")
        made.append(p)
    return made


def _clear_memory(app: Path) -> None:
    for scope in ("user", "project", "local"):
        shutil.rmtree(_memory_dir(scope, app), ignore_errors=True)
    theseus_dir = app / ".theseus"
    if theseus_dir.exists() and not any(theseus_dir.iterdir()):
        theseus_dir.rmdir()


def _snapshot(d: Path) -> set[Path]:
    return set(d.rglob("*")) if d.exists() else set()


def _reset_dir(d: Path, keep: set[Path]) -> None:
    """에피소드가 만든 파일(도구 사용 로그, 큰 도구 출력 보관본, 메모리 등)을 지워 다음 에피소드가 같은 상태에서 시작하게 합니다."""
    for p in sorted(_snapshot(d) - keep, key=lambda x: len(x.parts), reverse=True):
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)


EFFORT_BY_CATEGORY = {
    "clarify": "low", "none": "low", "bash": "low", "read_loose": "low",
    "none_direct": "low", "skill_save": "low", "memory_empty": "low", "bash_dev": "low",
}  # 나머지는 교사 기본값(파일럿에서 low로는 skill·memory_save·web·task가 보낸 도구를 두고 헤맴)


async def cmd_episodes(args: argparse.Namespace) -> None:
    """질의마다 운영 엔진 + 교사 백엔드로 궤적을 만듭니다. 한 프로세스는 /app 하나를 쓰므로 순차로 돌립니다(병렬은 컨테이너를 여러 개)."""
    from benchmarks.llm_tool_call import harness

    # 운영과 같은 데이터 경로(큰 도구 출력 보관 경로가 도구 결과에 그대로 나오므로). _env의 임시 경로를 덮어씁니다.
    data_dir = Path(args.data_dir)
    os.environ["THESEUS_DATA_DIR"] = str(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    harness.pin_environment_section()
    harness.warmup_tool_rag()
    data_keep = _snapshot(data_dir)
    app = Path(args.fixture_dir).resolve()
    app_keep = _snapshot(app)
    harness.enter_fixture(app, _env.SERVER_DIR)
    rows = read_jsonl(Path(args.inp))
    if args.shard:
        k, n = map(int, args.shard.split("/"))
        rows = [r for i, r in enumerate(rows) if i % n == k]
    if args.limit:
        rows = rows[: args.limit]
    out_path = Path(args.out)
    done = {r["id"] for r in read_jsonl(out_path)}
    client = _openai_client()
    ledger = Ledger(args.model, args.budget_usd, Path(args.spend_log), "episodes")
    consecutive_errors = 0
    try:
        for r in rows:
            if r["id"] in done:
                continue
            cat = CATEGORIES[r["category"]]
            _clear_memory(app)
            if cat.get("memory_seed"):
                _seed_memory(r, app)
            if cat.get("skill_seed"):
                _seed_skills(r, app)
            assembly = _build_assembly(r["query"], remote=r["registry"] == "server_remote", session=f"datagen:{r['id']}")
            llm = assembly.engine.api_client
            if not hasattr(llm, "_backend"):
                raise SystemExit(f"unexpected api client {type(llm).__name__}")
            effort = args.reasoning_effort or EFFORT_BY_CATEGORY.get(r["category"])
            max_turns = cat.get("max_turns", args.max_turns)
            backend = TeacherBackend(client, ledger, row=r, cat=cat, model=args.model, effort=effort, max_output_tokens=args.max_output_tokens, max_turns=max_turns)
            llm._backend = backend
            llm._initialize_backend = lambda *_a, _b=backend, **_k: _b  # 라우팅이 백엔드를 다시 만들어도 교사 유지
            started = time.perf_counter()
            try:
                await asyncio.wait_for(_drain(assembly.engine, r["query"]), timeout=args.timeout)
            except asyncio.TimeoutError:
                backend.error = backend.error or f"timeout after {args.timeout}s"
            finally:
                _clear_memory(app)
                _reset_dir(data_dir, data_keep)
                _reset_dir(app, app_keep)
            if backend.budget_hit:
                print(f"[episode] stopped at {r['id']} (not recorded): {backend.budget_hit}", file=sys.stderr)
                break
            if backend.stop is None and backend.error is None:
                backend.stop = "engine_ended"
            consecutive_errors = consecutive_errors + 1 if backend.stop == "api_error" else 0
            ep = {
                "id": r["id"],
                "query_row": {k: v for k, v in r.items() if k not in ("near_eval",)},
                "sent_tools": list(assembly.sent_tools),
                "selection_mode": assembly.tool_selection_mode,
                "effort": effort,
                "stop": backend.stop,
                "error": backend.error,
                "turns": backend.turns,
                "wall_s": round(time.perf_counter() - started, 2),
            }
            append_jsonl(out_path, ep)
            path = ">".join("+".join(c["name"] for c in t["teacher"]["tool_calls"]) or "TEXT" for t in backend.turns)
            print(f"[episode] {r['id']}: {path} ({backend.stop}) ${ledger.spent:.4f}", file=sys.stderr, flush=True)
            if consecutive_errors >= 3:
                print("[episode] 3 consecutive API errors; stopping", file=sys.stderr)
                break
    finally:
        _clear_memory(app)
    print(json.dumps(ledger.summary(), ensure_ascii=False))


async def _drain(engine, query: str) -> None:
    try:
        async for _ in engine.submit_message(query):
            pass
    except _StopEpisode:
        pass


# ── validate ─────────────────────────────────────────────────

_GIT_CMD = re.compile(r"(^|[;&|]\s*|\s)git\s")


def _normalize_args(name: str, args: dict) -> dict:
    """운영 cwd(/app) 기준으로 경로 인자를 상대 경로로, 불필요한 cwd=/app은 제거합니다(교사 습관 정리)."""
    out = dict(args)
    for key in ("path", "root", "file_path", "directory"):
        v = out.get(key)
        if isinstance(v, str):
            if v.rstrip("/") == "/app":
                out[key] = "."
            elif v.startswith("/app/"):
                out[key] = v[len("/app/") :]
    if out.get("cwd") in ("/app", "/app/", "."):
        out.pop("cwd")
    return out


def _tool_results_after(turns: list[dict], i: int) -> list[str]:
    """i번째 턴 호출의 결과(i+1번째 요청에 들어간 tool 메시지)."""
    if i + 1 >= len(turns):
        return []
    return [m.get("content") or "" for m in turns[i + 1]["request"]["messages"] if m["role"] == "tool"][-len(turns[i]["teacher"]["tool_calls"]) :]


def _check_edit(call_args: dict, app: Path) -> str | None:
    path = call_args.get("path") or call_args.get("file_path")
    old, new = call_args.get("old_str"), call_args.get("new_str")
    if not isinstance(path, str) or not isinstance(old, str) or not isinstance(new, str):
        return "edit_missing_fields"
    target = (app / path).resolve() if not path.startswith("/") else Path(path)
    if not target.is_file():
        return "edit_target_missing"
    text = target.read_text(encoding="utf-8", errors="replace")
    count = text.count(old)
    if count == 0:
        return "edit_old_str_not_found"
    if count > 1 and not call_args.get("replace_all"):
        return "edit_old_str_not_unique"
    if old == new:
        return "edit_noop"
    if target.suffix == ".py":
        try:
            ast.parse(text.replace(old, new) if call_args.get("replace_all") else text.replace(old, new, 1))
        except SyntaxError:
            return "edit_breaks_syntax"
    return None


# 자리표시 인자(교사가 값을 지어낸 흔적)와 끝나지 않는 셸 명령(운영 bash는 타임아웃까지 막힘, 백그라운드는 task_create).
_PLACEHOLDER = re.compile(r"your[-_ ]?(service|app|file|package|module|project|name|host|branch|path)|<[A-Za-z][A-Za-z_-]{1,29}>|\bYOUR_[A-Z_]+|example\.com|\bfoo\b|\bxxx\b", re.IGNORECASE)
_BLOCKING = re.compile(r"\btail\s+(-\S*\s+)*-[a-zA-Z]*f|\bwatch\s|--reload\b|(?:^|[;&|(]\s*|\bpython3?\s+-m\s+)uvicorn\s+(?!--(?:help|version)\b)\S|\bflask\s+run\b|\bhttp\.server\b|\bnpm\s+run\s+(dev|start|watch)\b|\bsleep\s+\d{3,}|\bwhile\s+true\b")


def _overlap(value: str, query: str, n: int = 3) -> float:
    """질의의 문자 n-gram 중 value에도 있는 비율(재현율, 공백·대소문자 무시). 저장 인자가 사용자가 말한 내용을 담는지 봅니다.

    교사는 내용을 바꿔 쓰거나 설명을 덧붙이므로 정밀도는 낮게 나옵니다(정상 0.07~0.8). 재현율은 정상 저장이 0.3~0.8,
    run1 튜닝본처럼 질의와 무관한 내용을 쓴 경우 0.1 아래입니다.
    """
    v, q = _grams(value, n), _grams(query, n)
    return len(v & q) / len(q) if v and q else 0.0


def _check_write(call_args: dict, app: Path) -> str | None:
    path = call_args.get("path")
    content = call_args.get("content")
    if not isinstance(path, str) or not isinstance(content, str) or not content.strip():
        return "write_missing_fields"
    rel = path.lstrip("./")
    if path.startswith("/") or ".." in Path(rel).parts:
        return "write_path_outside_app"
    if call_args.get("allow_overwrite") or (app / rel).exists():
        return "write_overwrites_existing"
    if rel.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError:
            return "write_breaks_syntax"
    return None


def validate_episode(ep: dict, registry: Any, app: Path) -> tuple[bool, list[str], list[list[dict]]]:
    """궤적 하나를 검증합니다. (통과 여부, 문제 목록, 턴별 정규화된 호출)을 돌려줍니다."""
    from benchmarks.llm_tool_call.harness import _validate_args, is_clarifying_text

    row = ep["query_row"]
    cat = CATEGORIES[row["category"]]
    problems: list[str] = []
    turns = ep["turns"]
    if ep.get("error") or not turns:
        return False, [f"episode_error:{ep.get('stop')}"], []
    seen_calls: set[str] = set()
    called_before: set[str] = set()
    normalized: list[list[dict]] = []
    read_paths: set[str] = set()
    for i, t in enumerate(turns):
        teach = t["teacher"]
        offered = {x["function"]["name"] for x in t["request"]["tools"]}
        if teach["status"] != "completed" or teach.get("refusal"):
            problems.append(f"t{i}:status")
        calls = []
        for c in teach["tool_calls"]:
            try:
                parsed = json.loads(c["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                parsed = {"_parse_error": str(exc)}
            if not isinstance(parsed, dict):
                parsed = {"_parse_error": "arguments is not an object"}
            parsed = _normalize_args(c["name"], parsed) if "_parse_error" not in parsed else parsed
            ok, err = _validate_args(registry, {"name": c["name"], "input": parsed})
            if c["name"] not in offered:
                problems.append(f"t{i}:not_offered:{c['name']}")
            if not ok:
                problems.append(f"t{i}:invalid_args:{c['name']}:{err}")
            key = c["name"] + json.dumps(parsed, sort_keys=True, ensure_ascii=False)
            if key in seen_calls:
                problems.append(f"t{i}:repeated_call:{c['name']}")
            seen_calls.add(key)
            if c["name"] == "read_file" and isinstance(parsed.get("path"), str):
                read_paths.add(parsed["path"].lstrip("./"))
            calls.append({"id": c["id"], "name": c["name"], "arguments": parsed})
        normalized.append(calls)
        last = i == len(turns) - 1
        names = [c["name"] for c in calls]
        if "ask_user" in names:
            problems.append(f"t{i}:ask_user_not_in_server")  # 운영 서버에서 사용자에게 닿지 않음(#59): 되묻기는 본문으로
        if not last:
            # tool_search는 목표 도구를 보내지 않았고, 보낸 짝 도구(memory_list 등)도 이미 써 본 뒤에만 맞는 행동입니다.
            discover_ok = bool(targets_of(cat)) and not ((family_of(cat) & offered) - called_before)
            bad = [n for n in names if n not in cat["via"] and not (n == "tool_search" and discover_ok)]
            if bad:
                problems.append(f"t{i}:detour:{'+'.join(bad)}")
            if any(res.startswith("[TOOL EXECUTION ERROR]") for res in _tool_results_after(turns, i)):
                problems.append(f"t{i}:tool_error")
        called_before |= set(names)
    final = normalized[-1] if normalized else []
    final_names = [c["name"] for c in final]
    final_text = (turns[-1]["teacher"]["content"] or "").strip()
    category = row["category"]
    stop = ep["stop"]
    targets = targets_of(cat)
    kind = cat.get("final", "call" if targets else "text")
    final_is_call = stop == "target_call" and bool(final_names) and set(final_names) <= targets
    probe_names = {n for calls in normalized[:-1] for n in (c["name"] for c in calls)}
    if kind == "text":
        if stop != "text_answer" or not final_text:
            problems.append(f"final:{category}_needs_text:{stop}")
    elif kind == "clarify_text":
        if not (stop == "text_answer" and is_clarifying_text(final_text)):
            problems.append(f"final:clarify:{'+'.join(final_names) or 'TEXT'}")
    elif kind == "call_or_text":
        text_ok = stop == "text_answer" and bool(final_text)
        if not ((final_is_call or text_ok) and "memory_list" in probe_names):  # 어느 쪽이든 메모 목록부터 확인
            problems.append(f"final:{'+'.join(final_names) or 'TEXT'}:{stop}")
    elif not final_is_call:
        problems.append(f"final:{'+'.join(final_names) or 'TEXT'}:{stop}")
    if final_text and row["lang"] == "ko" and not final_names and hangul_ratio(final_text) < 0.3:
        problems.append("final:text_not_korean")
    # 질의가 경로를 직접 말했을 때만 그 파일이어야 합니다. 느슨한 질의는 교사가 실제 정의를 다른 파일에서 찾을 수 있습니다.
    target_path = (row.get("path") or "").lstrip("./")
    if target_path and target_path not in row["query"] and Path(target_path).name not in row["query"]:
        target_path = ""
    if category in ("read_direct", "read_loose") and target_path:
        for c in final:
            if c["name"] == "read_file" and (c["arguments"].get("path") or "").lstrip("./") != target_path:
                problems.append("final:read_wrong_path")
    if category == "edit" and target_path:
        for c in final:
            if c["name"] == "edit_file" and (c["arguments"].get("path") or "").lstrip("./") != target_path:
                problems.append("final:edit_wrong_path")
    if category == "memory":
        note = next((n for n in row.get("memory_notes") or [] if n["is_target"]), None)
        want = (note["name"] if note else "").removesuffix(".md")
        reads = [(str(c["arguments"].get("filename", "")).removesuffix(".md"), c["arguments"].get("scope", "local")) for c in final if c["name"] == "memory_read"]
        if reads and not any(got == want and (note is None or scope == note["scope"]) for got, scope in reads):
            problems.append("final:memory_wrong_note")  # 후보 여러 개를 함께 읽는 것은 괜찮지만 목표 메모는 들어 있어야 함
    # run2: none도 tool_search 없이 바로 못 한다고 답해도 됩니다(run1은 tool_search를 강제해 보낸 도구를 두고 검색부터 하는 습관이 생김).
    if category == "skill":
        note = next((n for n in row.get("memory_notes") or [] if n["is_target"]), None)
        want = Path(note["name"]).name.removesuffix(".md").lower() if note else ""  # _seed_skills가 앞머리에 쓴 이름(운영 레지스트리 키)
        reads = [str(c["arguments"].get("name", "")).lower() for c in final if c["name"] == "skill_read"]  # 운영처럼 정규화 없이
        if reads and want not in reads:
            problems.append("final:skill_wrong_name")
    grounded = cat.get("grounded_arg")
    if grounded and final_is_call:
        key, threshold = grounded
        for c in final:
            value = c["arguments"].get(key)
            if not isinstance(value, str) or _overlap(value, row["query"]) < threshold:
                problems.append(f"final:ungrounded_{key}")  # 질의에 없는 내용을 저장·요약(run1 튜닝본이 사실 아닌 메모를 씀)
    for c in final:
        a = c["arguments"]
        if c["name"] == "web_fetch" and str(a.get("url", "")).rstrip("/") not in {u.rstrip("/.,?!:;") for u in _URL.findall(row["query"])}:
            problems.append("final:web_fetch_url_not_in_query")
        if c["name"] in ("bash", "task_create"):
            command = str(a.get("command", ""))
            if _GIT_CMD.search(" " + command):
                problems.append("final:git_unavailable_in_prod")
            if _PLACEHOLDER.search(command):
                problems.append(f"final:{c['name']}_placeholder")
            if c["name"] == "bash" and _BLOCKING.search(command):
                problems.append("final:bash_blocking")  # 끝나지 않는 명령은 task_create로
        if c["name"] == "write_file":
            err = _check_write(a, app)
            if err:
                problems.append(f"final:{err}")
    if stop == "target_call":  # 어느 범주든 마지막 edit_file은 같은 기준
        for c in final:
            if c["name"] == "edit_file":
                p = (c["arguments"].get("path") or "").lstrip("./")
                if p not in read_paths:
                    problems.append("final:edit_without_read")
                err = _check_edit(c["arguments"], app)
                if err:
                    problems.append(f"final:{err}")
                if _deletion_only(c["arguments"]) and not _REMOVE_VERB.search(row["query"]):
                    problems.append("final:deletion_only_edit")  # 요청은 변경인데 줄만 지움(의미상 틀린 편집이 많음)
    problems.extend(_habit_problems(category, normalized, final_text, row))
    return not problems, problems, normalized


# ── 학생이 따라 배우면 안 되는 습관(1차 생성 감사에서 찾은 것) ──
_BLIND_GLOB = {"*", "**", "**/*", "./*", "./**", "./**/*"}
_REMOVE_VERB = re.compile(r"삭제|제거|지워|빼|정리|중복|remove|delete|drop|get rid|clean ?up|dedup", re.IGNORECASE)
_FIRST_SENTENCE = re.compile(r"(?<=[.?!。])\s+|\n")


def _deletion_only(args: dict) -> bool:
    old, new = args.get("old_str"), args.get("new_str")
    if not isinstance(old, str) or not isinstance(new, str):
        return False
    old_lines = {line.strip() for line in old.splitlines() if line.strip()}
    new_lines = [line.strip() for line in new.splitlines() if line.strip()]
    return len(new_lines) < len(old_lines) and all(line in old_lines for line in new_lines)


def _habit_problems(category: str, normalized: list[list[dict]], final_text: str, row: dict) -> list[str]:
    from benchmarks.llm_tool_call.harness import is_clarifying_text

    out: list[str] = []
    probes = normalized[:-1]
    for i, calls in enumerate(normalized):
        for c in calls:
            a = c["arguments"]
            if c["name"] == "glob" and str(a.get("pattern", "")).strip() in _BLIND_GLOB and str(a.get("root", ".")).strip() in (".", "", "./"):
                out.append(f"t{i}:blind_glob")  # 루트 전체 glob: 디렉터리 2개만 나오는 헛걸음
            if c["name"] == "grep" and str(a.get("query", "")).count("|") >= 3:
                out.append(f"t{i}:shotgun_grep")
    if category == "edit":
        seen_read = False
        for i, calls in enumerate(probes):
            if seen_read and any(c["name"] == "glob" for c in calls):
                out.append(f"t{i}:edit_glob_after_read")
            seen_read = seen_read or any(c["name"] == "read_file" for c in calls)
    if category == "clarify":
        if any(c["name"] == "glob" for calls in probes for c in calls) or len(probes) > 1:
            out.append("final:clarify_over_probe")  # 첨부·결정 같은 빠진 정보는 탐색으로 못 찾음: 바로 또는 한 번 읽고 묻기
    if category in ("none", "none_direct") and final_text:
        first = next((s for s in _FIRST_SENTENCE.split(final_text.strip()) if s.strip()), "")
        if "?" in first or is_clarifying_text(first):
            out.append("final:none_asks_first")  # 할 수 없다는 말보다 질문이 먼저 나옴
    if category == "read_loose" and sum(1 for c in (normalized[-1] if normalized else []) if c["name"] == "read_file") > 2:
        out.append("final:over_read")
    if category in ("bash", "bash_dev"):
        for c in normalized[-1] if normalized else []:
            if c["name"] == "bash" and len(str(c["arguments"].get("command", ""))) > 300:
                out.append("final:bash_too_long")
    return out


_DATE_RE = re.compile(r"- Date: \d{4}-\d{2}-\d{2} \(UTC\)")


def _sft_examples(ep: dict, normalized: list[list[dict]], rng: random.Random) -> list[dict]:
    """궤적의 턴마다 예제 하나: 그 턴에 운영이 보낸 messages + tools → 정답 assistant 턴.

    시스템 프롬프트의 날짜만 무작위로 바꾸고(교사에게는 고정 날짜를 보내 캐시가 맞게 함), 앞선 턴의 assistant
    호출 인자도 정규화한 값으로 바꿔 예제 안에서 일관되게 합니다.
    """
    day = f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    out = []
    for i, t in enumerate(ep["turns"]):
        msgs = json.loads(json.dumps(t["request"]["messages"]))
        if msgs and msgs[0]["role"] == "system":
            msgs[0]["content"] = _DATE_RE.sub(f"- Date: {day} (UTC)", msgs[0]["content"])
        prior = 0
        for m in msgs:
            if m["role"] == "assistant" and m.get("tool_calls"):
                for tc, norm in zip(m["tool_calls"], normalized[prior]):
                    tc["function"]["arguments"] = json.dumps(norm["arguments"], ensure_ascii=False)
                prior += 1
        assistant: dict[str, Any] = {"role": "assistant", "content": (t["teacher"]["content"] or "").strip()}
        if normalized[i]:
            assistant["tool_calls"] = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}} for c in normalized[i]]
        out.append(
            {
                "id": f"{ep['id']}#t{i}",
                "episode": ep["id"],
                "turn": i,
                "n_turns": len(ep["turns"]),
                "category": ep["query_row"]["category"],
                "lang": ep["query_row"]["lang"],
                "tools": t["request"]["tools"],
                "messages": msgs + [assistant],
            }
        )
    return out


def cmd_validate(args: argparse.Namespace) -> None:
    from benchmarks.llm_tool_call import harness

    harness.pin_environment_section()
    app = Path(args.fixture_dir).resolve()
    harness.enter_fixture(app, _env.SERVER_DIR)
    registry = _build_assembly("validate", remote=False, session="datagen:validate").engine.tool_metadata["tool_registry"]
    rng = random.Random(args.seed)
    examples, report = [], []
    for ep in read_jsonl(Path(args.inp)):
        ok, problems, normalized = validate_episode(ep, registry, app)
        row = ep["query_row"]
        report.append(
            {
                "id": ep["id"],
                "category": row["category"],
                "lang": row["lang"],
                "query": row["query"],
                "accepted": ok,
                "path": ">".join("+".join(c["name"] for c in t["teacher"]["tool_calls"]) or "TEXT" for t in ep["turns"]),
                "stop": ep["stop"],
                "problems": problems,
                "final_text": ((ep["turns"][-1]["teacher"]["content"] or "")[:200] if ep["turns"] else ""),
            }
        )
        if ok:
            examples.extend(_sft_examples(ep, normalized, rng))
    out = Path(args.out)
    write_jsonl(out, examples)
    write_jsonl(out.with_suffix(".report.jsonl"), report)
    by_cat: dict[str, list[bool]] = {}
    for v in report:
        by_cat.setdefault(v["category"], []).append(v["accepted"])
    summary = {
        "episodes": len(report),
        "accepted": sum(v["accepted"] for v in report),
        "accept_rate": round(sum(v["accepted"] for v in report) / len(report), 3) if report else None,
        "sft_examples": len(examples),
        "by_category": {c: f"{sum(a)}/{len(a)}" for c, a in sorted(by_cat.items())},
        "turns_per_accepted_episode": round(statistics.fmean([len(e["turns"]) for e in read_jsonl(Path(args.inp)) if any(v["id"] == e["id"] and v["accepted"] for v in report)]), 2) if examples else None,
        "problem_counts": {},
    }
    for v in report:
        for p in v["problems"]:
            k = re.sub(r"^t\d+:", "t*:", p).split(":")
            key = ":".join(k[:2])
            summary["problem_counts"][key] = summary["problem_counts"].get(key, 0) + 1
    out.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


# ── CLI ──────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def paid(sp, max_out: int):
        sp.add_argument("--model", default="gpt-6.1-sol")
        sp.add_argument("--budget-usd", type=float, required=True, help="이번 실행의 지출 상한(최악 비용을 예약하며 지킴)")
        sp.add_argument("--spend-log", required=True, help="모든 유료 단계가 공유하는 지출 기록 JSONL")
        sp.add_argument("--reasoning-effort", default=None)
        sp.add_argument("--max-output-tokens", type=int, default=max_out)

    sp = sub.add_parser("catalog")
    sp.add_argument("--fixture-dir", default="/app")
    sp.add_argument("--out", required=True)

    sp = sub.add_parser("queries")
    paid(sp, 6000)
    sp.add_argument("--catalog", required=True)
    sp.add_argument("--fixture-dir", default="/app")
    sp.add_argument("--plan", default=None, help='pilot2 | run2-pilot | run2 | JSON {"범주": 개수}. 없으면 PILOT2_PLAN')
    sp.add_argument("--per-call", type=int, default=8)
    sp.add_argument("--seed", type=int, default=2)
    sp.add_argument("--out", required=True)

    sp = sub.add_parser("dedup")
    sp.add_argument("--inp", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--max-jaccard", type=float, default=0.5)
    sp.add_argument("--max-cosine", type=float, default=0.92)
    sp.add_argument("--max-cosine-self", type=float, default=0.93)

    sp = sub.add_parser("stats")
    sp.add_argument("--inp", required=True)

    sp = sub.add_parser("episodes")
    paid(sp, 2048)
    sp.add_argument("--inp", required=True)
    sp.add_argument("--fixture-dir", default="/app")
    sp.add_argument("--max-turns", type=int, default=3)
    sp.add_argument("--timeout", type=float, default=240.0)
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--shard", default=None, help="k/n: 이 프로세스가 맡을 몫(컨테이너 여러 개로 병렬 실행)")
    sp.add_argument("--data-dir", default="/home/appuser/.theseus/data", help="운영 Core의 THESEUS_DATA_DIR")
    sp.add_argument("--out", required=True)

    sp = sub.add_parser("validate")
    sp.add_argument("--inp", required=True)
    sp.add_argument("--fixture-dir", default="/app")
    sp.add_argument("--seed", type=int, default=1)
    sp.add_argument("--out", required=True)

    args = p.parse_args()
    for k in ("out", "inp", "catalog", "spend_log"):
        if getattr(args, k, None):
            setattr(args, k, str(Path(getattr(args, k)).resolve()))  # fixture로 chdir하므로 먼저 절대 경로로
    os.environ.setdefault("THESEUS_MODEL", "ollama/qwen3:4b-instruct-2507-q4_K_M")  # 엔진 조립용(LLM 백엔드는 교사로 바꿈)
    os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:9/v1")
    os.environ.setdefault("THESEUS_EMBED_MODEL_DIR", str(Path.home() / ".theseus/models/e5-small-int8"))
    os.environ.setdefault("THESEUS_DEBUG_DUMP", "false")
    fn = {"catalog": cmd_catalog, "queries": cmd_queries, "dedup": cmd_dedup, "stats": cmd_stats, "episodes": cmd_episodes, "validate": cmd_validate}[args.cmd]
    result = fn(args)
    if asyncio.iscoroutine(result):
        asyncio.run(result)


if __name__ == "__main__":
    main()
