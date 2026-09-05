"""임베딩 벡터의 저장 형식과 유사도. **순수 파이썬이다.**

numpy 를 쓰지 않는 이유
    numpy 는 인코딩(onnxruntime)에만 필요하다. 유사도 계산까지 numpy 에 묶어두면
    모델이 없는 환경에서 과거 기록을 꺼내는 것조차 못 하게 된다. 저장된 벡터를
    비교하는 일은 곱셈 384번이라 순수 파이썬으로 충분하다.

저장 형식
    schema.sql 이 정한 대로 float32 리틀엔디언 raw bytes. 384차원
    (multilingual-e5-small). 빅엔디언 기계에서도 같은 바이트가 나오도록 뒤집는다.
"""

from __future__ import annotations

import math
import sys
from array import array
from typing import Iterable, Sequence

DIM = 384
_FLOAT32 = 'f'


class VectorError(ValueError):
    """벡터 바이트가 규격에 맞지 않는다."""


def pack(values: Sequence[float]) -> bytes:
    """float 목록 → float32 리틀엔디언 bytes."""
    buf = array(_FLOAT32, (float(v) for v in values))
    if array(_FLOAT32).itemsize != 4:
        raise VectorError('이 기계의 float 크기가 4바이트가 아니다')
    if sys.byteorder != 'little':
        buf.byteswap()
    return buf.tobytes()


def unpack(raw: bytes | memoryview | None) -> list[float] | None:
    """bytes → float 목록. 비어 있으면 None, 깨졌으면 VectorError."""
    if raw is None:
        return None
    data = bytes(raw)
    if not data:
        return None
    if len(data) % 4:
        raise VectorError(f'float32 배열이 아니다 ({len(data)}바이트)')
    buf = array(_FLOAT32)
    buf.frombytes(data)
    if sys.byteorder != 'little':
        buf.byteswap()
    return list(buf)


def norm(values: Sequence[float]) -> float:
    return math.sqrt(sum(v * v for v in values))


def normalize(values: Sequence[float]) -> list[float]:
    """길이 1로 만든다. 0벡터는 그대로 둔다."""
    length = norm(values)
    if length < 1e-12:
        return [float(v) for v in values]
    return [float(v) / length for v in values]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """코사인 유사도. 길이가 다르면 비교하지 않는다.

    저장된 벡터는 인코딩 때 이미 정규화돼 있지만, 모델을 바꾸거나 손으로 넣은
    벡터가 섞일 수 있으므로 여기서 한 번 더 나눈다.
    """
    if len(a) != len(b) or not a:
        return 0.0
    na, nb = norm(a), norm(b)
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def nearest(
    query: Sequence[float],
    candidates: Iterable[tuple[str, bytes]],
    *,
    threshold: float = 0.0,
    exclude: Iterable[str] = (),
    top_k: int = 1,
) -> list[tuple[str, float]]:
    """가장 가까운 후보들. (id, 유사도) 를 유사도 내림차순으로.

    깨진 벡터는 조용히 건너뛴다. 기록 하나가 이상하다고 되살리기 전체가
    멈추면 안 된다.
    """
    if not query or top_k <= 0:
        return []
    skip = set(exclude)
    scored: list[tuple[str, float]] = []
    for ref_id, raw in candidates:
        if ref_id in skip:
            continue
        try:
            other = unpack(raw)
        except VectorError:
            continue
        if not other or len(other) != len(query):
            continue
        score = cosine(query, other)
        if score >= threshold:
            scored.append((ref_id, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored[:top_k]
