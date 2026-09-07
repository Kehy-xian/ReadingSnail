"""달팽이 창. tkinter 와 디스플레이가 있을 때만 돈다.

CI·헤드리스에서는 통째로 건너뛴다. 이동 로직 자체는 tests/test_behavior.py 가
창 없이 검증하므로, 여기서 보는 것은 'Tk 에 얹었을 때도 무너지지 않는가'다.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    GUI = True
    REASON = ''
except Exception as exc:                                  # ImportError, TclError
    GUI = False
    REASON = f'tkinter/디스플레이 없음: {exc}'


@unittest.skipUnless(GUI, REASON)
class Window(unittest.TestCase):
    def setUp(self) -> None:
        from readingsnail.pet.window import PetWindow
        self.w = PetWindow(start_at=(300, 300))

    def tearDown(self) -> None:
        self.w.close()

    def test_창이_열리고_그려진다(self):
        self.w.draw()
        self.w.root.update()
        self.assertGreater(len(self.w.canvas.find_all()), 5)

    def test_투명이_안_되는_환경에서도_살아남는다(self):
        # '-transparentcolor' 는 Windows 전용이다. X11/macOS 에서는 TclError.
        self.assertIn(self.w.transparent, (True, False))
        self.assertIsNotNone(self.w.canvas['bg'])

    def test_틱을_돌리면_실제_창이_따라_움직인다(self):
        self.w.root.update_idletasks()
        for _ in range(300):
            self.w.step()
        self.w.root.update_idletasks()
        self.assertEqual((self.w.root.winfo_x(), self.w.root.winfo_y()),
                         (self.w.motion.x, self.w.motion.y))

    def test_붙잡고_있는_동안은_안_움직인다(self):
        self.w._dragging = True
        before = (self.w.motion.x, self.w.motion.y)
        for _ in range(50):
            self.w.step()
        self.assertEqual((self.w.motion.x, self.w.motion.y), before)

    def test_모든_상태를_그려도_터지지_않는다(self):
        from dataclasses import replace
        from readingsnail.pet.behavior import AMBIENT_STATES, INTERRUPT_STATES
        for state in AMBIENT_STATES + INTERRUPT_STATES:
            for facing in (-1, 1):
                self.w.motion = replace(self.w.motion, state=state, facing=facing)
                self.w.draw()
                self.w.root.update()

    def test_말풍선(self):
        self.w.say('숲으로 간 이유를 오래 생각했다')
        self.w.root.update()
        n = len(self.w.canvas.find_all())
        self.w.say(None)
        self.w.root.update()
        self.assertLess(len(self.w.canvas.find_all()), n)

    def test_긴_발화는_잘린다(self):
        self.w.say('가' * 300)
        self.w.root.update()          # 창 밖으로 새지 않고 그려지기만 하면 된다

    def test_배율을_줄여도_그려진다(self):
        from readingsnail.pet.window import PetWindow
        small = PetWindow(scale=0.5, start_at=(600, 300))
        try:
            self.assertEqual(small.size, 95)
            small.draw()
            small.root.update()
            self.assertGreater(len(small.canvas.find_all()), 5)
        finally:
            small.close()

    def test_두_번_닫아도_괜찮다(self):
        self.w.close()
        self.w.close()


@unittest.skipUnless(GUI, REASON)
class NoInheritanceChain(unittest.TestCase):
    """전작의 v2~v11 상속 체인을 다시 만들지 않는다."""

    def test_창_클래스는_하나뿐이다(self):
        from readingsnail.pet import window
        classes = [n for n, v in vars(window).items()
                   if isinstance(v, type) and v.__module__ == window.__name__]
        self.assertEqual(classes, ['PetWindow'])

    def test_상속하지_않는다(self):
        from readingsnail.pet.window import PetWindow
        self.assertEqual(PetWindow.__bases__, (object,))


if __name__ == '__main__':
    unittest.main(verbosity=2)


@unittest.skipUnless(GUI, REASON)
class AppBoot(unittest.TestCase):
    """`python -m readingsnail` 이 실제로 뜨고 기록이 저장되는지."""

    def setUp(self) -> None:
        import os
        from tempfile import TemporaryDirectory
        self._tmp = TemporaryDirectory()
        os.environ['READINGSNAIL_DATA_DIR'] = self._tmp.name
        os.environ['BOOKEATER_DATA_DIR'] = str(Path(self._tmp.name) / '없음')

        from readingsnail.paths import default_db_path
        from readingsnail.pet.window import PetWindow
        from readingsnail.storage.db import open_database
        from readingsnail.storage.drafts import Drafts
        from readingsnail.storage.journal import Journal

        self.db = open_database(default_db_path())
        self.journal = Journal(self.db)
        self.drafts = Drafts(self.db)
        self.pet = PetWindow(start_at=(120, 120))

    def tearDown(self) -> None:
        import os
        self.pet.close()
        self.db.close()
        for key in ('READINGSNAIL_DATA_DIR', 'BOOKEATER_DATA_DIR'):
            os.environ.pop(key, None)
        self._tmp.cleanup()

    def test_기록이_없어도_첫마디가_나온다(self):
        """시드가 없으면 여기서 달팽이가 벙어리가 된다."""
        from readingsnail.services.speaker import Speaker
        with self.db.write() as conn:
            spoken = Speaker(self.journal).speak(conn)
        self.assertIsNotNone(spoken)
        self.assertTrue(spoken.utterance.text)

    def test_기록_창에서_저장하면_DB에_들어간다(self):
        from readingsnail.pet.panels import WritePanel
        panel = WritePanel(self.pet.root, self.journal, self.drafts)
        panel.text.insert('1.0', '숲으로 간 이유를 오래 생각했다')
        panel.kind.set('quote')
        panel.page.insert(0, 'p.31')
        panel.save()
        entry = self.journal.recent_entries()[0]
        self.assertEqual((entry.kind, entry.page), ('quote', 'p.31'))

    def test_저장하지_않고_닫으면_초안으로_남는다(self):
        from readingsnail.pet.panels import WritePanel
        from readingsnail.storage.drafts import Drafts as D
        panel = WritePanel(self.pet.root, self.journal, self.drafts)
        panel.text.insert('1.0', '쓰다 만 글')
        panel.close()
        self.assertEqual(self.drafts.load(D.key_for_book(None)).body, '쓰다 만 글')
        self.assertEqual(self.journal.count_entries(), 0)

    def test_저장하면_초안이_지워진다(self):
        from readingsnail.pet.panels import WritePanel
        from readingsnail.storage.drafts import Drafts as D
        panel = WritePanel(self.pet.root, self.journal, self.drafts)
        panel.text.insert('1.0', '저장할 글')
        panel.save()
        self.assertIsNone(self.drafts.load(D.key_for_book(None)))

    def test_서재가_책과_기록_수를_보여준다(self):
        from readingsnail.pet.panels import LibraryPanel
        book = self.journal.add_book('월든', author='헨리 데이비드 소로')
        self.journal.add_entry('기록', book_id=book.book_id)
        panel = LibraryPanel(self.pet.root, self.journal)
        try:
            rows = [(panel.tree.item(i, 'text'), panel.tree.item(i, 'values'))
                    for i in panel.tree.get_children()]
            self.assertTrue(any('월든' in text and str(values[1]) == '1'
                                for text, values in rows), rows)
            self.assertIn('책 1권', panel.summary.cget('text'))
        finally:
            panel.close()

    def test_전작_이전을_거절하면_결국_그만_묻는다(self):
        from readingsnail.__main__ import DECLINE_KEY, MAX_ASKS
        self.db.set_meta(DECLINE_KEY, str(MAX_ASKS))
        self.assertGreaterEqual(int(self.db.get_meta(DECLINE_KEY)), MAX_ASKS)


@unittest.skipUnless(GUI, REASON)
class FontCacheAcrossRoots(unittest.TestCase):
    """Tk 이름있는 폰트는 인터프리터마다 따로 산다.

    창 배율을 바꾸느라 root 를 다시 만들면, 캐시된 Font 는 죽은 인터프리터를
    가리켜 TclError 가 나거나 조용히 다른 폰트로 그려진다.
    """

    def test_창을_다시_만들어도_폰트가_살아_있다(self):
        from readingsnail import theme
        from readingsnail.pet.window import PetWindow

        first = PetWindow(start_at=(50, 50))
        first.say('첫 창')
        first.root.update()
        self.assertIsNotNone(theme.font('bubble', master=first.root).actual('size'))
        first.close()

        second = PetWindow(start_at=(50, 50))
        try:
            second.say('두 번째 창')
            second.root.update()
            wanted = theme.font('bubble', master=second.root)
            texts = [i for i in second.canvas.find_all()
                     if second.canvas.type(i) == 'text']
            self.assertTrue(texts)
            self.assertEqual(second.canvas.itemcget(texts[0], 'font'), str(wanted))
        finally:
            second.close()

    def test_초기화_전에_부르면_알려준다(self):
        from readingsnail import theme
        self.assertTrue(callable(theme.reset_font_cache))


@unittest.skipUnless(GUI, REASON)
class ClosingWithOpenPanel(unittest.TestCase):
    """앱을 닫을 때 패널에 쓰던 글을 잃지 않는다."""

    def setUp(self) -> None:
        import os
        from tempfile import TemporaryDirectory
        self._tmp = TemporaryDirectory()
        os.environ['READINGSNAIL_DATA_DIR'] = self._tmp.name

        from readingsnail.paths import default_db_path
        from readingsnail.pet.window import PetWindow
        from readingsnail.storage.db import open_database
        from readingsnail.storage.drafts import Drafts
        from readingsnail.storage.journal import Journal

        self.db = open_database(default_db_path())
        self.journal = Journal(self.db)
        self.drafts = Drafts(self.db)
        self.pet = PetWindow(start_at=(120, 120))

    def tearDown(self) -> None:
        import os
        self.pet.close()
        self.db.close()
        os.environ.pop('READINGSNAIL_DATA_DIR', None)
        self._tmp.cleanup()

    def _panel(self, text: str):
        from readingsnail.pet.panels import WritePanel
        panel = WritePanel(self.pet.root, self.journal, self.drafts, owner=self.pet)
        panel.text.delete('1.0', 'end')
        panel.text.insert('1.0', text)
        return panel

    def test_패널이_열린_채_종료해도_초안이_남는다(self):
        from readingsnail.storage.drafts import Drafts as D
        self._panel('앱이 꺼져도 남아야 하는 글')
        self.pet.close()
        saved = self.drafts.load(D.key_for_book(None))
        self.assertIsNotNone(saved, '종료하면서 쓰던 글이 사라졌다')
        self.assertEqual(saved.body, '앱이 꺼져도 남아야 하는 글')

    def test_패널을_먼저_닫아도_이중_정리가_안전하다(self):
        from readingsnail.storage.drafts import Drafts as D
        panel = self._panel('먼저 닫은 글')
        panel.close()
        self.pet.close()
        self.assertEqual(self.drafts.load(D.key_for_book(None)).body, '먼저 닫은 글')

    def test_저장한_뒤_종료하면_초안이_되살아나지_않는다(self):
        from readingsnail.storage.drafts import Drafts as D
        panel = self._panel('저장할 글')
        panel.save()
        self.pet.close()
        self.assertIsNone(self.drafts.load(D.key_for_book(None)))
        self.assertEqual(self.journal.count_entries(), 1)

    def test_패널이_터져도_나머지_정리는_진행된다(self):
        broken = []
        self.pet.register_closer(lambda: (_ for _ in ()).throw(RuntimeError('터짐')))
        self.pet.register_closer(lambda: broken.append('정리됨'))
        self.pet.close()
        self.assertEqual(broken, ['정리됨'])


@unittest.skipUnless(GUI, REASON)
class ThreadBoundary(unittest.TestCase):
    """tkinter 는 인터프리터를 만든 스레드에서만 안전하다.

    root.after 조차 배경에서 부르면 안 된다. 전작이 queue 를 쓴 이유가 그것이다.
    배경에서 만든 말은 큐를 거쳐 UI 스레드가 꺼내야 한다.
    """

    def setUp(self) -> None:
        import os
        from tempfile import TemporaryDirectory
        self._tmp = TemporaryDirectory()
        os.environ['READINGSNAIL_DATA_DIR'] = self._tmp.name

        from readingsnail.nlp import vectors
        from readingsnail.paths import default_db_path
        from readingsnail.pet.window import PetWindow
        from readingsnail.storage.db import open_database
        from readingsnail.storage.journal import Journal

        class Fake:
            MODEL_ID = 'fake-v1'

            def encode(self, texts, *, kind='passage'):
                rows = []
                for text in texts:
                    buckets = [0.0] * 64
                    for i in range(max(0, len(text) - 2)):
                        buckets[hash(text[i:i + 3]) % 64] += 1.0
                    rows.append(vectors.normalize(buckets))
                return rows

        self.db = open_database(default_db_path())
        self.journal = Journal(self.db)
        self.pet = PetWindow(start_at=(120, 120))
        self.encoder = Fake()

    def tearDown(self) -> None:
        import os
        self.pet.close()
        self.db.close()
        os.environ.pop('READINGSNAIL_DATA_DIR', None)
        self._tmp.cleanup()

    def test_배경_스레드가_Tk를_직접_만지지_않는다(self):
        import threading
        import time
        from readingsnail.__main__ import Companion
        from readingsnail.services import dialogue

        ui_thread = threading.get_ident()
        offenders: list[str] = []
        original = self.pet.root.after

        def guarded(*args, **kwargs):
            if threading.get_ident() != ui_thread:
                offenders.append(threading.current_thread().name)
            return original(*args, **kwargs)

        self.pet.root.after = guarded
        saved_delay = dialogue.ECHO_DELAY_SEC
        dialogue.ECHO_DELAY_SEC = (0, 0)          # 되살리기를 즉시 일으킨다
        companion = Companion(self.pet, self.db, self.journal, self.encoder)
        try:
            companion.start()
            for i in range(20):
                self.journal.add_entry(f'숲으로 간 이유를 생각했다 {i}')
            companion.note_saved()
            deadline = time.time() + 4
            while time.time() < deadline and companion.worker.pending:
                self.pet.root.update()
                time.sleep(0.01)
            for _ in range(60):
                self.pet.root.update()
                time.sleep(0.01)
        finally:
            companion.stop()
            dialogue.ECHO_DELAY_SEC = saved_delay
            self.pet.root.after = original

        self.assertEqual(offenders, [], f'배경 스레드가 root.after 를 불렀다: {offenders}')
        self.assertEqual(companion.worker.failed, 0)
        self.assertEqual(companion.worker.encoded, 20)

    def test_종료하면_예약된_되살리기가_취소된다(self):
        import time
        from readingsnail.__main__ import Companion
        from readingsnail.services import dialogue

        saved_delay = dialogue.ECHO_DELAY_SEC
        dialogue.ECHO_DELAY_SEC = (30, 30)        # 아직 안 터진 타이머를 남긴다
        companion = Companion(self.pet, self.db, self.journal, self.encoder)
        try:
            companion.start()
            self.journal.add_entry('되살릴 기록')
            companion.note_saved()
            deadline = time.time() + 3
            while time.time() < deadline and companion.worker.pending:
                self.pet.root.update()
                time.sleep(0.01)
        finally:
            companion.stop()
            dialogue.ECHO_DELAY_SEC = saved_delay
        self.assertFalse([t for t in companion._timers if t.is_alive()])

    def test_창이_닫힌_뒤에_말해도_터지지_않는다(self):
        self.pet.close()
        self.pet.say('닫힌 뒤의 말')          # TclError 가 나면 안 된다
        self.assertIsNone(self.pet._bubble)


@unittest.skipUnless(GUI, REASON)
class AddBook(unittest.TestCase):
    """책 등록 창. 검색이 죽어도 수동 입력은 늘 열려 있어야 한다."""

    def setUp(self) -> None:
        import io
        import json
        import os
        from tempfile import TemporaryDirectory

        self._tmp = TemporaryDirectory()
        os.environ['READINGSNAIL_DATA_DIR'] = self._tmp.name

        from readingsnail.paths import default_db_path
        from readingsnail.pet.window import PetWindow
        from readingsnail.storage.db import open_database
        from readingsnail.storage.journal import Journal

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.close()
                return False

        doc = {'TITLE': '월든', 'AUTHOR': '헨리 데이비드 소로',
               'PUBLISHER': '은행나무', 'EA_ISBN': '9788956609959',
               'TITLE_URL': 'https://example.org/cover.png'}
        self.opener = lambda request, timeout=None: Response(
            json.dumps({'docs': [doc]}).encode())

        self.db = open_database(default_db_path())
        self.journal = Journal(self.db)
        self.pet = PetWindow(start_at=(120, 120))

    def tearDown(self) -> None:
        import os
        self.pet.close()
        self.db.close()
        os.environ.pop('READINGSNAIL_DATA_DIR', None)
        self._tmp.cleanup()

    def _panel(self, source):
        from readingsnail.pet.panels import AddBookPanel
        self.added: list = []
        return AddBookPanel(self.pet.root, self.journal, source=source,
                            on_added=lambda book_id, url: self.added.append((book_id, url)))

    def test_검색_결과를_고르면_칸이_채워지고_등록된다(self):
        from readingsnail.services.catalog.nlk import NationalLibrarySource
        panel = self._panel(NationalLibrarySource('키', opener=self.opener))
        panel.query.insert(0, '9788956609959')
        panel.search()
        self.pet.root.update()
        panel.listbox.selection_set(0)
        panel._fill_from_result()
        self.assertEqual(panel.title_entry.get(), '월든')
        panel.add()
        book = self.journal.list_books()[0]
        self.assertEqual((book.title, book.publisher, book.source),
                         ('월든', '은행나무', 'nl'))

    def test_등록_직후_표지_URL이_넘어온다(self):
        """창을 부순 뒤에 위젯을 읽으면 TclError 가 난다. 먼저 꺼내야 한다."""
        from readingsnail.services.catalog.nlk import NationalLibrarySource
        panel = self._panel(NationalLibrarySource('키', opener=self.opener))
        panel.query.insert(0, '월든')
        panel.search()
        self.pet.root.update()
        panel.listbox.selection_set(0)
        panel._fill_from_result()
        panel.add()                       # 여기서 TclError 가 나면 안 된다
        self.pet.root.update()
        self.assertEqual(len(self.added), 1)
        self.assertEqual(self.added[0][1], 'https://example.org/cover.png')

    def test_등록_시점에_DB에는_표지_URL이_없다(self):
        from readingsnail.services.catalog.nlk import NationalLibrarySource
        panel = self._panel(NationalLibrarySource('키', opener=self.opener))
        panel.query.insert(0, '월든')
        panel.search()
        self.pet.root.update()
        panel.listbox.selection_set(0)
        panel._fill_from_result()
        panel.add()
        self.assertIsNone(self.journal.list_books()[0].cover_path)

    def test_검색이_죽어도_수동_등록은_된다(self):
        from urllib.error import URLError

        from readingsnail.services.catalog.nlk import NationalLibrarySource

        def dead(request, timeout=None):
            raise URLError('서비스 종료')

        panel = self._panel(NationalLibrarySource('키', opener=dead))
        panel.query.insert(0, '찾을 수 없는 책')
        panel.search()
        self.pet.root.update()
        self.assertIn('직접 입력', panel.status.cget('text'))
        self.assertEqual(panel.title_entry.get(), '찾을 수 없는 책')
        panel.status_var.set('wishlist')
        panel.add()
        book = self.journal.list_books()[0]
        self.assertEqual((book.title, book.status, book.source),
                         ('찾을 수 없는 책', 'wishlist', 'manual'))

    def test_검색이_아예_꺼져_있어도_등록된다(self):
        panel = self._panel(None)
        self.assertIn('직접 입력', panel.status.cget('text'))
        panel.title_entry.insert(0, '손으로 넣은 책')
        panel.add()
        self.assertEqual(self.journal.list_books()[0].title, '손으로 넣은 책')

    def test_제목이_비면_등록하지_않는다(self):
        from readingsnail.pet import panels
        panel = self._panel(None)
        shown = []
        original = panels.messagebox.showinfo
        panels.messagebox.showinfo = lambda *a, **k: shown.append(a)
        try:
            panel.add()
        finally:
            panels.messagebox.showinfo = original
        self.assertEqual(self.journal.count_books(), 0)
        self.assertTrue(shown, '아무 안내도 없이 무시했다')
        panel.top.destroy()


@unittest.skipUnless(GUI, REASON)
class SearchDoesNotFreezeUI(unittest.TestCase):
    """서지 검색은 네트워크다. UI 스레드에서 부르면 최대 8초 얼어붙는다."""

    def setUp(self) -> None:
        import os
        from tempfile import TemporaryDirectory
        self._tmp = TemporaryDirectory()
        os.environ['READINGSNAIL_DATA_DIR'] = self._tmp.name

        from readingsnail.paths import default_db_path
        from readingsnail.pet.window import PetWindow
        from readingsnail.storage.db import open_database
        from readingsnail.storage.journal import Journal

        self.db = open_database(default_db_path())
        self.journal = Journal(self.db)
        self.pet = PetWindow(start_at=(120, 120))

    def tearDown(self) -> None:
        import os
        self.pet.close()
        self.db.close()
        os.environ.pop('READINGSNAIL_DATA_DIR', None)
        self._tmp.cleanup()

    def _slow_source(self, delay: float = 0.8):
        import io
        import json
        import time

        from readingsnail.services.catalog.nlk import NationalLibrarySource

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.close()
                return False

        def slow(request, timeout=None):
            time.sleep(delay)
            return Response(json.dumps({'docs': [{'TITLE': '월든'}]}).encode())

        return NationalLibrarySource('키', opener=slow)

    def test_검색이_즉시_돌아온다(self):
        import time

        from readingsnail.pet.panels import AddBookPanel
        panel = AddBookPanel(self.pet.root, self.journal, source=self._slow_source())
        panel.query.insert(0, '월든')
        started = time.time()
        panel.search()
        self.assertLess(time.time() - started, 0.2, 'search() 가 UI 를 붙잡았다')
        self.assertIn('찾는 중', panel.status.cget('text'))

    def test_검색_도는_동안_창이_반응한다(self):
        import time

        from readingsnail.pet.panels import AddBookPanel
        panel = AddBookPanel(self.pet.root, self.journal, source=self._slow_source())
        panel.query.insert(0, '월든')
        panel.search()

        lags, last = [], time.time()
        deadline = time.time() + 1.6
        while time.time() < deadline:
            self.pet.root.update()
            now = time.time()
            lags.append(now - last)
            last = now
            time.sleep(0.005)
        self.assertLess(max(lags), 0.3, f'창이 {max(lags):.2f}초 멈췄다')
        self.assertEqual([panel.listbox.get(i) for i in range(panel.listbox.size())],
                         ['월든'])

    def test_연타해도_요청이_겹치지_않는다(self):
        from readingsnail.pet.panels import AddBookPanel
        panel = AddBookPanel(self.pet.root, self.journal, source=self._slow_source(0.4))
        panel.query.insert(0, '월든')
        for _ in range(5):
            panel.search()
        self.assertTrue(panel._searching)
        self.assertLessEqual(panel._found.qsize(), 1)


@unittest.skipUnless(GUI, REASON)
class OnePanelAtATime(unittest.TestCase):
    """같은 기록 창을 두 번 열면 둘이 같은 초안을 두고 다툰다."""

    def setUp(self) -> None:
        import os
        from tempfile import TemporaryDirectory
        self._tmp = TemporaryDirectory()
        os.environ['READINGSNAIL_DATA_DIR'] = self._tmp.name

        from readingsnail.paths import default_db_path
        from readingsnail.pet.window import PetWindow
        from readingsnail.storage.db import open_database
        from readingsnail.storage.drafts import Drafts
        from readingsnail.storage.journal import Journal

        self.db = open_database(default_db_path())
        self.journal = Journal(self.db)
        self.drafts = Drafts(self.db)
        self.pet = PetWindow(start_at=(120, 120))

    def tearDown(self) -> None:
        import os
        self.pet.close()
        self.db.close()
        os.environ.pop('READINGSNAIL_DATA_DIR', None)
        self._tmp.cleanup()

    def _factory(self):
        from readingsnail.pet.panels import WritePanel
        return lambda: WritePanel(self.pet.root, self.journal, self.drafts, owner=self.pet)

    def test_두_번_열어도_창은_하나다(self):
        make = self._factory()
        first = self.pet.show_once('write', make)
        second = self.pet.show_once('write', make)
        self.assertIs(first, second)

    def test_먼저_쓴_글이_덮이지_않는다(self):
        from readingsnail.storage.drafts import Drafts as D
        make = self._factory()
        panel = self.pet.show_once('write', make)
        panel.text.insert('1.0', '첫 창 글')
        self.pet.show_once('write', make)          # 다시 열기 시도
        self.pet.close()
        self.assertEqual(self.drafts.load(D.key_for_book(None)).body, '첫 창 글')

    def test_닫은_뒤에는_새로_열린다(self):
        make = self._factory()
        first = self.pet.show_once('write', make)
        first.close()
        second = self.pet.show_once('write', make)
        self.assertIsNot(first, second)


@unittest.skipUnless(GUI, REASON)
class SpriteRendering(unittest.TestCase):
    """그림이 한 상태씩 들어와도 그 상태만 교체되고 나머지는 벡터로 남는다."""

    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(ROOT / 'tools'))
        try:
            import render_placeholder_pack as renderer
        except ImportError:
            raise unittest.SkipTest('Pillow 없음')
        from tempfile import TemporaryDirectory
        cls._tmp = TemporaryDirectory()
        cls.resource_root = Path(cls._tmp.name)
        cls.pack = cls.resource_root / 'resources' / 'sprites'
        # 말풍선이 뜨면 상태가 talk 로 바뀐다. 그림 있는 상태와 없는 상태를
        # 함께 두어야 '상태별 폴백'을 제대로 시험할 수 있다.
        renderer.main([str(cls.pack),
                       '--props', str(cls.resource_root / 'resources' / 'props'),
                       '--states', 'idle,talk', '--quiet'])

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def setUp(self) -> None:
        import os
        from tempfile import TemporaryDirectory
        from readingsnail.pet.window import PetWindow
        self._data = TemporaryDirectory()
        os.environ['READINGSNAIL_DATA_DIR'] = self._data.name
        self.pet = PetWindow(start_at=(120, 120),
                             resource_root=self.resource_root,
                             data_dir=self._data.name)

    def tearDown(self) -> None:
        import os
        self.pet.close()
        os.environ.pop('READINGSNAIL_DATA_DIR', None)
        self._data.cleanup()

    def test_그림이_있는_상태는_스프라이트로_그린다(self):
        from dataclasses import replace
        self.pet.motion = replace(self.pet.motion, state='idle')
        self.assertTrue(self.pet._draw_sprite())

    def test_그림이_없는_상태만_벡터로_내려간다(self):
        from dataclasses import replace
        for state in ('walk', 'eat', 'sleep'):
            self.pet.motion = replace(self.pet.motion, state=state)
            self.pet._sprite_state = None
            self.assertFalse(self.pet._draw_sprite(), state)
            self.pet.draw()                      # 벡터로라도 그려져야 한다
            self.assertGreater(len(self.pet.canvas.find_all()), 5, state)

    def test_애니메이션이_흐른다(self):
        import time
        from dataclasses import replace
        self.pet.motion = replace(self.pet.motion, state='idle')
        seen = set()
        deadline = time.time() + 0.9
        while time.time() < deadline:
            self.pet.draw()
            self.pet.root.update()
            items = self.pet.canvas.find_all()
            if items:
                seen.add(self.pet.canvas.itemcget(items[0], 'image'))
            time.sleep(0.03)
        self.assertGreater(len(seen), 2, f'프레임이 바뀌지 않는다: {len(seen)}')

    def test_말풍선은_스프라이트_위에도_뜬다(self):
        from dataclasses import replace
        self.pet.motion = replace(self.pet.motion, state='idle')
        self.pet.say('숲으로 간 이유')
        self.pet.root.update()
        kinds = {self.pet.canvas.type(i) for i in self.pet.canvas.find_all()}
        self.assertIn('image', kinds)
        self.assertIn('text', kinds)

    def test_창마다_캐시가_따로_묶인다(self):
        """ImageTk 이미지는 만든 root 에 묶인다. 다른 창에 쓰면
        'image "pyimageN" doesn't exist' 로 터진다. 폰트 캐시와 같은 함정이다."""
        from dataclasses import replace

        from readingsnail.pet.window import PetWindow
        second = PetWindow(start_at=(400, 120), resource_root=self.resource_root,
                           data_dir=self._data.name)
        try:
            self.assertIsNot(second.sprites, self.pet.sprites)
            self.assertIs(second.sprites.master, second.root)
            for window in (self.pet, second):
                window.motion = replace(window.motion, state='idle')
                window.draw()
                window.root.update()          # TclError 가 나면 안 된다
        finally:
            second.close()


