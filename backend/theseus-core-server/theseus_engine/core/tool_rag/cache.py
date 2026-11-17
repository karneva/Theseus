"""텍스트 → 임베딩 벡터 캐시.

키는 sha256(embedder.fingerprint + "\\0" + 프리픽스를 포함한 텍스트)라서 모델이 바뀌면 자동으로 무효화됩니다.
커스텀 도구 하나가 추가돼 레지스트리 fingerprint가 바뀌어도, 새 인덱스를 만들 때 그 도구 텍스트만 새로 인코딩합니다.

선택적으로 디스크(npz)에 저장해 재시작 시 인덱스 구축 시간(36개 도구 기준 약 1 s)을 없앱니다.
경로는 THESEUS_TOOL_RAG_CACHE_DIR(빈 값이면 끔). 파일에는 키 해시와 float32 벡터만 들어갑니다(pickle 미사용).
파일은 임베더 fingerprint당 하나이고, 저장할 때 기존 파일의 벡터와 합칩니다(서버에서 core·Remote Workspace 세션이
번갈아 오거나 CLI에서 프로젝트를 바꿔도 마지막 레지스트리 벡터만 남지 않게). 상한은 max_disk_entries개입니다.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

log = logging.getLogger(__name__)


def text_key(fingerprint: str, text: str) -> str:
    return hashlib.sha256(f"{fingerprint}\0{text}".encode("utf-8")).hexdigest()


class EmbeddingCache:
    def __init__(
        self, cache_dir: str | os.PathLike | None = None, max_entries: int = 8192, max_disk_entries: int = 4096
    ) -> None:
        self._mem: OrderedDict[str, np.ndarray] = OrderedDict()
        self._max = max_entries
        self._max_disk = max_disk_entries
        self._fp_keys: dict[str, set[str]] = {}  # 임베더 fingerprint → 그 모델로 만든 벡터 키(디스크 저장 대상)
        self._dir = Path(cache_dir) if cache_dir else None
        self._loaded: set[str] = set()
        self._dirty: set[str] = set()
        self._lock = threading.Lock()

    # ── 디스크 ──────────────────────────────────────────────
    def _disk_path(self, fingerprint: str) -> Path | None:
        if self._dir is None:
            return None
        safe = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
        return self._dir / f"tool_rag_vectors_{safe}.npz"

    def _load_disk(self, fingerprint: str) -> None:
        if fingerprint in self._loaded:
            return
        self._loaded.add(fingerprint)
        path = self._disk_path(fingerprint)
        if path is None or not path.is_file():
            return
        try:
            with np.load(path, allow_pickle=False) as data:
                keys, vecs = data["keys"], data["vecs"]
            owned = self._fp_keys.setdefault(fingerprint, set())
            for k, v in zip(keys.tolist(), vecs):
                self._mem.setdefault(str(k), np.asarray(v, dtype=np.float32))
                owned.add(str(k))
            log.info("[ToolRAG] 디스크 벡터 캐시 %d개 로드: %s", len(keys), path)
        except Exception as exc:  # 손상된 캐시는 무시하고 다시 만듭니다.
            log.warning("[ToolRAG] 벡터 캐시를 읽지 못해 무시합니다(%s): %s", path, exc)

    def flush(self, fingerprint: str, keep_keys: Sequence[str]) -> None:
        """이 임베더의 벡터를 디스크에 원자적으로 씁니다.

        keep_keys(현재 인덱스가 쓰는 벡터)를 먼저 넣고, 같은 임베더로 만들었거나 디스크에서 읽은 다른 벡터를 최근 사용
        순으로 max_disk_entries개까지 덧붙입니다. 메모리 LRU에서 밀려난 벡터는 저장하지 않습니다.
        """
        path = self._disk_path(fingerprint)
        if path is None or fingerprint not in self._dirty:
            return
        with self._lock:
            owned = self._fp_keys.get(fingerprint, set())
            ordered = dict.fromkeys(keep_keys)
            ordered.update(dict.fromkeys(k for k in reversed(self._mem) if k in owned))
            keys = [k for k in ordered if k in self._mem][: max(1, self._max_disk)]
            if not keys:
                return
            vecs = np.stack([self._mem[k] for k in keys]).astype(np.float32)
            self._dirty.discard(fingerprint)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".npz")
            os.close(fd)
            np.savez(tmp, keys=np.asarray(keys), vecs=vecs)
            os.replace(tmp, path)
        except OSError as exc:
            log.warning("[ToolRAG] 벡터 캐시 저장 실패(무시): %s", exc)

    # ── 조회 ────────────────────────────────────────────────
    def get_or_encode(
        self, fingerprint: str, texts: Sequence[str], encode: Callable[[list[str]], np.ndarray], dim: int
    ) -> tuple[np.ndarray, list[str], int]:
        """texts의 벡터 행렬, 각 텍스트의 키, 새로 인코딩한 개수를 돌려줍니다."""
        keys = [text_key(fingerprint, t) for t in texts]
        with self._lock:
            self._load_disk(fingerprint)
            missing = [(k, t) for k, t in dict(zip(keys, texts)).items() if k not in self._mem]
        if missing:
            vecs = encode([t for _, t in missing])
            with self._lock:
                owned = self._fp_keys.setdefault(fingerprint, set())
                for (k, _), v in zip(missing, vecs):
                    self._mem[k] = np.asarray(v, dtype=np.float32)
                    owned.add(k)
                self._dirty.add(fingerprint)
        with self._lock:
            if not keys:
                return np.zeros((0, dim), dtype=np.float32), keys, len(missing)
            for k in keys:
                self._mem.move_to_end(k)
            mat = np.stack([self._mem[k] for k in keys]).astype(np.float32)
            while len(self._mem) > self._max:
                old, _ = self._mem.popitem(last=False)
                for owned in self._fp_keys.values():
                    owned.discard(old)
        return mat, keys, len(missing)

    def __len__(self) -> int:
        return len(self._mem)

    def clear(self) -> None:
        with self._lock:
            self._mem.clear()
            self._fp_keys.clear()
            self._loaded.clear()
            self._dirty.clear()
