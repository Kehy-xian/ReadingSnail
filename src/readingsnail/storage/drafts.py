"""작성 중 임시저장.

아직 저장 버튼을 누르지 않은 글만 여기 산다. 저장된 기록은 entries 로 간다.
앱이 죽어도 쓰던 글이 남아 있어야 한다.

전작에서 고친 점
    BookEater 의 reading_draft 는 singleton 한 줄이라 동시에 두 곳에 쓰던 글을
    담지 못했다. 여기서는 draft_key 로 나눠 책별 초안이 각자 남는다.
    (키 규칙은 호출부가 정한다. 예: 'book:<book_id>', 'quick')

    전작에는 monster_milestones 삭제 시 초안을 지우는 트리거가 있었다.
    그 테이블 자체가 없으므로 트리거도 없다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .db import Database
from .journal import ENTRY_KINDS, utc_now

MAX_DRAFT_CHARS = 200_000
MAX_BOOK_ID_CHARS = 200

QUICK_KEY = 'quick'


@dataclass(frozen=True)
class Draft:
    draft_key: str
    book_id: str | None
    kind: str
    body: str
    updated_at: str


class Drafts:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def key_for_book(book_id: str | None) -> str:
        return f'book:{book_id}' if book_id else QUICK_KEY

    def save(self, draft_key: str, *, body: str = '', book_id: str | None = None,
             kind: str = 'note') -> Draft | None:
        """빈 글을 저장하면 초안을 지운다. 남길 게 없기 때문이다."""
        if kind not in ENTRY_KINDS:
            raise ValueError(f'알 수 없는 기록 종류: {kind}')
        text = str(body or '')[:MAX_DRAFT_CHARS]
        if not text.strip():
            self.clear(draft_key)
            return None

        clean_book = str(book_id or '').strip()[:MAX_BOOK_ID_CHARS] or None
        with self.db.write() as con:
            con.execute(
                'INSERT INTO drafts(draft_key, book_id, kind, body, updated_at) VALUES (?,?,?,?,?) '
                'ON CONFLICT(draft_key) DO UPDATE SET book_id=excluded.book_id, '
                '  kind=excluded.kind, body=excluded.body, updated_at=excluded.updated_at',
                (str(draft_key), clean_book, kind, text, utc_now()),
            )
        return self.load(draft_key)

    def load(self, draft_key: str) -> Draft | None:
        with self.db.connect() as con:
            row = con.execute(
                'SELECT draft_key, book_id, kind, body, updated_at FROM drafts WHERE draft_key=?',
                (str(draft_key),),
            ).fetchone()
            if row is None or not str(row['body']).strip():
                return None
            return Draft(str(row['draft_key']), row['book_id'], str(row['kind']),
                         str(row['body']), str(row['updated_at']))

    def list_all(self) -> list[Draft]:
        """복구 화면용. 최근에 손댄 순."""
        with self.db.connect() as con:
            rows = con.execute(
                'SELECT draft_key, book_id, kind, body, updated_at FROM drafts '
                'ORDER BY updated_at DESC').fetchall()
            return [Draft(str(r['draft_key']), r['book_id'], str(r['kind']),
                          str(r['body']), str(r['updated_at']))
                    for r in rows if str(r['body']).strip()]

    def clear(self, draft_key: str) -> None:
        with self.db.write() as con:
            con.execute('DELETE FROM drafts WHERE draft_key=?', (str(draft_key),))
