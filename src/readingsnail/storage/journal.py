"""책과 기록. 이 앱의 본체다.

원칙 (CLAUDE.md)
    · 책 1 : 기록 N. 기록은 시간순으로 계속 붙고, 새 기록이 옛 기록을 밀어내지 않는다.
    · 저장이 분석보다 먼저다. add_entry 는 임베딩을 받지 않는다. 인코딩이 실패해도
      기록은 이미 저장돼 있다. 벡터는 나중에 set_embedding 으로 채운다.
    · 책을 지워도 기록은 남는다(entries.book_id 는 ON DELETE SET NULL).
      제목을 정리하다가 자기가 쓴 글을 잃는 일은 없어야 한다.

시각 표기
    'YYYY-MM-DD HH:MM:SS' UTC 로 통일한다. SQLite CURRENT_TIMESTAMP 와 같은 형식이라
    전작에서 넘어온 기록과 새 기록이 한 줄로 정렬되고, date/datetime 함수도 그대로 먹는다.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .db import Database, StorageError

BOOK_STATUSES = ('reading', 'completed', 'wishlist', 'paused')
ENTRY_KINDS = ('quote', 'note')

TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

# 눈에 보이지 않는 문자들. str.strip() 은 이것들을 지우지 않아서,
# 폭 0 공백 하나만 붙여넣으면 '빈 기록'이 그대로 저장된다.
_INVISIBLE = '\u200b\u200c\u200d\u2060\ufeff\u00ad'


def is_blank(text: str) -> bool:
    """사람 눈에 아무것도 없는가."""
    return not str(text or '').strip().strip(_INVISIBLE).strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime(TIME_FORMAT)


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class Book:
    book_id: str
    title: str
    author: str
    publisher: str | None
    isbn13: str | None
    cover_path: str | None
    spine_style: int
    spine_tint: str | None
    status: str
    source: str
    added_at: str
    started_at: str | None
    finished_at: str | None

    @property
    def display_name(self) -> str:
        return f'{self.title} — {self.author}' if self.author else self.title


@dataclass(frozen=True)
class Entry:
    entry_id: str
    book_id: str | None
    kind: str
    body: str
    page: str | None
    created_at: str
    has_embedding: bool



def _must(value, what: str, key: object):
    """방금 쓴 것을 다시 읽지 못했다.

    `assert` 로 두면 두 가지가 나쁘다. `python -O` 로 돌리면 검사 자체가 사라져
    None 이 그대로 흘러나가고, 걸릴 때는 까닭 없는 `AssertionError` 만 뜬다.
    실제로 걸린다 — 앱이 도는 중에 백업으로 되돌리면 방금 쓴 줄이 통째로
    갈린 파일에 남는다. 그때 사용자에게 무슨 일인지는 말해 줘야 한다.
    """
    if value is None:
        raise StorageError(f'{what}을 저장한 뒤 다시 읽지 못했습니다 ({key}). '
                           '기록 파일이 도중에 바뀌었을 수 있습니다.')
    return value


def _book(row: sqlite3.Row) -> Book:
    return Book(
        book_id=str(row['book_id']), title=str(row['title']), author=str(row['author']),
        publisher=row['publisher'], isbn13=row['isbn13'], cover_path=row['cover_path'],
        spine_style=int(row['spine_style']), spine_tint=row['spine_tint'],
        status=str(row['status']), source=str(row['source']), added_at=str(row['added_at']),
        started_at=row['started_at'], finished_at=row['finished_at'],
    )


def _entry(row: sqlite3.Row) -> Entry:
    return Entry(
        entry_id=str(row['entry_id']), book_id=row['book_id'], kind=str(row['kind']),
        body=str(row['body']), page=row['page'], created_at=str(row['created_at']),
        has_embedding=bool(row['has_embedding']),
    )


_BOOK_COLS = ('book_id, title, author, publisher, isbn13, cover_path, spine_style, '
              'spine_tint, status, source, added_at, started_at, finished_at')
_ENTRY_COLS = ('entry_id, book_id, kind, body, page, created_at, '
               '(embedding IS NOT NULL) AS has_embedding')


def _clean(value: str | None) -> str | None:
    text = str(value or '').strip()
    return text or None


class Journal:
    """책 목록과 기록을 읽고 쓴다."""

    def __init__(self, db: Database):
        self.db = db

    # ── 책 ────────────────────────────────────────────
    def add_book(
        self, title: str, *, book_id: str | None = None, author: str = '',
        publisher: str | None = None, isbn13: str | None = None,
        cover_path: str | None = None, spine_style: int = 0, spine_tint: str | None = None,
        status: str = 'reading', source: str = 'manual', added_at: str | None = None,
    ) -> Book:
        title = str(title or '').strip()
        if not title:
            raise ValueError('제목을 비울 수 없다')
        if status not in BOOK_STATUSES:
            raise ValueError(f'알 수 없는 상태: {status}')

        book_id = str(book_id or new_id())
        now = added_at or utc_now()
        started = now if status == 'reading' else None
        with self.db.write() as con:
            con.execute(
                f'INSERT INTO books({_BOOK_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) '
                'ON CONFLICT(book_id) DO UPDATE SET '
                '  title=excluded.title, author=excluded.author,'
                '  publisher=COALESCE(excluded.publisher, books.publisher),'
                '  isbn13=COALESCE(excluded.isbn13, books.isbn13),'
                '  cover_path=COALESCE(excluded.cover_path, books.cover_path)',
                (book_id, title, str(author or '').strip(), _clean(publisher), _clean(isbn13),
                 _clean(cover_path), int(spine_style), _clean(spine_tint), status,
                 str(source or 'manual'), now, started, None),
            )
        book = self.get_book(book_id)
        if book is None:
            raise RuntimeError('책 저장에 실패했다')
        return book

    def get_book(self, book_id: str) -> Book | None:
        with self.db.connect() as con:
            row = con.execute(
                f'SELECT {_BOOK_COLS} FROM books WHERE book_id=?', (str(book_id),)).fetchone()
            return _book(row) if row else None

    def list_books(self, *, status: str | None = None, limit: int = 100) -> list[Book]:
        if limit <= 0:
            return []
        where, args = '', []
        if status is not None:
            if status not in BOOK_STATUSES:
                raise ValueError(f'알 수 없는 상태: {status}')
            where, args = 'WHERE status=?', [status]
        args.append(int(limit))
        with self.db.connect() as con:
            rows = con.execute(
                f'SELECT {_BOOK_COLS} FROM books {where} '
                'ORDER BY COALESCE(finished_at, started_at, added_at) DESC, rowid DESC LIMIT ?',
                args,
            ).fetchall()
            return [_book(r) for r in rows]

    def set_status(self, book_id: str, status: str, *, at: str | None = None) -> Book:
        """상태를 바꾼다. completed 로 갈 때만 finished_at 이 찍힌다."""
        if status not in BOOK_STATUSES:
            raise ValueError(f'알 수 없는 상태: {status}')
        now = at or utc_now()
        with self.db.write() as con:
            cur = con.execute(
                'UPDATE books SET status=?,'
                "  started_at = CASE WHEN ?='reading' AND started_at IS NULL THEN ? ELSE started_at END,"
                "  finished_at = CASE WHEN ?='completed' THEN COALESCE(finished_at, ?) ELSE NULL END "
                'WHERE book_id=?',
                (status, status, now, status, now, str(book_id)),
            )
            if cur.rowcount != 1:
                raise KeyError(book_id)
        return _must(self.get_book(book_id), '책', book_id)

    def update_book(self, book_id: str, **fields: object) -> Book:
        """제목·저자·표지 등을 고친다. 상태는 set_status 로만 바꾼다."""
        allowed = ('title', 'author', 'publisher', 'isbn13', 'cover_path',
                   'spine_style', 'spine_tint')
        sets, args = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f'고칠 수 없는 항목: {key}')
            if key == 'title' and not str(value or '').strip():
                raise ValueError('제목을 비울 수 없다')
            sets.append(f'{key}=?')
            args.append(int(value) if key == 'spine_style' else value)
        if not sets:
            book = self.get_book(book_id)
            if book is None:
                raise KeyError(book_id)
            return book
        args.append(str(book_id))
        with self.db.write() as con:
            cur = con.execute(f'UPDATE books SET {", ".join(sets)} WHERE book_id=?', args)
            if cur.rowcount != 1:
                raise KeyError(book_id)
        return _must(self.get_book(book_id), '책', book_id)

    def delete_book(self, book_id: str) -> int:
        """책 정보만 지운다. 그 책에 딸린 기록은 book_id 가 NULL 이 되어 살아남는다.

        전작의 delete_book_metadata 와 같은 태도다. 제목을 정리하다가
        자기가 쓴 글을 잃는 일은 없어야 한다. 돌려주는 값은 풀려난 기록 수.
        """
        with self.db.write() as con:
            orphaned = con.execute(
                'SELECT count(*) AS n FROM entries WHERE book_id=?', (str(book_id),)
            ).fetchone()['n']
            cur = con.execute('DELETE FROM books WHERE book_id=?', (str(book_id),))
            if cur.rowcount != 1:
                raise KeyError(book_id)
        return int(orphaned)

    # ── 기록 ──────────────────────────────────────────
    def add_entry(
        self, body: str, *, book_id: str | None = None, kind: str = 'note',
        page: str | None = None, entry_id: str | None = None, created_at: str | None = None,
    ) -> Entry:
        """기록을 남긴다. 임베딩은 받지 않는다 — 저장이 분석보다 먼저다."""
        body = str(body or '').strip()
        if is_blank(body):
            raise ValueError('빈 기록은 저장하지 않는다')
        if kind not in ENTRY_KINDS:
            raise ValueError(f'알 수 없는 기록 종류: {kind}')

        entry_id = str(entry_id or new_id())
        now = created_at or utc_now()
        book = _clean(book_id)
        with self.db.write() as con:
            if book is not None and con.execute(
                    'SELECT 1 FROM books WHERE book_id=?', (book,)).fetchone() is None:
                raise KeyError(book)
            con.execute(
                'INSERT INTO entries(entry_id, book_id, kind, body, page, created_at) '
                'VALUES (?,?,?,?,?,?)',
                (entry_id, book, kind, body, _clean(page), now),
            )
        return _must(self.get_entry(entry_id), '기록', entry_id)

    def get_entry(self, entry_id: str) -> Entry | None:
        with self.db.connect() as con:
            row = con.execute(
                f'SELECT {_ENTRY_COLS} FROM entries WHERE entry_id=?', (str(entry_id),)).fetchone()
            return _entry(row) if row else None

    def entries_for_book(self, book_id: str, *, limit: int = 500) -> list[Entry]:
        """한 책의 기록을 시간순으로. 이게 '기록 타임라인' 화면의 원본이다."""
        if limit <= 0:
            return []
        with self.db.connect() as con:
            rows = con.execute(
                f'SELECT {_ENTRY_COLS} FROM entries WHERE book_id=? '
                'ORDER BY created_at ASC, rowid ASC LIMIT ?',
                (str(book_id), int(limit)),
            ).fetchall()
            return [_entry(r) for r in rows]

    def recent_entries(self, *, kind: str | None = None, limit: int = 50) -> list[Entry]:
        if limit <= 0:
            return []
        where, args = '', []
        if kind is not None:
            if kind not in ENTRY_KINDS:
                raise ValueError(f'알 수 없는 기록 종류: {kind}')
            where, args = 'WHERE kind=?', [kind]
        args.append(int(limit))
        with self.db.connect() as con:
            rows = con.execute(
                f'SELECT {_ENTRY_COLS} FROM entries {where} '
                'ORDER BY created_at DESC, rowid DESC LIMIT ?', args).fetchall()
            return [_entry(r) for r in rows]

    def revise_entry(self, entry_id: str, body: str) -> Entry:
        """오타 정정용. 한 기록의 본문을 고친다.

        '기록을 덮어쓰지 않는다'는 원칙은 새 기록이 옛 기록을 밀어내지 않는다는 뜻이지
        자기 오타를 고칠 수 없다는 뜻은 아니다. 다만 본문이 바뀌면 기존 임베딩은
        더 이상 그 글의 벡터가 아니므로 **반드시 함께 지운다.** 안 그러면 의미 검색이
        옛 문장을 기준으로 엉뚱한 기록을 이어붙인다. (FTS 인덱스는 트리거가 알아서 따라온다.)
        """
        body = str(body or '').strip()
        if is_blank(body):
            raise ValueError('빈 기록으로 바꿀 수 없다')
        with self.db.write() as con:
            cur = con.execute(
                'UPDATE entries SET body=?, embedding=NULL, embed_model=NULL WHERE entry_id=?',
                (body, str(entry_id)),
            )
            if cur.rowcount != 1:
                raise KeyError(entry_id)
        return _must(self.get_entry(entry_id), '기록', entry_id)

    def delete_entry(self, entry_id: str) -> None:
        with self.db.write() as con:
            cur = con.execute('DELETE FROM entries WHERE entry_id=?', (str(entry_id),))
            if cur.rowcount != 1:
                raise KeyError(entry_id)

    # ── 임베딩 ────────────────────────────────────────
    def pending_embeddings(self, *, model: str | None = None,
                           limit: int = 32) -> list[tuple[str, str]]:
        """아직 인코딩되지 않은 기록. (entry_id, body) 목록.

        model 을 넘기면 **다른 모델로 만든 벡터도 대상에 넣는다.** 모델을 바꾸면
        (예: INT8 양자화) 옛 벡터는 새 벡터와 비교할 수 없기 때문이다.
        비교 불가능한 벡터를 그대로 두면 되살리기가 조용히 엉뚱해진다.

        최신 기록부터 준다. 방금 쓴 글이 가장 먼저 이어지는 게 자연스럽다.
        """
        if limit <= 0:
            return []
        if model is None:
            where, args = 'embedding IS NULL', []
        else:
            where, args = '(embedding IS NULL OR embed_model IS NOT ?)', [str(model)]
        args.append(int(limit))
        with self.db.connect() as con:
            rows = con.execute(
                f'SELECT entry_id, body FROM entries WHERE {where} '
                'ORDER BY created_at DESC, rowid DESC LIMIT ?', args).fetchall()
            return [(str(r['entry_id']), str(r['body'])) for r in rows]

    def count_pending_embeddings(self, *, model: str | None = None) -> int:
        if model is None:
            sql, args = 'SELECT count(*) AS n FROM entries WHERE embedding IS NULL', ()
        else:
            sql = ('SELECT count(*) AS n FROM entries '
                   'WHERE embedding IS NULL OR embed_model IS NOT ?')
            args = (str(model),)
        with self.db.connect() as con:
            return int(con.execute(sql, args).fetchone()['n'])

    def embedded_entries(self, *, model: str,
                         limit: int = 5000) -> list[tuple[str, bytes]]:
        """같은 모델로 만든 벡터만. (entry_id, embedding) 목록.

        모델이 다른 벡터를 섞으면 좌표계가 달라 유사도가 무의미해진다.
        """
        if limit <= 0:
            return []
        with self.db.connect() as con:
            rows = con.execute(
                'SELECT entry_id, embedding FROM entries '
                'WHERE embedding IS NOT NULL AND embed_model IS ? '
                'ORDER BY created_at DESC, rowid DESC LIMIT ?',
                (str(model), int(limit)),
            ).fetchall()
            return [(str(r['entry_id']), bytes(r['embedding'])) for r in rows]

    def set_embedding(self, entry_id: str, vector: bytes, model: str) -> None:
        """저장 시점에 한 번만 계산된 벡터를 붙인다."""
        if not isinstance(vector, (bytes, bytearray, memoryview)):
            raise TypeError('벡터는 raw bytes 여야 한다')
        with self.db.write() as con:
            cur = con.execute(
                'UPDATE entries SET embedding=?, embed_model=? WHERE entry_id=?',
                (sqlite3.Binary(bytes(vector)), str(model), str(entry_id)),
            )
            if cur.rowcount != 1:
                raise KeyError(entry_id)

    # ── 집계 ──────────────────────────────────────────
    def count_entries(self, *, kind: str | None = None) -> int:
        with self.db.connect() as con:
            if kind is None:
                row = con.execute('SELECT count(*) AS n FROM entries').fetchone()
            else:
                row = con.execute(
                    'SELECT count(*) AS n FROM entries WHERE kind=?', (str(kind),)).fetchone()
            return int(row['n'])

    def count_books(self, *, status: str | None = None) -> int:
        with self.db.connect() as con:
            if status is None:
                row = con.execute('SELECT count(*) AS n FROM books').fetchone()
            else:
                row = con.execute(
                    'SELECT count(*) AS n FROM books WHERE status=?', (str(status),)).fetchone()
            return int(row['n'])

    def entry_counts_by_book(self) -> dict[str | None, int]:
        """책마다 기록이 몇 건인지 한 번에. 책 없는 기록은 None 키로 온다.

        서재 화면이 책마다 따로 세면 N+1 질의가 된다. 지금은 빨라도 책이
        늘면 UI 스레드에서 눈에 띄기 시작한다.
        """
        with self.db.connect() as con:
            rows = con.execute(
                'SELECT book_id, count(*) AS n FROM entries GROUP BY book_id').fetchall()
            return {r['book_id']: int(r['n']) for r in rows}

    def stalled_books(self, *, days: int = 7, limit: int = 10) -> list[Book]:
        """'읽는 중'인데 한동안 기록이 없는 책. 달팽이의 STALLED 갈래가 쓴다.

        재촉이 아니라 되묻기용이다. 말투는 services/dialogue.py 가 정한다.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).strftime(TIME_FORMAT)
        with self.db.connect() as con:
            rows = con.execute(
                f'SELECT {_BOOK_COLS} FROM books b WHERE b.status=\'reading\' '
                '  AND COALESCE((SELECT max(created_at) FROM entries e WHERE e.book_id=b.book_id),'
                '               b.started_at, b.added_at) < ? '
                'ORDER BY b.added_at ASC LIMIT ?',
                (cutoff, int(limit)),
            ).fetchall()
            return [_book(r) for r in rows]
