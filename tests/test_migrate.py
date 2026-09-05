"""전작(BookEater beta.4) → 이 앱 이전.

가짜 전작 DB 는 실제 BookEater 의 DDL 을 그대로 옮겨 만든다.
(src/bookeater/storage/sqlite_store.py, journal.py, settings.py 의 _init_db)
그래야 이 테스트가 통과할 때 진짜 사용자 DB 도 통과한다.
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from readingsnail.storage.db import Database                                  # noqa: E402
from readingsnail.storage.journal import Journal                              # noqa: E402
from readingsnail.storage.migrate import (                                    # noqa: E402
    MIGRATION_MARKER, MigrationError, legacy_looks_migratable, migrate)
from readingsnail.storage.settings import Settings                            # noqa: E402

LEGACY_DDL = """
CREATE TABLE monster_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    revision INTEGER NOT NULL DEFAULT 0,
    entry_count INTEGER NOT NULL DEFAULT 0,
    current_base TEXT,
    stage INTEGER NOT NULL DEFAULT 0,
    species TEXT NOT NULL DEFAULT '글씨알',
    stats_json TEXT NOT NULL DEFAULT '{}',
    form_id TEXT NOT NULL DEFAULT 'starter',
    recent_stats_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE reading_entries (
    feed_id TEXT PRIMARY KEY,
    note_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','fed')),
    public_json TEXT,
    model_version TEXT,
    nutrition_policy TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fed_at TEXT
);
CREATE TABLE books (
    book_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'reading'
        CHECK (status IN ('reading','completed','wishlist','paused')),
    isbn13 TEXT, publisher TEXT, cover_url TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_read_at TEXT
);
CREATE TABLE reading_entry_context (
    feed_id TEXT PRIMARY KEY,
    book_id TEXT,
    progress_text TEXT,
    FOREIGN KEY(feed_id) REFERENCES reading_entries(feed_id) ON DELETE CASCADE,
    FOREIGN KEY(book_id) REFERENCES books(book_id) ON DELETE SET NULL
);
CREATE TABLE app_settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO monster_state(singleton, entry_count, stage, species) VALUES (1, 3, 2, '책벌레');
"""


def make_legacy(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(LEGACY_DDL)
    con.execute(
        "INSERT INTO books(book_id,title,author,status,isbn13,publisher,cover_url,source,created_at)"
        " VALUES ('b1','월든','헨리 데이비드 소로','completed','9788932917245','은행나무',"
        "'https://example.com/cover.jpg','nl','2024-03-01 09:00:00')")
    con.execute(
        "INSERT INTO books(book_id,title,status,created_at) VALUES"
        " ('b2','읽고 싶은 책','wishlist','2024-05-02 10:00:00')")
    rows = [
        ('f1', '숲으로 간 이유를 오래 생각했다', 'fed', '2024-03-02 11:00:00'),
        ('f2', '두 번째로 남긴 감상', 'fed', '2024-03-05 12:00:00'),
        ('f3', '책과 무관하게 남긴 메모', 'pending', '2024-04-01 13:00:00'),
    ]
    for feed_id, text, status, created in rows:
        con.execute(
            'INSERT INTO reading_entries(feed_id,note_text,status,created_at) VALUES (?,?,?,?)',
            (feed_id, text, status, created))
    con.execute("INSERT INTO reading_entry_context VALUES ('f1','b1','p.31')")
    con.execute("INSERT INTO reading_entry_context VALUES ('f2','b1',NULL)")
    con.execute("INSERT INTO app_settings(key,value) VALUES ('autostart','1')")
    con.execute("INSERT INTO app_settings(key,value) VALUES ('scale','75')")
    con.commit()
    con.close()


class Migration(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.legacy = self.tmp / 'bookeater.sqlite3'
        make_legacy(self.legacy)
        self.db = Database(':memory:')
        self.journal = Journal(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_기록과_책이_넘어온다(self):
        report = migrate(self.db, self.legacy)
        self.assertEqual(report.books, 2)
        self.assertEqual(report.entries, 3)
        self.assertEqual(report.settings, 2)
        self.assertEqual(report.skipped, [])

    def test_책_기록_연결이_유지된다(self):
        migrate(self.db, self.legacy)
        timeline = self.journal.entries_for_book('b1')
        self.assertEqual([e.body for e in timeline],
                         ['숲으로 간 이유를 오래 생각했다', '두 번째로 남긴 감상'])
        self.assertEqual(timeline[0].page, 'p.31')      # progress_text → page
        self.assertEqual(timeline[0].created_at, '2024-03-02 11:00:00')

    def test_책_없는_기록도_살아남는다(self):
        migrate(self.db, self.legacy)
        loose = self.journal.get_entry('f3')
        self.assertIsNotNone(loose)
        self.assertIsNone(loose.book_id)

    def test_전부_note_로_들어온다(self):
        # 전작에는 quote/note 구분이 없었다. 임의로 quote 라 단정하지 않는다.
        migrate(self.db, self.legacy)
        self.assertEqual(self.journal.count_entries(kind='note'), 3)
        self.assertEqual(self.journal.count_entries(kind='quote'), 0)

    def test_진화_상태는_넘어오지_않는다(self):
        migrate(self.db, self.legacy)
        with self.db.connect() as con:
            names = {r['name'] for r in
                     con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn('monster_state', names)

    def test_표지_URL은_DB에_들어가지_않고_보고서로_나온다(self):
        report = migrate(self.db, self.legacy)
        self.assertEqual(report.covers_to_fetch,
                         [('b1', '월든', 'https://example.com/cover.jpg')])
        book = self.journal.get_book('b1')
        self.assertIsNone(book.cover_path)

    def test_설정이_넘어온다(self):
        migrate(self.db, self.legacy)
        settings = Settings(self.db)
        self.assertTrue(settings.get_bool('autostart'))
        self.assertEqual(settings.get_int('scale'), 75)

    def test_완독_상태가_보존된다(self):
        migrate(self.db, self.legacy)
        self.assertEqual(self.journal.get_book('b1').status, 'completed')
        self.assertEqual(self.journal.get_book('b2').status, 'wishlist')

    def test_두_번_돌려도_늘지_않는다(self):
        migrate(self.db, self.legacy)
        second = migrate(self.db, self.legacy)
        self.assertEqual(second.entries, 0)
        self.assertEqual(second.books, 0)
        self.assertEqual(second.already_present, 7)
        self.assertEqual(self.journal.count_entries(), 3)

    def test_사용자가_이미_쓴_기록을_건드리지_않는다(self):
        mine = self.journal.add_entry('새 앱에서 먼저 쓴 글')
        migrate(self.db, self.legacy)
        self.assertEqual(self.journal.get_entry(mine.entry_id).body, '새 앱에서 먼저 쓴 글')
        self.assertEqual(self.journal.count_entries(), 4)

    def test_원본은_바뀌지_않는다(self):
        before = self.legacy.read_bytes()
        migrate(self.db, self.legacy)
        self.assertEqual(self.legacy.read_bytes(), before)

    def test_이전한_기록도_한글_검색에_걸린다(self):
        from readingsnail.storage import search
        migrate(self.db, self.legacy)
        with self.db.connect() as con:
            self.assertEqual(len(search.search_entries(con, '생각')), 1)   # 2자
            self.assertEqual(len(search.search_entries(con, '이유를')), 1)  # 3자

    def test_이전_흔적이_남는다(self):
        migrate(self.db, self.legacy)
        self.assertIsNotNone(self.db.get_meta(MIGRATION_MARKER))

    def test_구버전_전작_DB도_이전된다(self):
        """beta.4 이전 버전에는 publisher / cover_url / source 컬럼이 없다.

        sqlite3.Row 는 없는 컬럼에 IndexError 를 던지는데 이건
        sqlite3.DatabaseError 가 아니라서 예전 코드는 이전 전체가 중단됐다.
        """
        older = self.tmp / 'older.sqlite3'
        con = sqlite3.connect(older)
        con.executescript(
            'CREATE TABLE reading_entries(feed_id TEXT PRIMARY KEY, note_text TEXT NOT NULL,'
            "  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"
            'CREATE TABLE books(book_id TEXT PRIMARY KEY, title TEXT NOT NULL,'
            "  author TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'reading',"
            '  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);')
        con.execute("INSERT INTO books(book_id,title) VALUES('b9','옛 책')")
        con.execute("INSERT INTO reading_entries(feed_id,note_text) VALUES('f9','옛 기록')")
        con.commit()
        con.close()

        report = migrate(self.db, older)
        self.assertEqual((report.books, report.entries), (1, 1))
        self.assertEqual(report.skipped, [])
        self.assertEqual(report.covers_to_fetch, [])
        self.assertEqual(self.journal.get_entry('f9').body, '옛 기록')

    def test_컬럼_이름이_다르면_거부한다(self):
        # BookEater 가 아닌 다른 앱의 DB 를 잘못 지목한 경우다.
        weird = self.tmp / 'weird.sqlite3'
        con = sqlite3.connect(weird)
        con.executescript('CREATE TABLE reading_entries(feed_id TEXT PRIMARY KEY, body TEXT)')
        con.execute("INSERT INTO reading_entries VALUES ('f1','다른 컬럼명')")
        con.commit()
        con.close()
        with self.assertRaises(MigrationError):
            migrate(self.db, weird)

    def test_전작_DB가_아니면_거부한다(self):
        other = self.tmp / 'other.sqlite3'
        sqlite3.connect(other).executescript('CREATE TABLE x(y)')
        self.assertFalse(legacy_looks_migratable(other))
        with self.assertRaises(MigrationError):
            migrate(self.db, other)

    def test_없는_파일(self):
        self.assertFalse(legacy_looks_migratable(self.tmp / '없음.sqlite3'))
        with self.assertRaises(MigrationError):
            migrate(self.db, self.tmp / '없음.sqlite3')

    def test_기록이_있는_전작_DB만_이전_대상이다(self):
        self.assertTrue(legacy_looks_migratable(self.legacy))
        empty = self.tmp / 'empty.sqlite3'
        con = sqlite3.connect(empty)
        con.executescript(LEGACY_DDL)
        con.commit()
        con.close()
        self.assertFalse(legacy_looks_migratable(empty))


if __name__ == '__main__':
    unittest.main(verbosity=2)
