"""임베딩을 뒤에서 채운다.

CLAUDE.md 의 두 제약이 여기서 만난다.
    · 저장이 분석보다 먼저다 — 기록은 이미 DB 에 있다. 여기서 실패해도 잃지 않는다.
    · 임베딩은 저장 시점에 한 번만 계산한다. 상시 추론 금지 —
      할 일이 없으면 이 스레드는 잠든다. 주기적으로 훑지 않는다.

동작
    UI 스레드가 wake() 로 깨우면, 밀린 기록을 한 묶음씩 인코딩하고 다시 잠든다.
    모델이 없으면 한 번 알아채고 조용히 멈춘다. 없는 모델을 계속 찾지 않는다.
"""

from __future__ import annotations

import threading
from typing import Callable

from ..nlp import vectors
from ..nlp.encoder import EncoderUnavailable
from ..storage.journal import Journal

BATCH = 8


class EmbeddingWorker:
    """기록 → 벡터. 백그라운드 스레드 하나."""

    def __init__(self, journal: Journal, encoder, *,
                 model: str | None = None,
                 on_done: Callable[[str], None] | None = None):
        self.journal = journal
        self.encoder = encoder
        self.model = model or getattr(encoder, 'MODEL_ID', None) or _default_model()
        # 한 건이 끝날 때마다 부른다. UI 스레드가 아니므로 호출부가 알아서 넘겨야 한다.
        self.on_done = on_done

        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._unavailable = False
        self.encoded = 0
        self.failed = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name='embedding',
                                        daemon=True)
        self._thread.start()
        self.wake()

    def wake(self) -> None:
        """기록이 하나 생겼다. 밀린 것이 있으면 처리한다."""
        self._wake.set()

    def stop(self, *, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    @property
    def pending(self) -> int:
        return self.journal.count_pending_embeddings(model=self.model)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait()
            if self._stop.is_set():
                return
            self._wake.clear()
            try:
                while not self._stop.is_set() and self.drain_once():
                    pass
            except Exception:
                # 배경 작업이 앱을 무너뜨리지 않는다. 기록은 이미 저장돼 있다.
                self.failed += 1

    def drain_once(self) -> bool:
        """한 묶음 처리. 더 할 일이 남았으면 True.

        테스트에서 스레드 없이 직접 부를 수 있게 떼어 뒀다.
        """
        if self._unavailable:
            return False
        batch = self.journal.pending_embeddings(model=self.model, limit=BATCH)
        if not batch:
            return False

        ids = [entry_id for entry_id, _ in batch]
        bodies = [body for _, body in batch]
        try:
            rows = self.encoder.encode(bodies, kind='passage')
        except EncoderUnavailable:
            # 모델이 없다. 다시 찾으러 가지 않는다 — 그게 곧 상시 추론이다.
            self._unavailable = True
            return False
        except Exception:
            self.failed += len(batch)
            return False

        if len(rows) != len(ids):
            self.failed += len(batch)
            return False

        for entry_id, values in zip(ids, rows):
            try:
                self.journal.set_embedding(entry_id, vectors.pack(values), self.model)
            except (KeyError, ValueError):
                # 그 사이에 지워진 기록. 넘어간다.
                continue
            self.encoded += 1
            if self.on_done is not None:
                try:
                    self.on_done(entry_id)
                except Exception:
                    pass
        return True


def _default_model() -> str:
    from ..nlp.encoder import MODEL_ID
    return MODEL_ID
