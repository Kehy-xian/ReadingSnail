"""저장소 계층. 책 1:N 기록, 임시저장, 설정.

여기서 지키려는 것은 CLAUDE.md 의 제약이다.
  · 기록은 덮어쓰지 않는다
  · 저장이 분석보다 먼저다
  · 책을 지워도 기록은 남는다
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from readingsnail.storage.db import Database, StorageError, open_database  # noqa: E402
from readingsnail.storage.drafts import Drafts                            # noqa: E402
from readingsnail.storage.journal import Journal                          # noqa: E402
from readingsnail.storage.settings import Settings                        # noqa: E402


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database(':memory:')
        self.journal = Journal(self.db)

    def tearDown(self) -> None:
        self.db.close()


class BookAndEntries(Base):
    def test_책_1_대_기록_N(self):
        book = self.journal.add_book('월든', author='헨리 데이비드 소로')
        for text in ('첫 문장', '둘째 문장', '셋째 문장'):
            self.journal.add_entry(text, book_id=book.book_id)
        timeline = self.journal.entries_for_book(book.book_id)
        self.assertEqual([e.body for e in timeline], ['첫 문장', '둘째 문장', '셋째 문장'])

    def test_새_기록이_옛_기록을_밀어내지_않는다(self):
        book = self.journal.add_book('월든')
        first = self.journal.add_entry('처음 남긴 말', book_id=book.book_id)
        self.journal.add_entry('나중에 남긴 말', book_id=book.book_id)
        self.assertIsNotNone(self.journal.get_entry(first.entry_id))
        self.assertEqual(self.journal.count_entries(), 2)

    def test_책을_지워도_기록은_남는다(self):
        book = self.journal.add_book('사라질 책')
        entry = self.journal.add_entry('살아남아야 할 문장', book_id=book.book_id)
        freed = self.journal.delete_book(book.book_id)
        self.assertEqual(freed, 1)
        survivor = self.journal.get_entry(entry.entry_id)
        self.assertIsNotNone(survivor)
        self.assertEqual(survivor.body, '살아남아야 할 문장')
        self.assertIsNone(survivor.book_id)

    def test_기록_종류가_나뉜다(self):
        book = self.journal.add_book('책')
        self.journal.add_entry('필사한 문장', book_id=book.book_id, kind='quote', page='p.42')
        self.journal.add_entry('내 생각', book_id=book.book_id, kind='note')
        self.assertEqual(self.journal.count_entries(kind='quote'), 1)
        self.assertEqual(self.journal.count_entries(kind='note'), 1)

    def test_없는_책에_기록을_붙일_수_없다(self):
        with self.assertRaises(KeyError):
            self.journal.add_entry('본문', book_id='없는책')

    def test_빈_기록은_저장하지_않는다(self):
        for bad in ('', '   ', '\n'):
            with self.assertRaises(ValueError):
                self.journal.add_entry(bad)

    def test_완독_표시가_finished_at을_남긴다(self):
        book = self.journal.add_book('다 읽을 책')
        self.assertIsNone(book.finished_at)
        done = self.journal.set_status(book.book_id, 'completed')
        self.assertIsNotNone(done.finished_at)
        # 다시 읽는 중으로 되돌리면 완독 시각은 지워진다
        back = self.journal.set_status(book.book_id, 'reading')
        self.assertIsNone(back.finished_at)

    def test_상태별_목록(self):
        self.journal.add_book('읽는 중')
        self.journal.add_book('위시', status='wishlist')
        self.assertEqual(len(self.journal.list_books(status='wishlist')), 1)
        self.assertEqual(self.journal.count_books(), 2)

    def test_정체된_책만_골라낸다(self):
        old = self.journal.add_book('오래 방치된 책', added_at='2020-01-01 00:00:00')
        self.journal.add_book('오늘 등록한 책')
        stalled = self.journal.stalled_books(days=7)
        self.assertEqual([b.book_id for b in stalled], [old.book_id])

    def test_최근_기록이_있으면_정체가_아니다(self):
        book = self.journal.add_book('읽는 중', added_at='2020-01-01 00:00:00')
        self.journal.add_entry('오늘 읽었다', book_id=book.book_id)
        self.assertEqual(self.journal.stalled_books(days=7), [])


class Embedding(Base):
    def test_저장이_분석보다_먼저다(self):
        entry = self.journal.add_entry('벡터 없이 먼저 저장된다')
        self.assertFalse(entry.has_embedding)
        self.assertEqual(self.journal.pending_embeddings(), [(entry.entry_id, entry.body)])

    def test_나중에_벡터를_붙인다(self):
        entry = self.journal.add_entry('본문')
        self.journal.set_embedding(entry.entry_id, b'\x00' * 1536, 'e5-small-int8')
        self.assertTrue(self.journal.get_entry(entry.entry_id).has_embedding)
        self.assertEqual(self.journal.pending_embeddings(), [])

    def test_본문을_고치면_벡터가_무효화된다(self):
        # 안 그러면 의미 검색이 옛 문장 기준으로 엉뚱한 기록을 이어붙인다.
        entry = self.journal.add_entry('원래 문장')
        self.journal.set_embedding(entry.entry_id, b'\x01' * 8, 'm')
        revised = self.journal.revise_entry(entry.entry_id, '고친 문장')
        self.assertEqual(revised.body, '고친 문장')
        self.assertFalse(revised.has_embedding)
        self.assertEqual(len(self.journal.pending_embeddings()), 1)

    def test_본문을_고치면_검색_인덱스도_따라온다(self):
        from readingsnail.storage import search
        entry = self.journal.add_entry('원래 달팽이 문장')
        with self.db.connect() as con:
            self.assertEqual(len(search.search_entries(con, '달팽이')), 1)
            self.journal.revise_entry(entry.entry_id, '고친 거북이 문장')
            self.assertEqual(len(search.search_entries(con, '달팽이')), 0)
            self.assertEqual(len(search.search_entries(con, '거북이')), 1)


class DraftStore(Base):
    def setUp(self) -> None:
        super().setUp()
        self.drafts = Drafts(self.db)

    def test_책별로_초안이_따로_남는다(self):
        # 전작은 singleton 한 줄이라 이게 안 됐다.
        a, b = self.drafts.key_for_book('책A'), self.drafts.key_for_book('책B')
        self.drafts.save(a, body='A에 쓰던 글', book_id='책A')
        self.drafts.save(b, body='B에 쓰던 글', book_id='책B')
        self.assertEqual(self.drafts.load(a).body, 'A에 쓰던 글')
        self.assertEqual(self.drafts.load(b).body, 'B에 쓰던 글')
        self.assertEqual(len(self.drafts.list_all()), 2)

    def test_빈_초안은_지워진다(self):
        key = self.drafts.key_for_book(None)
        self.drafts.save(key, body='쓰다 만 글')
        self.assertIsNotNone(self.drafts.load(key))
        self.assertIsNone(self.drafts.save(key, body='   '))
        self.assertIsNone(self.drafts.load(key))

    def test_길이_상한(self):
        from readingsnail.storage.drafts import MAX_DRAFT_CHARS
        key = 'quick'
        self.drafts.save(key, body='가' * (MAX_DRAFT_CHARS + 500))
        self.assertEqual(len(self.drafts.load(key).body), MAX_DRAFT_CHARS)


class SettingStore(Base):
    def setUp(self) -> None:
        super().setUp()
        self.settings = Settings(self.db)

    def test_읽고_쓰기(self):
        self.settings.set('scale', '75')
        self.assertEqual(self.settings.get('scale'), '75')
        self.assertEqual(self.settings.get_int('scale'), 75)
        self.assertEqual(self.settings.get('없는키', '기본값'), '기본값')

    def test_불리언(self):
        self.settings.set_bool('autostart', True)
        self.assertTrue(self.settings.get_bool('autostart'))
        self.assertFalse(self.settings.get_bool('없는키'))
        self.assertEqual(self.settings.get_int('autostart'), 1)

    def test_깨진_숫자는_기본값으로(self):
        self.settings.set('scale', '숫자아님')
        self.assertEqual(self.settings.get_int('scale', 100), 100)

    def test_초기화해도_기록은_남는다(self):
        self.journal.add_entry('내 기록')
        self.settings.set('scale', '50')
        self.settings.clear()
        self.assertEqual(self.settings.all(), {})
        self.assertEqual(self.journal.count_entries(), 1)


class NestedWrites(Base):
    """write() 중첩. 막아두면 2단계 UI 코드가 바로 걸린다."""

    def test_쓰기_안에서_저장소_메서드를_불러도_된다(self):
        with self.db.write():
            self.journal.add_entry('중첩 안에서 저장')
        self.assertEqual(self.journal.count_entries(), 1)

    def test_쓰기_안의_읽기는_아직_커밋_안_된_것도_본다(self):
        with self.db.write():
            entry = self.journal.add_entry('아직 커밋 전')
            self.assertIsNotNone(self.journal.get_entry(entry.entry_id))

    def test_안쪽만_실패하면_바깥은_살아남는다(self):
        with self.db.write() as con:
            self.journal.add_entry('바깥 기록')
            try:
                with self.db.write() as inner:
                    inner.execute(
                        "INSERT INTO entries(entry_id,kind,body,created_at) "
                        "VALUES ('x','note','안쪽 기록',datetime('now'))")
                    raise RuntimeError('안쪽만 실패')
            except RuntimeError:
                pass
        bodies = [e.body for e in self.journal.recent_entries()]
        self.assertEqual(bodies, ['바깥 기록'])

    def test_바깥이_실패하면_전부_되돌아간다(self):
        try:
            with self.db.write():
                self.journal.add_entry('바깥')
                with self.db.write():
                    self.journal.add_entry('안쪽')
                raise RuntimeError('바깥 실패')
        except RuntimeError:
            pass
        self.assertEqual(self.journal.count_entries(), 0)


class OnDisk(unittest.TestCase):
    """파일 DB 로 열고 닫아도 살아남는지."""

    def test_재접속_후에도_기록이_있다(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sub' / 'readingsnail.sqlite3'
            db = open_database(path)          # 폴더가 없어도 만들어야 한다
            Journal(db).add_entry('디스크에 남을 문장')
            db.close()

            again = open_database(path)
            self.assertEqual(Journal(again).count_entries(), 1)
            self.assertEqual(again.schema_version(), '1')
            # 명언 시드는 두 번째 열 때 다시 들어가지 않는다
            with again.connect() as con:
                n = con.execute('SELECT count(*) AS n FROM quotes').fetchone()['n']
            self.assertEqual(n, 24)
            again.close()

    def test_WAL_모드로_열린다(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / 'x.sqlite3')
            with db.connect() as con:
                self.assertEqual(
                    con.execute('PRAGMA journal_mode').fetchone()[0].lower(), 'wal')
            db.close()

    def test_실패한_쓰기는_되돌려진다(self):
        db = Database(':memory:')
        journal = Journal(db)
        journal.add_entry('먼저 있던 기록')
        try:
            with db.write() as con:
                con.execute("INSERT INTO entries(entry_id, kind, body, created_at) "
                            "VALUES ('x','note','추가',datetime('now'))")
                raise RuntimeError('중간에 터짐')
        except RuntimeError:
            pass
        self.assertEqual(journal.count_entries(), 1)
        db.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)


class StartupResilience(unittest.TestCase):
    """설치가 덜 끝났거나 파일이 손상돼도 기록에는 닿을 수 있어야 한다."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_시드가_깨져도_DB는_열린다(self):
        """명언은 장식이고 기록이 본체다. 시드 하나 때문에 앱이 안 열리면
        사용자는 자기 기록에 접근할 길이 없어진다."""
        from readingsnail.storage.seed import seed_quotes
        cases = {
            'broken.json': '{ not json',
            'empty.json': '',
            'nokey.json': '{"seed_version": 1}',
            'nosource.json': '{"seed_version":1,"quotes":[{"id":"x","body":"b","source":""}]}',
        }
        for name, content in cases.items():
            path = self.tmp / name
            path.write_text(content, encoding='utf-8')
            db = Database(':memory:')
            try:
                with db.connect() as con:
                    self.assertEqual(seed_quotes(con, path), 0, name)
                    self.assertEqual(
                        con.execute('SELECT count(*) AS n FROM entries').fetchone()['n'], 0)
            finally:
                db.close()

    def test_시드_파일이_아예_없어도_열린다(self):
        from readingsnail.storage.seed import seed_quotes
        db = Database(':memory:')
        try:
            with db.connect() as con:
                self.assertEqual(seed_quotes(con, self.tmp / '없음.json'), 0)
        finally:
            db.close()

    def test_strict는_여전히_알려준다(self):
        """시드를 고칠 때 실수를 잡으려면 이쪽을 쓴다."""
        from readingsnail.storage.seed import seed_quotes
        db = Database(':memory:')
        try:
            with db.connect() as con:
                with self.assertRaises(OSError):
                    seed_quotes(con, self.tmp / '없음.json', strict=True)
        finally:
            db.close()

    def test_번들_시드는_여전히_들어간다(self):
        from readingsnail.storage.seed import seed_quotes
        db = Database(':memory:')
        try:
            with db.connect() as con:
                self.assertEqual(seed_quotes(con), 24)
        finally:
            db.close()

    def test_기록_폴더_경로가_파일이면_분명히_알려준다(self):
        blocker = self.tmp / '파일임'
        blocker.write_text('x', encoding='utf-8')
        with self.assertRaises(StorageError):
            Database(blocker / 'readingsnail.sqlite3')

    def test_DB가_손상되면_StorageError(self):
        broken = self.tmp / 'broken.sqlite3'
        broken.write_bytes('SQLite 가 아니다'.encode('utf-8') * 100)
        with self.assertRaises(StorageError):
            Database(broken)

    def test_FTS가_어긋나도_재구축으로_복구된다(self):
        from readingsnail.storage import search
        db = Database(':memory:')
        try:
            Journal(db).add_entry('원래 문장 달팽이')
            with db.write() as con:
                con.execute("INSERT INTO entries_fts(entries_fts) VALUES('delete-all')")
            with db.connect() as con:
                self.assertEqual(len(search.search_entries(con, '달팽이')), 0)
            with db.connect() as con:
                search.rebuild_index(con)
                self.assertEqual(len(search.search_entries(con, '달팽이')), 1)
        finally:
            db.close()