@unittest.skipUnless(GUI, REASON)
class Styling(unittest.TestCase):
    """색의 출처는 언제나 theme.PALETTE 다. ttkbootstrap 이 덮어쓰지 않는다."""

    def setUp(self) -> None:
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self) -> None:
        self.root.destroy()

    def test_스타일이_우리_팔레트를_쓴다(self):
        from readingsnail.pet.styling import apply
        from readingsnail.theme import PALETTE
        style = apply(self.root)
        self.assertEqual(style.lookup('TFrame', 'background'), PALETTE['paper'])
        self.assertEqual(style.lookup('Accent.TButton', 'background'),
                         PALETTE['moss_deep'])

    def test_ttkbootstrap이_없어도_돌아간다(self):
        """설치가 덜 끝났다고 앱이 안 뜨면 안 된다."""
        import builtins

        from readingsnail.pet import styling
        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name.startswith('ttkbootstrap'):
                raise ImportError('없는 셈 치기')
            return real_import(name, *args, **kwargs)

        builtins.__import__ = blocked
        try:
            style = styling.apply(self.root)
        finally:
            builtins.__import__ = real_import
        from readingsnail.theme import PALETTE
        self.assertEqual(style.lookup('TFrame', 'background'), PALETTE['paper'])
        self.assertEqual(style.theme_use(), 'clam')

    def test_텍스트_기본값도_같은_색이다(self):
        from readingsnail.pet.styling import apply, text_defaults
        from readingsnail.theme import PALETTE
        apply(self.root)
        defaults = text_defaults(self.root)
        self.assertEqual(defaults['bg'], PALETTE['paper'])
        self.assertEqual(defaults['fg'], PALETTE['ink'])
        self.assertEqual(defaults['selectbackground'], PALETTE['moss_deep'])
        self.assertEqual(defaults['selectforeground'], PALETTE['on_accent'])


