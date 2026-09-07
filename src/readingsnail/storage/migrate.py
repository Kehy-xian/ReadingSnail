"""전작(BookEater beta.4) 기록 이전.

가져오는 것
    books                  → books        (표지 URL 은 제외, 아래 참조)
    reading_entries        → entries      (전부 kind='note')
    reading_entry_context  → entries.book_id / entries.page
    app_settings           → settings

버리는 것
    monster_state, monster_milestones, monster_encyclopedia, monster_care
    reading_entries 의 status / public_json / model_version / nutrition_policy
    — 진화·영양·성향 분류의 산물이다. 이 앱에는 대응하는 개념이 없다.

표지에 대하여
    전작은 books.cover_url 에 외부 URL 을 박아뒀다. 새 스키마는 cover_path(로컬 파일)만
    갖는다. 여기서 URL 을 내려받을 수는 없으므로 DB 에 넣지 않고 **보고서에 적어 돌려준다.**
    호출부가 나중에 내려받아 add_book(cover_path=...) 로 채우면 된다.
    URL 을 DB 에 그대로 옮기면 '외부 URL 을 박아두지 않는다'는 제약이 깨진다.

안전
    · 원본 DB 는 read-only(mode=ro)로만 연다. 전작 데이터는 절대 바뀌지 않는다.
    · 여러 번 돌려도 안전하다. 같은 id 는 다시 넣지 않는다.
    · 한 건이 깨져도 나머지는 들어간다. 깨진 건은 보고서의 skipped 에 남는다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from ..paths import readonly_uri
from .db import Database
from .journal import BOOK_STATUSES, TIME_FORMAT, utc_now

MIGRATION_MARKER = 'migrated_from_bookeater'

# 전작이 기록을 담고 있었다는 증거. 이게 없으면 BookEater DB 가 아니다.
REQUIRED_LEGACY_TABLES = ('reading_entries',)


@dataclass
class MigrationReport:
    source: str
    books: int = 0
    entries: int = 0
    settings: int = 0
    already_present: int = 0
    skipped: list[str] = field(default_factory=list)
    # 내려받아야 할 표지. [(book_id, title, cover_url), ...]
    covers_to_fetch: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.books + self.entries + self.settings

    def summary(self) -> str:
        parts = [f'책 {self.books}권', f'기록 {self.entries}건', f'설정 {self.settings}개']
        if self.already_present:
            parts.append(f'이미 있던 것 {self.already_present}건')
        if self.covers_to_fetch:
            parts.append(f'표지 재다운로드 대상 {len(self.covers_to_fetch)}권')
        if self.skipped:
            parts.append(f'건너뜀 {len(self.skipped)}건')
        return ', '.join(parts)


class MigrationError(RuntimeError):
    """전작 DB 를 읽을 수 없다."""


def _open_legacy(path: str | Path) -> sqlite3.Connection:
    src = Path(path).expanduser()
    if not src.is_file():
        raise MigrationError(f'전작 DB 가 없다: {src}')
    # mode=ro. 원본을 여는 것 자체로도 바꾸지 않는다.
    con = sqlite3.connect(readonly_uri(src), uri=True, timeout=5.0)
    con.row_factory = sqlite3.Row
    return con


def _tables(con: sqlite3.Connection) -> set[str]:
    return {str(r['name']) for r in
            con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _col(row: sqlite3.Row, name: str, default: object = None) -> object:
    """없는 컬럼을 조용히 넘긴다.

    전작은 beta.4 하나가 아니다. 그 전 버전 DB 에는 publisher, cover_url, source 가
    없을 수 있고 그때 sqlite3.Row 는 sqlite3.DatabaseError 가 아니라 IndexError 를
    던진다. 아래 try/except 가 잡지 못해 이전 전체가 중단됐었다.
    """
    try:
        value = row[name]
    except (IndexError, KeyError):
        return default
    return default if value is None else value


def _text(row: sqlite3.Row, name: str, default: str = '') -> str:
    return str(_col(row, name, default) or default)


def _normalize_time(raw: object) -> str:
    """전작은 CURRENT_TIMESTAMP('YYYY-MM-DD HH:MM:SS')를 썼다. 형식이 같으면 그대로 쓴다."""
    text = str(raw or '').strip()
    if not text:
        return utc_now()
    try:
        from datetime import datetime
        datetime.strptime(text[:19], TIME_FORMAT)
        return text[:19]
    except ValueError:
        # ISO 등 다른 형식이면 'T' 만 공백으로 바꿔 본다.
        candidate = text[:19].replace('T', ' ')
        try:
            from datetime import datetime
            datetime.strptime(candidate, TIME_FORMAT)
            return candidate
        except ValueError:
            return utc_now()


def legacy_looks_migratable(path: str | Path) -> bool:
    """이전할 만한 전작 DB 인지 조용히 확인한다. 첫 실행 안내에 쓴다."""
    try:
        con = _open_legacy(path)
    except (MigrationError, sqlite3.DatabaseError):
        return False
    try:
        if not set(REQUIRED_LEGACY_TABLES) <= _tables(con):
            return False
        n = con.execute('SELECT count(*) AS n FROM reading_entries').fetchone()['n']
        return int(n) > 0
    except sqlite3.DatabaseError:
        return False
    finally:
        con.close()


def migrate(db: Database, legacy_path: str | Path) -> MigrationReport:
    """전작 기록을 현재 DB 로 옮긴다. 여러 번 돌려도 결과가 같다."""
    report = MigrationReport(source=str(legacy_path))
    src = _open_legacy(legacy_path)
    try:
        try:
            tables = _tables(src)
        except sqlite3.DatabaseError as exc:
            # 파일이 SQLite 가 아니거나 손상됐다. 날 DatabaseError 를 밖으로
            # 흘리면 부팅 대화상자가 그대로 터진다.
            raise MigrationError(f'전작 DB 를 읽을 수 없다: {exc}') from exc
        if not set(REQUIRED_LEGACY_TABLES) <= tables:
            raise MigrationError('BookEater 기록 테이블(reading_entries)이 없다')

        _migrate_books(src, db, tables, report)
        _migrate_entries(src, db, tables, report)
        _migrate_settings(src, db, tables, report)
    finally:
        src.close()

    db.set_meta(MIGRATION_MARKER, f'{utc_now()} | {report.summary()}')
    return report


def _migrate_books(src, db, tables, report) -> None:
    if 'books' not in tables:
        return
    try:
        rows = src.execute('SELECT * FROM books').fetchall()
    except sqlite3.DatabaseError as exc:
        report.skipped.append(f'books 테이블을 읽을 수 없다 — {exc}')
        return

    for row in rows:
        book_id = _text(row, 'book_id').strip()
        title = _text(row, 'title').strip()
        if not book_id or not title:
            report.skipped.append(f'book:{book_id or "(id없음)"} — 제목이나 id 가 비었다')
            continue
        status = _text(row, 'status', 'reading')
        if status not in BOOK_STATUSES:
            status = 'reading'
        added = _normalize_time(_col(row, 'created_at'))

        cover_url = _text(row, 'cover_url').strip()
        if cover_url:
            # DB 에 URL 을 넣지 않는다. 나중에 내려받도록 목록만 넘긴다.
            report.covers_to_fetch.append((book_id, title, cover_url))

        finished = None
        if status == 'completed':
            finished = _normalize_time(_col(row, 'updated_at') or added)

        try:
            with db.write() as con:
                cur = con.execute(
                    'INSERT OR IGNORE INTO books'
                    '(book_id, title, author, publisher, isbn13, status, source, added_at,'
                    ' started_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (book_id, title, _text(row, 'author'),
                     _text(row, 'publisher').strip() or None,
                     _text(row, 'isbn13').strip() or None,
                     status, _text(row, 'source', 'manual'), added,
                     added if status in ('reading', 'completed', 'paused') else None,
                     finished),
                )
            if cur.rowcount:
                report.books += 1
            else:
                report.already_present += 1
        except sqlite3.DatabaseError as exc:
            report.skipped.append(f'book:{book_id} — {exc}')


def _migrate_entries(src, db, tables, report) -> None:
    has_context = 'reading_entry_context' in tables
    join = ('LEFT JOIN reading_entry_context c ON c.feed_id = e.feed_id'
            if has_context else '')
    select_ctx = 'c.book_id AS ctx_book, c.progress_text AS ctx_page' if has_context \
        else "NULL AS ctx_book, NULL AS ctx_page"
    try:
        rows = src.execute(
            f'SELECT e.feed_id, e.note_text, e.created_at, {select_ctx} '
            f'FROM reading_entries e {join} ORDER BY e.created_at, e.rowid'
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        # 컬럼 이름이 다르면 여기서 걸린다. 어느 앱의 DB 인지 알 수 없다는 뜻이다.
        raise MigrationError(f'BookEater 기록 테이블 구조가 예상과 다르다 — {exc}') from exc

    for row in rows:
        entry_id = _text(row, 'feed_id').strip()
        body = _text(row, 'note_text').strip()
        if not entry_id or not body:
            report.skipped.append(f'entry:{entry_id or "(id없음)"} — 본문이 비었다')
            continue
        book_id = _text(row, 'ctx_book').strip() or None
        page = _text(row, 'ctx_page').strip() or None
        created = _normalize_time(_col(row, 'created_at'))

        try:
            with db.write() as con:
                # 책이 안 넘어왔으면 기록만 살린다. book_id 는 NULL 로 두고 버리지 않는다.
                if book_id is not None and con.execute(
                        'SELECT 1 FROM books WHERE book_id=?', (book_id,)).fetchone() is None:
                    book_id = None
                cur = con.execute(
                    'INSERT OR IGNORE INTO entries'
                    "(entry_id, book_id, kind, body, page, created_at) VALUES (?,?,'note',?,?,?)",
                    (entry_id, book_id, body, page, created),
                )
            if cur.rowcount:
                report.entries += 1
            else:
                report.already_present += 1
        except sqlite3.DatabaseError as exc:
            report.skipped.append(f'entry:{entry_id} — {exc}')


def _migrate_settings(src, db, tables, report) -> None:
    if 'app_settings' not in tables:
        return
    try:
        rows = src.execute('SELECT key, value FROM app_settings').fetchall()
    except sqlite3.DatabaseError as exc:
        report.skipped.append(f'app_settings 를 읽을 수 없다 — {exc}')
        return
    for row in rows:
        key = _text(row, 'key').strip()
        if not key:
            continue
        try:
            with db.write() as con:
                cur = con.execute(
                    'INSERT OR IGNORE INTO settings(key, value) VALUES (?,?)',
                    (key, _text(row, 'value')),
                )
            if cur.rowcount:
                report.settings += 1
            else:
                report.already_present += 1
        except sqlite3.DatabaseError as exc:
            report.skipped.append(f'setting:{key} — {exc}')