class WroteButCannotReadBack(Base):
    """방금 쓴 줄을 다시 읽지 못하는 때 — 앱이 도는 중에 백업으로 되돌리면 실제로 걸린다.

    `assert` 로 두면 `python -O` 에서 검사가 사라져 None 이 흘러나가고,
    걸릴 때는 까닭 없는 AssertionError 만 뜬다. 둘 다 사용자를 속인다.
    """

    def test_기록을_다시_못_읽으면_까닭을_말한다(self):
        original = self.journal.get_entry
        self.journal.get_entry = lambda _id: None
        try:
            with self.assertRaises(StorageError) as caught:
                self.journal.add_entry('사라진 기록')
        finally:
            self.journal.get_entry = original
        self.assertIn('기록', str(caught.exception))

    def test_책을_다시_못_읽으면_까닭을_말한다(self):
        book = self.journal.add_book('월든')
        original = self.journal.get_book
        self.journal.get_book = lambda _id: None
        try:
            with self.assertRaises(StorageError):
                self.journal.set_status(book.book_id, 'completed')
            with self.assertRaises(StorageError):
                self.journal.update_book(book.book_id, title='다른 제목')
        finally:
            self.journal.get_book = original

    def test_고쳐_쓴_기록도_마찬가지다(self):
        entry = self.journal.add_entry('처음 글')
        original = self.journal.get_entry
        self.journal.get_entry = lambda _id: None
        try:
            with self.assertRaises(StorageError):
                self.journal.revise_entry(entry.entry_id, '고친 글')
        finally:
            self.journal.get_entry = original

    def test_검사가_최적화로_사라지지_않는다(self):
        # `python -O` 는 assert 를 통째로 지운다. 그러면 None 이 그대로 흘러나가
        # 한참 뒤 엉뚱한 자리에서 AttributeError 로 터진다.
        import subprocess
        import sys as _sys
        script = """
import sys
sys.path.insert(0, "src")
from readingsnail.storage.db import Database, StorageError
from readingsnail.storage.journal import Journal
journal = Journal(Database(":memory:"))
journal.get_entry = lambda _id: None
try:
    journal.add_entry("기록")
except StorageError:
    print("막힘")
else:
    print("통과함")
"""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'probe.py'
            path.write_text(script, encoding='utf-8')
            out = subprocess.run([_sys.executable, '-O', str(path)],
                                 capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(out.stdout.strip(), '막힘', out.stderr)


class InvisibleText(unittest.TestCase):
    """눈에 보이지 않는 문자만 있는 기록은 빈 기록이다.

    str.strip() 은 폭 0 공백(U+200B)이나 BOM(U+FEFF)을 지우지 않는다.
    붙여넣기로 섞여 들어오면 '빈 기록'이 그대로 저장된다.
    """

    def setUp(self) -> None:
        self.db = Database(':memory:')
        self.journal = Journal(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_보이지_않는_문자만_있으면_거부한다(self):
        for bad in ('​', '‌‍', '﻿', '⁠',
                    '  ​  ', '　', '­'):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.journal.add_entry(bad)

    def test_보이는_글자가_있으면_저장한다(self):
        entry = self.journal.add_entry('진짜 기록​')
        self.assertIn('진짜 기록', entry.body)

    def test_고칠_때도_같은_기준(self):
        entry = self.journal.add_entry('원래 문장')
        with self.assertRaises(ValueError):
            self.journal.revise_entry(entry.entry_id, '​')
        self.assertEqual(self.journal.get_entry(entry.entry_id).body, '원래 문장')

    def test_is_blank(self):
        from readingsnail.storage.journal import is_blank
        self.assertTrue(is_blank(''))
        self.assertTrue(is_blank('​ \n'))
        self.assertFalse(is_blank('가'))
        self.assertFalse(is_blank('​가​'))