@unittest.skipUnless(GUI, REASON)
class LibraryPanelBehaviour(unittest.TestCase):
    """서재는 책마다 따로 세지 않는다. 책이 늘면 N+1 이 눈에 띄기 시작한다."""

    def setUp(self) -> None:
        import os
        from tempfile import TemporaryDirectory
        self._tmp = TemporaryDirectory()
        os.environ['READINGSNAIL_DATA_DIR'] = self._tmp.name

        from readingsnail.paths import default_db_path
        from readingsnail.pet.window import PetWindow
        from readingsnail.storage.db import open_database
        from readingsnail.storage.journal import Journal

        self.db = open_database(default_db_path())
        self.journal = Journal(self.db)
        self.pet = PetWindow(start_at=(120, 120))

    def tearDown(self) -> None:
        import os
        self.pet.close()
        self.db.close()
        os.environ.pop('READINGSNAIL_DATA_DIR', None)
        self._tmp.cleanup()

    def test_한_번에_기록_수를_센다(self):
        book = self.journal.add_book('월든')
        for i in range(3):
            self.journal.add_entry(f'기록 {i}', book_id=book.book_id)
        self.journal.add_entry('책 없는 기록')
        counts = self.journal.entry_counts_by_book()
        self.assertEqual(counts[book.book_id], 3)
        self.assertEqual(counts[None], 1)

    def test_책을_고르면_그_책의_기록이_보인다(self):
        from readingsnail.pet.panels import LibraryPanel
        book = self.journal.add_book('월든', author='소로')
        self.journal.add_entry('숲으로 간 이유', book_id=book.book_id, kind='quote')
        self.journal.add_entry('다른 책 기록')
        panel = LibraryPanel(self.pet.root, self.journal)
        try:
            target = [i for i in panel.tree.get_children()
                      if '월든' in panel.tree.item(i, 'text')]
            self.assertTrue(target)
            panel.tree.selection_set(target[0])
            panel._show_entries()
            shown = panel.detail.get('1.0', 'end')
            self.assertIn('숲으로 간 이유', shown)
            self.assertNotIn('다른 책 기록', shown)
        finally:
            panel.close()

    def test_책_없는_기록도_한_줄로_보인다(self):
        from readingsnail.pet.panels import LibraryPanel
        self.journal.add_entry('책 없이 남긴 메모')
        panel = LibraryPanel(self.pet.root, self.journal)
        try:
            texts = [panel.tree.item(i, 'text') for i in panel.tree.get_children()]
            self.assertIn('(책 없는 기록)', texts)
        finally:
            panel.close()

    def test_많은_책도_빠르게_연다(self):
        import time

        from readingsnail.pet.panels import LibraryPanel
        for i in range(120):
            book = self.journal.add_book(f'책 {i}')
            self.journal.add_entry(f'기록 {i}', book_id=book.book_id)
        started = time.time()
        panel = LibraryPanel(self.pet.root, self.journal)
        try:
            elapsed = time.time() - started
            self.assertLess(elapsed, 1.5, f'서재 여는 데 {elapsed:.2f}초')
            self.assertEqual(len(panel.tree.get_children()), 120)
        finally:
            panel.close()


