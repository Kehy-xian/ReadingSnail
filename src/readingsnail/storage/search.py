"""기록 전문 검색. 반드시 이 모듈을 거쳐서 검색할 것.

왜 라우터가 필요한가
    entries_fts 는 trigram 토크나이저를 쓴다. 한글 부분 일치를 위해서다.
    그런데 trigram 은 세 글자씩 겹쳐 색인하므로 **세 글자 미만 질의를
    원리상 매칭하지 못한다.** '독서'(2자), '기록'(2자)처럼 한국어에서
    가장 흔한 검색어가 통째로 0건이 된다.

    다행히 trigram 인덱스는 LIKE '%…%' 도 가속한다(EXPLAIN QUERY PLAN 에서
    `VIRTUAL TABLE INDEX 0:L0`). 전체 스캔이 아니다.

    그래서 이렇게 나눈다.
        3자 이상  → MATCH (랭킹 있음, 빠름)
        2자 이하  → LIKE  (랭킹 없음, 최신순)

    UI 에서 sqlite 를 직접 MATCH 하면 이 분기가 빠져 2자 검색이 죽는다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# trigram 이 감당하는 최소 길이. SQLite FTS5 의 제약이지 우리 선택이 아니다.
MIN_MATCH_LEN = 3

# LIKE 패턴에서 뜻을 갖는 문자들.
_LIKE_ESCAPE = '\\'


@dataclass(frozen=True)
class Hit:
    entry_id: str
    book_id: str | None
    kind: str
    body: str
    created_at: str


def _quote_for_match(query: str) -> str:
    """FTS5 질의 문자열로 감싼다.

    trigram 은 따옴표로 감싼 구절을 부분 문자열로 취급한다. 감싸두면
    사용자가 친 `AND`, `*`, `-`, `"` 가 질의 문법으로 해석되지 않는다.
    """
    return '"' + query.replace('"', '""') + '"'


def _escape_like(query: str) -> str:
    out = query
    for ch in (_LIKE_ESCAPE, '%', '_'):
        out = out.replace(ch, _LIKE_ESCAPE + ch)
    return out


def search_entries(
    conn: sqlite3.Connection,
    query: str,
    *,
    kind: str | None = None,
    limit: int = 50,
) -> list[Hit]:
    """기록 본문을 검색한다. 질의 길이에 따라 MATCH / LIKE 로 갈린다."""
    q = query.strip()
    if not q:
        return []

    kind_clause = ' AND e.kind = ?' if kind else ''
    kind_args: tuple[str, ...] = (kind,) if kind else ()

    if len(q) >= MIN_MATCH_LEN:
        sql = f"""
            SELECT e.entry_id, e.book_id, e.kind, e.body, e.created_at
              FROM entries_fts f
              JOIN entries e ON e.rowid = f.rowid
             WHERE entries_fts MATCH ?{kind_clause}
             ORDER BY bm25(entries_fts), e.created_at DESC
             LIMIT ?
        """
        args = (_quote_for_match(q), *kind_args, limit)
    else:
        # 2자 이하. trigram MATCH 로는 절대 안 잡히므로 LIKE 로 우회한다.
        sql = f"""
            SELECT e.entry_id, e.book_id, e.kind, e.body, e.created_at
              FROM entries_fts f
              JOIN entries e ON e.rowid = f.rowid
             WHERE f.body LIKE ? ESCAPE '{_LIKE_ESCAPE}'{kind_clause}
             ORDER BY e.created_at DESC
             LIMIT ?
        """
        args = (f'%{_escape_like(q)}%', *kind_args, limit)

    return [Hit(*row) for row in conn.execute(sql, args)]


def rebuild_index(conn: sqlite3.Connection) -> None:
    """외부 콘텐츠 인덱스를 처음부터 다시 만든다.

    토크나이저를 바꾸거나 트리거 없이 entries 를 손댄 뒤에 부른다.
    """
    with conn:
        conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")


def check_index(conn: sqlite3.Connection) -> bool:
    """인덱스와 원본이 어긋났는지 본다. 어긋났으면 rebuild_index 를 부를 것."""
    try:
        conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('integrity-check')")
        return True
    except sqlite3.DatabaseError:
        return False
