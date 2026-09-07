"""7단계 — 운영. 내보내기·백업·단일 인스턴스·자동 시작·주간 요약.

이 계층이 지키는 것은 하나다: **기록을 잃지 않고, 들고 나갈 수 있게 한다.**
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from readingsnail.services import autostart, backup, export, single_instance, summary  # noqa: E402
from readingsnail.storage.db import Database, open_database                            # noqa: E402
from readingsnail.storage.journal import Journal                                       # noqa: E402


def seeded(journal) -> None:
    book = journal.add_book('월든', author='헨리 데이비드 소로', status='completed',
                            publisher='은행나무', isbn13='9788956609959')
    journal.add_entry('숲으로 간 이유를 오래 생각했다', book_id=book.book_id,
                      kind='quote', page='p.31')
    journal.add_entry('나도 한동안 그러고 싶었다\n두 줄짜리 생각', book_id=book.book_id)
    journal.add_entry('책 없이 남긴 메모')


class Export(unittest.TestCase):
    """SPEC 1항: 데이터 락인 방지용이며 **선택 기능이 아니다.**"""

    def setUp(self) -> None:
        self.db = Database(':memory:')
        self.journal = Journal(self.db)
        seeded(self.journal)

    def tearDown(self) -> None:
        self.db.close()

    def test_마크다운에_모든_기록이_들어간다(self):
        text = export.to_markdown(self.journal)
        self.assertIn('월든', text)
        self.assertIn('숲으로 간 이유를 오래 생각했다', text)
        self.assertIn('책 없이 남긴 메모', text)
        self.assertIn('9788956609959', text)

    def test_필사는_인용으로_묶인다(self):
        text = export.to_markdown(self.journal)
        self.assertIn('> 숲으로 간 이유를 오래 생각했다', text)

    def test_여러_줄_기록이_보존된다(self):
        text = export.to_markdown(self.journal)
        self.assertIn('나도 한동안 그러고 싶었다\n두 줄짜리 생각', text)

    def test_CSV_한_줄에_기록_하나(self):
        import csv
        import io
        rows = list(csv.reader(io.StringIO(export.to_csv(self.journal))))
        self.assertEqual(rows[0], list(export.CSV_COLUMNS))
        self.assertEqual(len(rows), 1 + self.journal.count_entries())

    def test_CSV의_줄바꿈과_쉼표가_깨지지_않는다(self):
        import csv
        import io
        self.journal.add_entry('쉼표, 그리고\n줄바꿈이 든 기록')
        rows = list(csv.reader(io.StringIO(export.to_csv(self.journal))))
        bodies = [r[5] for r in rows[1:]]
        self.assertIn('쉼표, 그리고\n줄바꿈이 든 기록', bodies)

    def test_CSV는_엑셀에서_한글이_안_깨지게_BOM을_붙인다(self):
        with TemporaryDirectory() as tmp:
            path = export.write_csv(self.journal, Path(tmp) / 'a.csv')
            self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_기록이_없어도_내보내진다(self):
        empty = Database(':memory:')
        try:
            text = export.to_markdown(Journal(empty))
            self.assertIn('기록 0건', text)
        finally:
            empty.close()

    def test_파일로_쓴다(self):
        with TemporaryDirectory() as tmp:
            md = export.write_markdown(self.journal, Path(tmp) / 'sub' / 'a.md')
            self.assertTrue(md.is_file())
            self.assertIn('월든', md.read_text(encoding='utf-8'))

    # --- 수식 주입 -------------------------------------------------------
    # 웹에서 붙여넣은 글이 기록에 섞이면 '=' 로 시작하는 칸이 생긴다. 그 CSV 를
    # 동료에게 보내면 엑셀이 그것을 수식으로 실행한다(=cmd|... 는 DDE 공격이다).

    def _cells(self) -> list[str]:
        import csv
        import io
        rows = list(csv.reader(io.StringIO(export.to_csv(self.journal))))
        return [c for row in rows[1:] for c in row]

    def test_수식으로_시작하는_기록은_수식으로_읽히지_않는다(self):
        for body in ('=1+1', '=cmd|"/c calc"!A1', '+수식', '-빼기로 시작', '@골뱅이',
                     '\tHT로 시작', '\rCR로 시작'):
            with self.subTest(body=body):
                self.journal.add_entry(body)
        for cell in self._cells():
            self.assertNotIn(cell[:1], export._FORMULA_LEAD,
                             f'수식으로 읽히는 칸이 남았다: {cell!r}')

    def test_책_제목과_저자에도_같은_보호가_걸린다(self):
        self.journal.add_book('=위험한 제목', author='@저자')
        for cell in self._cells():
            self.assertNotIn(cell[:1], export._FORMULA_LEAD)

    def test_보이는_내용은_그대로_남는다(self):
        # 작은따옴표는 엑셀이 '이건 글자다' 표시로 읽고 화면에 보여주지 않는다.
        self.journal.add_entry('=1+1')
        self.assertIn("'=1+1", self._cells())

    def test_가운데_등호는_건드리지_않는다(self):
        self.journal.add_entry('가운데 = 는 그대로 둔다')
        self.assertIn('가운데 = 는 그대로 둔다', self._cells())

    def test_Markdown은_손대지_않는다(self):
        # 마크다운에서는 수식이 실행되지 않는다. 기록은 쓴 그대로 남아야 한다.
        self.journal.add_entry('=1+1')
        self.assertIn('\n=1+1\n', export.to_markdown(self.journal))


class Backup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.db_path = self.dir / 'rs.sqlite3'
        self.db = open_database(self.db_path)
        self.journal = Journal(self.db)
        seeded(self.journal)

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_백업이_일관된_사본을_만든다(self):
        made = backup.make_backup(self.db_path, self.dir)
        copy = open_database(made)
        try:
            self.assertEqual(Journal(copy).count_entries(), 3)
        finally:
            copy.close()

    def test_받다_만_파일이_남지_않는다(self):
        backup.make_backup(self.db_path, self.dir)
        leftovers = list((self.dir / 'backups').glob('*.part'))
        self.assertEqual(leftovers, [])

    def test_복원하면_그_시점으로_돌아간다(self):
        made = backup.make_backup(self.db_path, self.dir)
        self.journal.add_entry('백업 뒤에 쓴 기록')
        self.assertEqual(self.journal.count_entries(), 4)
        self.db.close()

        backup.restore_backup(made, self.db_path, self.dir)
        self.db = open_database(self.db_path)
        self.journal = Journal(self.db)
        self.assertEqual(self.journal.count_entries(), 3)

    def test_복원_전에_지금_것을_먼저_백업한다(self):
        """잘못 복원했다고 오늘 쓴 기록을 잃으면 안 된다."""
        made = backup.make_backup(self.db_path, self.dir)
        self.journal.add_entry('되돌리기 전에 쓴 기록')
        self.db.close()

        undo = backup.restore_backup(made, self.db_path, self.dir)
        recovered = open_database(undo)
        try:
            self.assertEqual(Journal(recovered).count_entries(), 4)
        finally:
            recovered.close()
        self.db = open_database(self.db_path)
        self.journal = Journal(self.db)

    def test_깨진_백업으로는_복원하지_않는다(self):
        bad = self.dir / 'bad.sqlite3'
        bad.write_bytes(b'not a database')
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(bad, self.db_path, self.dir)
        self.assertEqual(self.journal.count_entries(), 3, '원본이 상했다')

    def test_없는_백업(self):
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(self.dir / '없음.sqlite3', self.db_path, self.dir)

    def test_버전이_바뀔_때만_백업한다(self):
        first = backup.backup_for_version(self.db_path, self.dir, '0.0.2',
                                          stored_version='0.0.1')
        self.assertIsNotNone(first)
        again = backup.backup_for_version(self.db_path, self.dir, '0.0.2',
                                          stored_version='0.0.2')
        self.assertIsNone(again, '같은 버전인데 또 백업했다')

    def test_새_설치는_백업하지_않는다(self):
        fresh = self.dir / '없는파일.sqlite3'
        self.assertIsNone(backup.backup_for_version(fresh, self.dir, '0.0.1',
                                                    stored_version=None))

    def test_자동_백업만_솎아낸다(self):
        for i in range(12):
            backup.backup_for_version(self.db_path, self.dir, f'0.0.{i}',
                                      stored_version='old')
        manual = backup.make_backup(self.db_path, self.dir, reason='manual')
        backup.prune_backups(self.dir, reason='version', keep=3)
        kinds = [b.reason for b in backup.list_backups(self.dir)]
        self.assertEqual(kinds.count('version'), 3)
        self.assertTrue(manual.is_file(), '손으로 만든 백업을 지웠다')

    # --- 이름이 이상한 경로 -----------------------------------------------
    # `f'file:{path}?mode=ro'` 로 URI 를 만들면 '?'·'#' 에서 잘린다. SQLite 는
    # 오류를 내지 않고 **엉뚱한 빈 DB** 를 열어 백업이 멀쩡한 얼굴로 비게 된다.

    ODD_NAMES = ('백업 #2.sqlite3', '질문?.sqlite3', '퍼센트%20.sqlite3',
                 "따옴표'.sqlite3")

    def test_이름이_이상한_백업에서도_내용을_읽어_온다(self):
        # 바탕화면에서 고른 파일이 이런 이름일 수 있다. 읽는 쪽이 잘리면
        # SQLite 는 오류 없이 빈 DB 를 새로 열고, 사본이 조용히 빈다.
        want = self.journal.count_entries()
        self.assertGreater(want, 0)
        for name in self.ODD_NAMES:
            with self.subTest(name=name):
                odd = self.dir / name
                backup.copy_database(self.db_path, odd)     # 정상 이름 → 이상한 이름
                again = self.dir / 'again.sqlite3'
                backup.copy_database(odd, again)            # 이상한 이름 → 다시 읽기
                con = sqlite3.connect(again)
                try:
                    n = con.execute('SELECT count(*) FROM entries').fetchone()[0]
                finally:
                    con.close()
                self.assertEqual(n, want)

    def test_이름이_이상한_백업으로도_복원된다(self):
        for name in self.ODD_NAMES:
            with self.subTest(name=name):
                odd = self.dir / name
                backup.copy_database(self.db_path, odd)
                target = self.dir / 'restored.sqlite3'
                backup.restore_backup(odd, target, self.dir)
                con = sqlite3.connect(target)
                try:
                    n = con.execute('SELECT count(*) FROM entries').fetchone()[0]
                finally:
                    con.close()
                self.assertEqual(n, self.journal.count_entries())

    def test_빈_사본을_백업이라고_내놓지_않는다(self):
        # 원본에는 표가 있는데 사본이 비었다면 사본이 잘못된 것이다.
        # 비어 있는 백업이 멀쩡한 얼굴로 남는 것은 백업이 없는 것보다 나쁘다.
        original = backup._table_count
        seen: list[int] = []

        def counted(con):
            n = original(con)
            seen.append(n)
            return 0 if len(seen) > 1 else n     # 사본 쪽만 비어 있다고 답한다

        backup._table_count = counted
        try:
            with self.assertRaises(backup.BackupError):
                backup.copy_database(self.db_path, self.dir / 'empty.bak')
        finally:
            backup._table_count = original
        self.assertFalse((self.dir / 'empty.bak').exists())
        self.assertFalse(list(self.dir.glob('*.part')))

    def test_사용자가_넣어둔_파일은_솎아내지_않는다(self):
        folder = backup.backup_dir(self.dir)
        mine = folder / 'version.sqlite3'          # 우리 이름 규칙이 아니다
        mine.write_bytes(b'')
        for _ in range(backup.KEEP_AUTOMATIC + 3):
            backup.make_backup(self.db_path, self.dir, reason='version')
        backup.prune_backups(self.dir, reason='version')
        self.assertTrue(mine.exists())

    def test_목록은_최근_것부터(self):
        backup.make_backup(self.db_path, self.dir, reason='manual')
        found = backup.list_backups(self.dir)
        self.assertTrue(found)
        self.assertEqual(found, sorted(found, key=lambda b: b.made_at, reverse=True))


class SingleInstance(unittest.TestCase):
    def test_같은_입력이면_같은_이름(self):
        a = single_instance.instance_name(user_hint='u', data_dir_hint='d')
        b = single_instance.instance_name(user_hint='u', data_dir_hint='d')
        self.assertEqual(a, b)

    def test_데이터_폴더가_다르면_다른_이름(self):
        """프로필이 다르면 함께 떠도 된다."""
        a = single_instance.instance_name(user_hint='u', data_dir_hint='d1')
        b = single_instance.instance_name(user_hint='u', data_dir_hint='d2')
        self.assertNotEqual(a, b)

    def test_이름에_사용자와_경로가_드러나지_않는다(self):
        name = single_instance.instance_name(user_hint='홍길동',
                                             data_dir_hint='C:/Users/홍길동/기록')
        self.assertNotIn('홍길동', name)
        self.assertNotIn('Users', name)

    def test_Windows가_아니면_막지_않는다(self):
        guard = single_instance.acquire(platform='linux')
        self.assertTrue(guard.acquired)
        guard.close()


class Autostart(unittest.TestCase):
    def test_Windows에서만_지원한다(self):
        self.assertFalse(autostart.supported('linux'))
        self.assertFalse(autostart.supported('darwin'))
        self.assertTrue(autostart.supported('win32'))

    def test_개발_중에는_잠겨_있다(self):
        """python.exe 가 등록되면 엉뚱한 것이 뜬다."""
        self.assertFalse(autostart.can_enable(platform='win32', frozen=False,
                                              environ={}))
        self.assertTrue(autostart.can_enable(platform='win32', frozen=True,
                                             environ={}))
        self.assertTrue(autostart.can_enable(
            platform='win32', frozen=False,
            environ={autostart.DEV_OVERRIDE: '1'}))

    def test_명령에_따옴표를_두른다(self):
        self.assertEqual(autostart.startup_command(r'C:\Program Files\a.exe'),
                         '"C:\\Program Files\\a.exe"')
        with self.assertRaises(ValueError):
            autostart.startup_command('   ')

    def test_비Windows에서_켜면_거부한다(self):
        if autostart.supported():
            self.skipTest('Windows 에서는 다른 경로다')
        with self.assertRaises(RuntimeError):
            autostart.set_enabled(True)
        self.assertFalse(autostart.is_enabled())


class Installer(unittest.TestCase):
    """설치본이 지켜야 할 약속. 스크립트를 글로만 확인한다 — Windows 가 없다."""

    def setUp(self) -> None:
        self.script = (ROOT / 'installer' / 'ReadingSnail.iss').read_text(
            encoding='utf-8')

    def test_지울_때_기록을_건드리지_않는다(self):
        deletions = [line for line in self.script.splitlines()
                     if line.strip().lower().startswith('type:')]
        for line in deletions:
            self.assertIn('{app}', line, f'설치 폴더 밖을 지운다: {line}')

    def test_지울_때_자동_시작_등록은_거둔다(self):
        # 안 거두면 로그인할 때마다 없어진 exe 를 띄우려 든다.
        self.assertIn('RegDeleteValue', self.script)
        self.assertIn('CurrentVersion\\Run', self.script)
        self.assertIn('CurUninstallStepChanged', self.script)

    def test_설치할_때는_자동_시작을_만들지_않는다(self):
        # 기본은 꺼짐이다(SPEC 7항). 묻지도 않고 등록하면 성가신 프로그램이 된다.
        self.assertNotIn('[Registry]', self.script)
        self.assertNotIn('RegWriteStringValue', self.script)

    def test_관리자_권한을_묻지_않는다(self):
        self.assertIn('PrivilegesRequired=lowest', self.script)


class WeeklySummary(unittest.TestCase):
    """SPEC 6항: 알림 팝업으로 띄우지 않는다. 재촉하지 않는다."""

    def setUp(self) -> None:
        self.db = Database(':memory:')
        self.journal = Journal(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_이번_주만_센다(self):
        old = (datetime.now(timezone.utc) - timedelta(days=20)
               ).strftime('%Y-%m-%d %H:%M:%S')
        self.journal.add_entry('이번 주 기록')
        self.journal.add_entry('지난달 기록', created_at=old)
        result = summary.summarize(self.journal)
        self.assertEqual(result.entries, 1)
        self.assertEqual(result.total_entries, 2)

    def test_필사와_생각을_나눠_센다(self):
        book = self.journal.add_book('월든')
        self.journal.add_entry('필사', book_id=book.book_id, kind='quote')
        self.journal.add_entry('생각 1', book_id=book.book_id)
        self.journal.add_entry('생각 2', book_id=book.book_id)
        result = summary.summarize(self.journal)
        self.assertEqual((result.quotes, result.notes), (1, 2))

    def test_이번_주_완독한_책(self):
        book = self.journal.add_book('월든', author='소로')
        self.journal.set_status(book.book_id, 'completed')
        result = summary.summarize(self.journal)
        self.assertEqual(result.finished, [('월든', '소로')])

    def test_조용한_주도_말이_된다(self):
        result = summary.summarize(self.journal)
        self.assertTrue(result.quiet)
        lines = summary.as_lines(result)
        self.assertTrue(any('조용' in line for line in lines))

    def test_재촉하지_않는다(self):
        book = self.journal.add_book('방치된 책', added_at='2020-01-01 00:00:00')
        self.journal.add_entry('기록', book_id=book.book_id,
                               created_at='2020-01-02 00:00:00')
        text = '\n'.join(summary.as_lines(summary.summarize(self.journal)))
        for bad in ('일째', '안 읽', '벌써', '해야', '분발'):
            self.assertNotIn(bad, text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