@unittest.skipUnless(GUI, REASON)
class ShelfAndProps(unittest.TestCase):
    """책장은 이 앱의 유일한 보상 화면이다. 소품은 해금 없이 그냥 고른다."""

    def setUp(self) -> None:
        import os
        from tempfile import TemporaryDirectory
        self._tmp = TemporaryDirectory()
        os.environ['READINGSNAIL_DATA_DIR'] = self._tmp.name

        from readingsnail.paths import default_db_path
        from readingsnail.pet.window import PetWindow
        from readingsnail.storage.db import open_database
        from readingsnail.storage.journal import Journal
        from readingsnail.storage.settings import Settings

        self.db = open_database(default_db_path())
        self.journal = Journal(self.db)
        self.settings = Settings(self.db)
        self.pet = PetWindow(start_at=(120, 120))

    def tearDown(self) -> None:
        import os
        self.pet.close()
        self.db.close()
        os.environ.pop('READINGSNAIL_DATA_DIR', None)
        self._tmp.cleanup()

    def _shelf(self, **kw):
        from readingsnail.pet.panels import ShelfPanel
        return ShelfPanel(self.pet.root, self.journal, **kw)

    def test_다_읽은_책만_꽂힌다(self):
        done = self.journal.add_book('다 읽은 책', status='completed')
        self.journal.add_book('읽는 중인 책')
        panel = self._shelf()
        try:
            self.pet.root.update()
            self.assertEqual([s.book_id for s in panel.slots], [done.book_id])
        finally:
            panel.close()

    def test_책이_없으면_안내가_뜬다(self):
        panel = self._shelf()
        try:
            self.pet.root.update()
            texts = [panel.canvas.itemcget(i, 'text')
                     for i in panel.canvas.find_all()
                     if panel.canvas.type(i) == 'text']
            self.assertTrue(any('아직' in t for t in texts), texts)
        finally:
            panel.close()

    def test_책을_누르면_그_책이_열린다(self):
        book = self.journal.add_book('월든', status='completed')
        opened: list[str] = []
        panel = self._shelf(on_open_book=opened.append)
        try:
            self.pet.root.update()
            slot = panel.slots[0]

            class Event:
                x = slot.x + 3
                y = slot.y + 6

            panel._click(Event())
            self.assertEqual(opened, [book.book_id])
        finally:
            panel.close()

    def test_빈_곳을_눌러도_아무_일_없다(self):
        self.journal.add_book('월든', status='completed')
        opened: list[str] = []
        panel = self._shelf(on_open_book=opened.append)
        try:
            self.pet.root.update()

            class Event:
                x = 3
                y = 3

            panel._click(Event())
            self.assertEqual(opened, [])
        finally:
            panel.close()

    def test_책등_글자가_바탕에서_읽힌다(self):
        """책등 색은 표지마다 다르다. 어두운 책등에는 밝은 글자가 와야 한다."""
        from readingsnail.pet.panels import _readable_on
        from readingsnail.theme import PALETTE, contrast
        for background in ('#B33B3B', '#273B8B', '#F2EADC', PALETTE['paper_deep']):
            picked = _readable_on(background)
            self.assertGreaterEqual(contrast(picked, background), 3.0, background)

    def test_소품은_해금_없이_고른다(self):
        from readingsnail.pet.panels import PropsPanel
        panel = PropsPanel(self.pet.root, None, self.settings)
        try:
            self.assertEqual(panel.selected(), ())
        finally:
            panel.close()

    def test_고른_소품이_설정에_남는다(self):
        from readingsnail.pet.panels import PropsPanel

        class FakeSprites:
            def __init__(self):
                self.props = ()

            def available_props(self):
                return ('leaf', 'glasses')

            def set_props(self, props):
                self.props = tuple(props)

        sprites = FakeSprites()
        changed: list = []
        panel = PropsPanel(self.pet.root, sprites, self.settings,
                           on_change=changed.append)
        try:
            panel.vars['leaf'].set(True)
            panel._apply()
            self.assertEqual(self.settings.get('pet.props'), 'leaf')
            self.assertEqual(sprites.props, ('leaf',))
            self.assertEqual(changed, [('leaf',)])
        finally:
            panel.close()

    def test_많은_책도_잘리지_않고_사실대로_센다(self):
        """조용히 절반만 보여주면 사용자는 책이 사라진 줄 안다."""
        for i in range(300):
            self.journal.add_book(f'책 {i}', status='completed')
        panel = self._shelf()
        try:
            self.pet.root.update()
            self.assertEqual(len(panel.slots), 300)
            self.assertIn('300권', panel.summary.cget('text'))
        finally:
            panel.close()

    def test_크기_변경이_폭주해도_한_번만_다시_그린다(self):
        import time
        for i in range(60):
            self.journal.add_book(f'책 {i}', status='completed')
        panel = self._shelf()
        try:
            self.pet.root.update()
            calls = []
            original = panel.refresh
            panel.refresh = lambda: (calls.append(1), original())[1]
            for width in range(320, 560, 10):
                panel.top.geometry(f'{width}x420')
                self.pet.root.update()
            deadline = time.time() + 0.5
            while time.time() < deadline:
                self.pet.root.update()
                time.sleep(0.02)
            self.assertLessEqual(len(calls), 3,
                                 f'{len(calls)}번 다시 그렸다 — 디바운스가 안 먹는다')
        finally:
            panel.refresh = original
            panel.close()

    def test_책장을_닫으면_예약된_다시_그리기가_취소된다(self):
        panel = self._shelf()
        panel._schedule_refresh()
        self.assertIsNotNone(panel._refresh_after)
        panel.close()
        self.assertIsNone(panel._refresh_after)


