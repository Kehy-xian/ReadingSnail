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
        from readingsnail.__main__ import _first_words
        with self.db.connect() as conn:
            words = _first_words(self.journal, conn)
        self.assertTrue(words)

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
        rows = [panel.listbox.get(i) for i in range(panel.listbox.size())]
        self.assertTrue(any('월든' in r and '1건' in r for r in rows))
        panel.top.destroy()

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
