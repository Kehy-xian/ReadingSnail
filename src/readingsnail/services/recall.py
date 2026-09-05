"""기억 되살리기. 방금 쓴 기록과 가장 비슷한 **과거 기록**을 찾는다.

이 앱이 무작위 추출과 갈라지는 지점이다. 아무 기록이나 꺼내면 그저 랜덤이고,
방금 쓴 글과 이어지는 옛 글이 나오면 "내가 예전에 이런 생각을 했구나"가 된다.

지키는 것
    · **기록을 지어내지 않는다.** 실제로 저장된 기록만 고른다.
      (전작 services/memory.py 의 태도를 그대로 가져왔다.)
    · 유사도가 ECHO_MIN_SIMILARITY 미만이면 아무것도 돌려주지 않는다.
      억지로 이어붙이면 "이게 왜 나와?"가 되고, 그 순간 신뢰가 깨진다.
    · **같은 모델로 만든 벡터끼리만 비교한다.** 좌표계가 다르면 유사도는 숫자일 뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..nlp import vectors
from ..services.dialogue import ECHO_MIN_SIMILARITY
from ..storage.journal import Entry, Journal


@dataclass(frozen=True)
class Recalled:
    entry: Entry
    similarity: float
    book_title: str | None

    @property
    def is_same_book(self) -> bool:
        return self.book_title is not None


def similar_entry(
    journal: Journal,
    *,
    source_entry_id: str,
    model: str,
    threshold: float = ECHO_MIN_SIMILARITY,
    scan_limit: int = 5000,
) -> Recalled | None:
    """방금 저장된 기록과 가장 비슷한 과거 기록.

    UI 스레드에서 부르지 말 것. 기록 5,000건 기준 0.3초쯤 걸린다.
    """
    source = journal.get_entry(source_entry_id)
    if source is None or not source.has_embedding:
        return None

    rows = journal.embedded_entries(model=model, limit=scan_limit)
    query = None
    for entry_id, raw in rows:
        if entry_id == source_entry_id:
            try:
                query = vectors.unpack(raw)
            except vectors.VectorError:
                return None
            break
    if not query:
        return None

    hits = vectors.nearest(query, rows, threshold=threshold,
                           exclude=(source_entry_id,), top_k=1)
    if not hits:
        return None
    entry_id, score = hits[0]
    found = journal.get_entry(entry_id)
    if found is None:
        return None

    title = None
    if found.book_id:
        book = journal.get_book(found.book_id)
        title = book.title if book else None
    return Recalled(entry=found, similarity=score, book_title=title)


def similar_to_text(
    journal: Journal,
    encoder,
    text: str,
    *,
    model: str,
    threshold: float = ECHO_MIN_SIMILARITY,
    top_k: int = 5,
    scan_limit: int = 5000,
) -> list[Recalled]:
    """임의의 문장으로 과거 기록을 찾는다. 검색 화면에서 쓴다.

    이때만 인코더가 필요하다. 모델이 없으면 빈 목록을 돌려준다 —
    호출부는 storage/search.py 의 글자 검색으로 물러나면 된다.
    """
    from ..nlp.encoder import EncoderUnavailable

    if not str(text or '').strip():
        return []
    try:
        query = encoder.encode_one(text, kind='query')
    except EncoderUnavailable:
        return []

    rows = journal.embedded_entries(model=model, limit=scan_limit)
    out: list[Recalled] = []
    for entry_id, score in vectors.nearest(query, rows, threshold=threshold, top_k=top_k):
        entry = journal.get_entry(entry_id)
        if entry is None:
            continue
        title = None
        if entry.book_id:
            book = journal.get_book(entry.book_id)
            title = book.title if book else None
        out.append(Recalled(entry=entry, similarity=score, book_title=title))
    return out