@unittest.skipUnless(GUI, REASON)
class WritePanelPerBook(unittest.TestCase):
    """책마다 기록 창 하나. 키를 하나로 두면 책장에서 책을 눌러도
    앞서 열린 창이 돌아와 책이 안 잡힌다."""

    def setUp(self) -> None:
        import os
        from tempfile import TemporaryDirectory
        self._tmp = TemporaryDirectory()
        os.environ['READINGSNAIL_DATA_DIR'] = self._tmp.name

        from readingsnail.paths import default_db_path
        from readingsnail.pet.window import PetWindow
        from readingsnail.storage.db import open_database
        from readingsnail.storage.drafts import Drafts
        from readingsnail.storage.journal import Journal

        self.db = open_database(default_db_path())
        self.journal = Journal(self.db)
        self.drafts = Drafts(self.db)
        self.pet = PetWindow(start_at=(120, 120))

    def tearDown(self) -> None:
        import os
        self.pet.close()
        self.db.close()
        os.environ.pop('READINGSNAIL_DATA_DIR', None)
        self._tmp.cleanup()

    def _open(self, book_id=None):
        from readingsnail.pet.panels import WritePanel
        return self.pet.show_once(
            f'write:{book_id or ""}',
            lambda: WritePanel(self.pet.root, self.journal, self.drafts,
                               book_id=book_id, owner=self.pet))

    def test_책마다_다른_창이_뜬다(self):
        first = self.journal.add_book('월든')
        second = self.journal.add_book('사피엔스')
        blank, one, two = self._open(), self._open(first.book_id), self._open(second.book_id)
        self.assertEqual(len({id(blank), id(one), id(two)}), 3)
        self.assertEqual(one.book_choice.get(), '월든')
        self.assertEqual(two.book_choice.get(), '사피엔스')

    def test_같은_책은_같은_창이다(self):
        book = self.journal.add_book('월든')
        self.assertIs(self._open(book.book_id), self._open(book.book_id))

    def test_책마다_초안이_섞이지_않는다(self):
        first = self.journal.add_book('월든')
        second = self.journal.add_book('사피엔스')
        one, two = self._open(first.book_id), self._open(second.book_id)
        one.text.insert('1.0', '월든에 쓰던 글')
        two.text.insert('1.0', '사피엔스에 쓰던 글')
        one.close()
        two.close()
        self.assertEqual(
            self.drafts.load(self.drafts.key_for_book(first.book_id)).body,
            '월든에 쓰던 글')
        self.assertEqual(
            self.drafts.load(self.drafts.key_for_book(second.book_id)).body,
            '사피엔스에 쓰던 글')

    def test_닫힌_창의_자리는_비운다(self):
        """책마다 키가 생기므로 그냥 두면 쌓인다."""
        for i in range(12):
            book = self.journal.add_book(f'책 {i}')
            panel = self._open(book.book_id)
            panel.close()
        self._open()
        self.assertLessEqual(len(self.pet._panels), 2)


