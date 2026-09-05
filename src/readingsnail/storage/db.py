"""DB 연결과 스키마 적용. 저장소 계층의 유일한 입구다.

전작에서 고친 점
    BookEater 는 SQLiteGameStore / ReadingJournalStore / ReadingDraftStore /
    AppSettingsStore 가 각자 `_connect()` 와 `_init_db()` 를 들고 있었다. 같은 코드가
    네 벌이고, DDL 이 파이썬 문자열 네 군데에 흩어져 schema.sql 같은 단일 출처가 없었다.

    여기서는 Database 하나가 연결과 스키마를 맡고, 나머지 저장소는 그것을 받아 쓴다.

연결 수명
    메서드마다 짧게 열고 닫는 방식은 전작 그대로 가져왔다. 의도적인 선택이다.
    sqlite3 연결은 스레드 사이에서 공유하면 안 되는데, 이 앱은 tkinter UI 스레드와
    임베딩 백그라운드 작업이 같은 DB 를 본다. 연결을 물고 있지 않으면 그 문제가 없다.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).parent / 'schema.sql'
SCHEMA_VERSION = '1'

# FTS5 trigram 토크나이저가 들어온 버전. 미달이면 스키마 적용 자체가 실패한다.
MIN_SQLITE = (3, 34, 0)


class StorageError(RuntimeError):
    """로컬 저장소를 안전하게 열 수 없다."""


def _sqlite_version() -> tuple[int, ...]:
    return tuple(int(p) for p in sqlite3.sqlite_version.split('.'))


class Database:
    """기록이 사는 SQLite 파일 하나를 감싼다."""

    def __init__(self, path: str | Path, *, apply_schema: bool = True):
        self.path = str(path)
        if self.path != ':memory:':
            folder = Path(self.path).expanduser().parent
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                # 경로 중간이 파일이거나 쓸 수 없는 곳이다. 여기서 분명히 알려주지
                # 않으면 FileExistsError 가 부팅 화면까지 그대로 올라간다.
                raise StorageError(f'기록을 둘 폴더를 만들 수 없다: {folder} ({exc})') from exc
            if not folder.is_dir():
                raise StorageError(f'기록을 둘 곳이 폴더가 아니다: {folder}')
        # 열려 있는 쓰기 트랜잭션의 연결을 스레드별로 들고 있는다.
        # 중첩 write() 와 write() 안의 읽기가 같은 연결을 쓰게 하기 위한 것이다.
        self._local = threading.local()
        # ':memory:' 는 연결마다 별개의 DB 가 된다. 짧은 연결 방식과 섞이면
        # 테이블이 사라진 것처럼 보이므로, 메모리 DB 는 연결 하나를 붙들고 간다.
        self._shared: sqlite3.Connection | None = None
        self._shared_lock = threading.RLock()
        if self.path == ':memory:':
            self._shared = self._new_connection()
        if apply_schema:
            self.apply_schema()

    # ── 연결 ──────────────────────────────────────────
    def _new_connection(self) -> sqlite3.Connection:
        # check_same_thread=False 는 메모리 DB 의 공유 연결 때문에 필요하다.
        # 파일 DB 는 호출한 스레드에서 열고 그 스레드에서 닫으므로 공유되지 않는다.
        con = sqlite3.connect(self.path, timeout=5.0, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA busy_timeout=5000')
        if self.path != ':memory:':
            con.execute('PRAGMA journal_mode=WAL')
        return con

    def _open_write(self) -> sqlite3.Connection | None:
        """이 스레드에서 지금 열려 있는 쓰기 트랜잭션의 연결."""
        return getattr(self._local, 'con', None)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """읽기용 짧은 연결. 커밋은 하지 않는다.

        쓰기 트랜잭션 안에서 부르면 그 연결을 그대로 돌려준다. 새 연결을 열면
        아직 커밋되지 않은 변경이 보이지 않고, 파일 DB 에서는 자기 자신의 쓰기
        잠금에 걸려 5초를 기다리다 실패한다.
        """
        con = self._open_write()
        if con is not None:
            yield con
            return
        if self._shared is not None:
            yield self._shared
            return
        con = self._new_connection()
        try:
            yield con
        finally:
            con.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """쓰기용. 빠져나갈 때 커밋하고, 예외가 나면 되돌린다.

        BEGIN IMMEDIATE 로 시작해 읽고-쓰는 사이에 다른 쓰기가 끼어들지 못하게 한다.
        전작의 record_note / commit_fed 가 쓰던 방식이다.

        **중첩해도 된다.** 안쪽 write() 는 SAVEPOINT 로 열려 바깥 트랜잭션에 합쳐진다.
        중첩을 막아두면 `with db.write(): journal.add_entry(...)` 같은 자연스러운
        호출이 'cannot start a transaction within a transaction' 으로 터진다.
        파일 DB 였다면 자기 잠금에 걸려 5초 뒤 'database is locked' 가 된다.
        """
        outer = self._open_write()
        if outer is not None:
            depth = getattr(self._local, 'depth', 0)
            name = f'rs_sp{depth}'
            self._local.depth = depth + 1
            outer.execute(f'SAVEPOINT {name}')
            try:
                yield outer
            except Exception:
                outer.execute(f'ROLLBACK TO {name}')
                outer.execute(f'RELEASE {name}')
                raise
            else:
                outer.execute(f'RELEASE {name}')
            finally:
                self._local.depth = depth
            return

        shared = self._shared is not None
        if shared:
            self._shared_lock.acquire()
        con = self._shared if shared else self._new_connection()
        self._local.con = con
        self._local.depth = 0
        try:
            con.execute('BEGIN IMMEDIATE')
            yield con
            con.commit()
        except Exception:
            if con.in_transaction:
                con.rollback()
            raise
        finally:
            self._local.con = None
            if shared:
                self._shared_lock.release()
            else:
                con.close()

    # ── 스키마 ────────────────────────────────────────
    def apply_schema(self) -> None:
        if _sqlite_version() < MIN_SQLITE:
            raise StorageError(
                f'SQLite {".".join(map(str, MIN_SQLITE))} 이상이 필요하다 '
                f'(현재 {sqlite3.sqlite_version}). FTS5 trigram 토크나이저를 쓴다.'
            )
        script = SCHEMA_PATH.read_text(encoding='utf-8')
        try:
            with self.connect() as con:
                con.executescript(script)
                con.commit()
        except sqlite3.DatabaseError as exc:
            raise StorageError('스키마를 적용할 수 없다') from exc

    def schema_version(self) -> str | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT value FROM schema_meta WHERE key='version'").fetchone()
            return str(row['value']) if row else None

    # ── 메타 ──────────────────────────────────────────
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as con:
            row = con.execute(
                'SELECT value FROM schema_meta WHERE key=?', (str(key),)).fetchone()
            return str(row['value']) if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.write() as con:
            con.execute(
                'INSERT INTO schema_meta(key, value) VALUES (?,?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                (str(key), str(value)),
            )

    def close(self) -> None:
        if self._shared is not None:
            self._shared.close()
            self._shared = None


def open_database(path: str | Path) -> Database:
    """앱이 부팅할 때 부르는 진입점. 스키마 적용 + 명언 시드까지 끝낸다."""
    from .seed import seed_quotes

    db = Database(path)
    with db.connect() as con:
        seed_quotes(con)
    return db
