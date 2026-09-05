"""multilingual-e5-small ONNX 인코더. **기록 저장 시점에만 돈다.**

전작 ci/e5_targeted_validation.py 의 E5 클래스에서 **인코더만** 가져왔다.
같은 파일에 있던 성향 분류(사유/탐구/감정/감각 × 상상/모험/자연/사회/어둠)는
가져오지 않는다. 그건 다시 넣지 않기로 한 기능이다(CLAUDE.md).

무겁게 다루지 않는다
    · numpy·onnxruntime·tokenizers 를 **함수 안에서** 늦게 불러온다. 모델이 없어도
      앱은 켜지고 기록은 저장된다. '저장이 분석보다 먼저다'가 여기서 지켜진다.
    · 모델을 못 열면 EncoderUnavailable 을 던진다. 부르는 쪽이 조용히 넘어간다.
    · 한 번 실패하면 기억해 두고 매번 다시 시도하지 않는다. 없는 모델을 1초마다
      찾으러 가면 그게 곧 상시 추론이다.

E5 규약
    문장 앞에 'query: ' 또는 'passage: ' 를 붙여야 한다. 안 붙이면 품질이 눈에 띄게
    떨어진다. 저장된 기록은 passage, 지금 막 쓴 기록으로 과거를 찾을 때는 query 다.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Sequence

# embed_model 컬럼에 그대로 들어간다. 모델을 바꾸면 이 값도 바꿀 것.
# 값이 다른 벡터끼리는 비교하지 않는다(services/recall.py).
MODEL_ID = 'multilingual-e5-small-onnx'
MODEL_RELATIVE = Path('resources/models/multilingual-e5-small-onnx')

MAX_TOKENS = 512
DIM = 384


class EncoderUnavailable(RuntimeError):
    """모델이나 실행기가 없다. 기록은 이미 저장돼 있으므로 조용히 넘어가면 된다."""


class E5Encoder:
    """게으르게 열리는 인코더. 스레드 하나에서만 쓰는 것을 가정한다."""

    def __init__(self, model_dir: str | Path):
        self.model_dir = Path(model_dir)
        self._lock = threading.Lock()
        self._session = None
        self._tokenizer = None
        self._input_names: set[str] = set()
        self._failure: str | None = None

    # ── 준비 ──────────────────────────────────────────
    def missing_files(self) -> list[str]:
        needed = ('model.onnx', 'tokenizer.json')
        return [n for n in needed if not (self.model_dir / n).is_file()]

    @property
    def available(self) -> bool:
        """실제로 열어보지 않고 판단한다. 부팅 화면에서 부르기 위한 것이다."""
        return self._failure is None and not self.missing_files()

    def reset_failure(self) -> None:
        """모델을 나중에 내려받았을 때 다시 시도하게 한다."""
        with self._lock:
            self._failure = None

    def _load(self) -> None:
        if self._session is not None:
            return
        if self._failure is not None:
            raise EncoderUnavailable(self._failure)

        missing = self.missing_files()
        if missing:
            self._failure = f'모델 파일이 없다: {", ".join(missing)}'
            raise EncoderUnavailable(self._failure)
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            self._failure = f'추론 라이브러리를 불러올 수 없다: {exc}'
            raise EncoderUnavailable(self._failure) from exc

        try:
            tokenizer = Tokenizer.from_file(str(self.model_dir / 'tokenizer.json'))
            tokenizer.enable_truncation(max_length=MAX_TOKENS)
            session = ort.InferenceSession(str(self.model_dir / 'model.onnx'),
                                           providers=['CPUExecutionProvider'])
        except Exception as exc:                      # onnxruntime 예외가 다양하다
            self._failure = f'모델을 열 수 없다: {exc}'
            raise EncoderUnavailable(self._failure) from exc

        self._tokenizer = tokenizer
        self._session = session
        self._input_names = {i.name for i in session.get_inputs()}

    # ── 인코딩 ────────────────────────────────────────
    def encode(self, texts: Sequence[str], *, kind: str = 'passage') -> list[list[float]]:
        """문장들을 정규화된 384차원 벡터로. 비어 있으면 빈 목록."""
        if kind not in ('passage', 'query'):
            raise ValueError("kind 는 'passage' 또는 'query'")
        cleaned = [str(t or '').strip() for t in texts]
        if not any(cleaned):
            return []

        with self._lock:
            self._load()
            import numpy as np

            prefixed = [f'{kind}: {t}' for t in cleaned]
            encs = self._tokenizer.encode_batch(prefixed)
            width = max(len(e.ids) for e in encs)
            pad = self._tokenizer.token_to_id('<pad>')
            if pad is None:
                pad = 1

            ids = np.array([e.ids + [pad] * (width - len(e.ids)) for e in encs], dtype=np.int64)
            mask = np.array([[1] * len(e.ids) + [0] * (width - len(e.ids)) for e in encs],
                            dtype=np.int64)
            feeds = {'input_ids': ids, 'attention_mask': mask}
            if 'token_type_ids' in self._input_names:
                feeds['token_type_ids'] = np.zeros_like(ids)
            feeds = {k: v for k, v in feeds.items() if k in self._input_names}

            hidden = self._session.run(None, feeds)[0]
            # 평균 풀링. 패딩 자리는 빼고 나눈다.
            m = mask[..., None].astype(np.float32)
            pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
            pooled = pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
            return [[float(v) for v in row] for row in pooled]

    def encode_one(self, text: str, *, kind: str = 'passage') -> list[float]:
        rows = self.encode([text], kind=kind)
        if not rows:
            raise EncoderUnavailable('인코딩할 문장이 없다')
        return rows[0]


def default_encoder(resource_root: str | Path) -> E5Encoder:
    return E5Encoder(Path(resource_root) / MODEL_RELATIVE)