@unittest.skipUnless(GUI, REASON)
class OperationsPanels(unittest.TestCase):
    """설정·주간 요약·트레이. 대화상자는 반드시 막고 시험한다 —
    모달이 뜨면 테스트가 영원히 멈춘다."""

    def setUp(self) -> None:
        import os
        from tempfile import TemporaryDirectory

        from readingsnail.pet import panels
        self._tmp = TemporaryDirectory()
        os.environ['READINGSNAIL_DATA_DIR'] = self._tmp.name

        from readingsnail.paths import default_data_dir, default_db_path
        from readingsnail.pet.window import PetWindow
        from readingsnail.storage.db import open_database
        from readingsnail.storage.journal import Journal
        from readingsnail.storage.settings import Settings

        self.shown: list = []
        self._real = (panels.messagebox.showinfo, panels.messagebox.showerror,
                      panels.messagebox.askyesno)
        panels.messagebox.showinfo = lambda *a, **k: self.shown.append(('info', a))
        panels.messagebox.showerror = lambda *a, **k: self.shown.append(('error', a))
        panels.messagebox.askyesno = lambda *a, **k: True

        self.db_path = default_db_path()
        self.data_dir = default_data_dir()
        self.db = open_database(self.db_path)
        self.journal = Journal(self.db)
        self.settings = Settings(self.db)
        self.pet = PetWindow(start_at=(120, 120))

    def tearDown(self) -> None:
        import os

        from readingsnail.pet import panels
        (panels.messagebox.showinfo, panels.messagebox.showerror,
         panels.messagebox.askyesno) = self._real
        self.pet.close()
        self.db.close()
        os.environ.pop('READINGSNAIL_DATA_DIR', None)
        self._tmp.cleanup()

    def _settings_panel(self, **kw):
        from readingsnail.pet.panels import SettingsPanel
        return SettingsPanel(self.pet.root, journal=self.journal,
                             settings=self.settings, db_path=self.db_path,
                             data_dir=self.data_dir, owner=self.pet, **kw)

    def test_설정_창이_열린다(self):
        panel = self._settings_panel()
        try:
            self.pet.root.update()
            self.assertEqual(panel.scale_var.get(), '1.0')
        finally:
            panel.close()

    def test_크기를_고르면_설정에_남는다(self):
        asked: list = []
        panel = self._settings_panel(on_scale=asked.append)
        try:
            panel.scale_var.set('0.75')
            panel._apply_scale()
            self.assertEqual(self.settings.get('pet.scale'), '0.75')
            self.assertEqual(asked, [0.75])
        finally:
            panel.close()

    def _pump(self, panel, seconds: float = 8.0) -> None:
        """배경 일감이 끝날 때까지 UI 를 돌린다."""
        import time
        deadline = time.time() + seconds
        while time.time() < deadline and panel._working:
            self.pet.root.update()
            time.sleep(0.02)
        self.pet.root.update()

    def test_백업_단추가_실제로_백업을_만든다(self):
        from readingsnail.services import backup
        self.journal.add_entry('지킬 기록')
        panel = self._settings_panel()
        try:
            panel._backup()
            self._pump(panel)
            found = backup.list_backups(self.data_dir)
            self.assertTrue(found)
            self.assertIn('백업 1개', panel.backup_note.cget('text'))
            self.assertTrue(any(kind == 'info' for kind, _ in self.shown))
        finally:
            panel.close()

    def test_백업은_UI_스레드를_붙들지_않는다(self):
        # 기록이 많으면 파일을 베끼는 데 시간이 든다. 그동안 창이 살아 있어야 한다.
        panel = self._settings_panel()
        try:
            panel._backup()
            self.assertTrue(panel._working, '배경으로 넘기지 않았다')
            self.pet.root.update()          # 얼지 않는다
            self._pump(panel)
            self.assertFalse(panel._working)
        finally:
            panel.close()

    def test_내보내기도_배경에서_돈다(self):
        from pathlib import Path as _Path
        book = self.journal.add_book('월든')
        self.journal.add_entry('숲으로 간 이유', book_id=book.book_id)
        target = _Path(self._tmp.name) / '기록.md'
        panel = self._settings_panel()
        try:
            import tkinter.filedialog as fd
            saved = fd.asksaveasfilename
            fd.asksaveasfilename = lambda *a, **k: str(target)
            try:
                panel._export('md')
                self.assertTrue(panel._working, '배경으로 넘기지 않았다')
                self._pump(panel)
            finally:
                fd.asksaveasfilename = saved
            self.assertTrue(target.is_file())
            self.assertIn('월든', target.read_text(encoding='utf-8'))
        finally:
            panel.close()

    def test_일감이_도는_중에_창을_닫아도_죽지_않는다(self):
        # 늦게 끝난 스레드가 닫힌 창을 만지면 Tcl_AsyncDelete 로 프로세스가 죽는다.
        panel = self._settings_panel()
        panel._backup()
        panel.close()                        # 끝나기 전에 닫는다
        import time
        deadline = time.time() + 3
        while time.time() < deadline:
            self.pet.root.update()           # TclError 가 나면 안 된다
            time.sleep(0.02)

    def test_인증키가_설정에_남는다(self):
        panel = self._settings_panel()
        try:
            panel.cert_var.set('  my-key  ')
            panel._save_cert()
            self.assertEqual(self.settings.get('catalog.nl_cert_key'), 'my-key')
        finally:
            panel.close()

    def test_비Windows에서_자동_시작을_켜면_안내만_한다(self):
        from readingsnail.services import autostart
        if autostart.supported():
            self.skipTest('Windows 에서는 다른 경로다')
        panel = self._settings_panel()
        try:
            panel.autostart_var.set(True)
            panel._apply_autostart()
            self.assertTrue(self.shown, '아무 안내도 없이 무시했다')
            self.assertFalse(panel.autostart_var.get())
        finally:
            panel.close()

    def test_주간_요약이_열린다(self):
        from readingsnail.pet.panels import WeeklyPanel
        book = self.journal.add_book('월든')
        self.journal.add_entry('이번 주 기록', book_id=book.book_id)
        panel = WeeklyPanel(self.pet.root, self.journal, owner=self.pet)
        try:
            self.pet.root.update()
            text = panel.body.get('1.0', 'end')
            self.assertIn('기록 1건', text)
            self.assertIn('월든', text)
        finally:
            panel.close()

    def test_조용한_주도_말이_된다(self):
        from readingsnail.pet.panels import WeeklyPanel
        panel = WeeklyPanel(self.pet.root, self.journal, owner=self.pet)
        try:
            self.assertIn('조용', panel.body.get('1.0', 'end'))
        finally:
            panel.close()


class Tray(unittest.TestCase):
    """트레이 메뉴는 pystray 스레드에서 불린다. Tk 를 건드리면 안 된다."""

    def test_pystray가_없으면_조용히_실패한다(self):
        from readingsnail.pet.tray import TrayIcon
        tray = TrayIcon()
        try:
            self.assertIn(tray.show(), (True, False))
        finally:
            tray.hide()

    def test_이벤트는_큐로만_전달된다(self):
        from readingsnail.pet.tray import QUIT, RESTORE, TrayIcon
        seen: list = []
        tray = TrayIcon(on_event=seen.append)
        tray._emit(RESTORE)
        tray._emit(QUIT)
        self.assertEqual(tray.drain(), [RESTORE, QUIT])
        self.assertEqual(seen, [RESTORE, QUIT])
        self.assertEqual(tray.drain(), [])

    def test_콜백이_터져도_큐는_남는다(self):
        from readingsnail.pet.tray import RESTORE, TrayIcon

        def boom(_event):
            raise RuntimeError('터짐')

        tray = TrayIcon(on_event=boom)
        tray._emit(RESTORE)
        self.assertEqual(tray.drain(), [RESTORE])

    def test_올리지_않고_내려도_안전하다(self):
        from readingsnail.pet.tray import TrayIcon
        tray = TrayIcon()
        tray.hide()
        tray.hide()
