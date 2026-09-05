"""6-c — 책장 배치와 표지 색.

배치는 순수 함수라 화면 없이 검증한다. 이동 로직과 같은 태도다.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from readingsnail.pet import shelf                                   # noqa: E402


@dataclass
class FakeBook:
    book_id: str
    title: str
    spine_tint: str | None = None
    spine_style: int = 0


def books(n: int) -> list[FakeBook]:
    return [FakeBook(f'book-{i}', f'책 {i}') for i in range(n)]


class Layout(unittest.TestCase):
    def test_빈_책장(self):
        shelves, slots = shelf.layout([], width=520)
        self.assertEqual(slots, [])
        self.assertEqual(len(shelves), 1)
        self.assertGreater(shelf.canvas_height(shelves), 0)

    def test_한_층에_다_들어가면_한_층(self):
        shelves, slots = shelf.layout(books(3), width=520)
        self.assertEqual(len(shelves), 1)
        self.assertEqual(len(slots), 3)

    def test_넘치면_아래로_늘어난다(self):
        """SPEC 5항: 완독 권수에 따라 선반이 아래로 늘어남."""
        few = shelf.layout(books(5), width=400)[0]
        many = shelf.layout(books(60), width=400)[0]
        self.assertGreater(len(many), len(few))
        self.assertGreater(shelf.canvas_height(many), shelf.canvas_height(few))

    def test_책이_선반_밖으로_나가지_않는다(self):
        width = 420
        shelves, slots = shelf.layout(books(40), width=width)
        for slot in slots:
            self.assertGreaterEqual(slot.x, 0)
            self.assertLessEqual(slot.x + slot.width, width)

    def test_같은_층의_책은_바닥선을_공유한다(self):
        shelves, slots = shelf.layout(books(30), width=520)
        by_bottom: dict[int, int] = {}
        for slot in slots:
            by_bottom[slot.bottom] = by_bottom.get(slot.bottom, 0) + 1
        # 눕힌 책도 바닥에 놓이므로 바닥선 종류는 층 수와 같아야 한다
        self.assertEqual(len(by_bottom), len(shelves))

    def test_정돈감을_깬다(self):
        """SPEC 5항: 기울어진 책 1~2권, 눕힌 책 1권을 섞는다."""
        _, slots = shelf.layout(books(60), width=520)
        tilted = [s for s in slots if s.tilt]
        lying = [s for s in slots if s.lying]
        self.assertTrue(tilted, '전부 똑바로 서 있다')
        self.assertTrue(lying, '눕힌 책이 하나도 없다')
        # 그렇다고 절반이 넘어가면 어수선하다
        self.assertLess(len(tilted) / len(slots), 0.5)
        self.assertLess(len(lying) / len(slots), 0.2)

    def test_같은_책은_언제나_같은_자세(self):
        """무작위로 하면 창을 열 때마다 책이 춤춘다."""
        first = shelf.layout(books(30), width=520)[1]
        second = shelf.layout(books(30), width=520)[1]
        self.assertEqual([(s.book_id, s.tilt, s.lying) for s in first],
                         [(s.book_id, s.tilt, s.lying) for s in second])

    def test_눕힌_책은_가로로_길다(self):
        _, slots = shelf.layout(books(60), width=520)
        for slot in slots:
            if slot.lying:
                self.assertGreater(slot.width, slot.height)
            else:
                self.assertLess(slot.width, slot.height)

    def test_책등_템플릿_번호가_범위_안에_있다(self):
        rows = [FakeBook(f'b{i}', f'책 {i}', spine_style=i * 7) for i in range(20)]
        _, slots = shelf.layout(rows, width=520)
        for slot in slots:
            self.assertIn(slot.template, range(shelf.SPINE_TEMPLATES))

    def test_아주_좁은_창에서도_배치된다(self):
        shelves, slots = shelf.layout(books(5), width=40)
        self.assertEqual(len(slots), 5)
        self.assertGreaterEqual(len(shelves), 1)

    def test_클릭_판정(self):
        _, slots = shelf.layout(books(10), width=520)
        target = slots[4]
        hit = shelf.slot_at(slots, target.x + 2, target.y + 5)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.book_id, target.book_id)
        self.assertIsNone(shelf.slot_at(slots, 2, 2))
        self.assertIsNone(shelf.slot_at(slots, 5000, 5000))


class CoverTint(unittest.TestCase):
    """책등 색은 표지에서 뽑는다. 정확한 대표색보다 **읽히는 밝기**가 중요하다."""

    def setUp(self) -> None:
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            self.skipTest('Pillow 없음')
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _cover(self, rgb, name='c.png') -> Path:
        from PIL import Image, ImageDraw
        path = self.tmp / name
        image = Image.new('RGB', (200, 300), rgb)
        ImageDraw.Draw(image).rectangle([20, 20, 180, 80], fill=(250, 250, 250))
        image.save(path)
        return path

    def test_색을_뽑는다(self):
        from readingsnail.services.covers import dominant_color
        self.assertRegex(dominant_color(self._cover((180, 60, 60))), r'^#[0-9A-F]{6}$')

    def test_너무_밝거나_어두운_표지도_읽히는_색이_나온다(self):
        from readingsnail.services.covers import dominant_color
        from readingsnail.theme import relative_luminance
        for rgb, label in (((250, 250, 248), '거의 흰 표지'),
                           ((10, 10, 12), '검정 표지')):
            color = dominant_color(self._cover(rgb, f'{label}.png'))
            self.assertIsNotNone(color, label)
            lum = relative_luminance(color)
            self.assertGreater(lum, 0.02, label)
            self.assertLess(lum, 0.6, label)

    def test_이미지가_아니면_None(self):
        (self.tmp / 'bad.png').write_bytes(b'not a png')
        from readingsnail.services.covers import dominant_color
        self.assertIsNone(dominant_color(self.tmp / 'bad.png'))
        self.assertIsNone(dominant_color(self.tmp / '없음.png'))

    def test_표지를_붙이면_책등_색도_정해진다(self):
        import io

        from readingsnail.services.covers import attach_cover
        from readingsnail.storage.db import Database
        from readingsnail.storage.journal import Journal

        png = self._cover((180, 60, 60)).read_bytes()

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.close()
                return False

        db = Database(':memory:')
        try:
            journal = Journal(db)
            book = journal.add_book('월든')
            attach_cover(journal, book.book_id, 'https://images.example.org/c.png',
                         self.tmp, opener=lambda r, timeout=None: Response(png))
            stored = journal.get_book(book.book_id)
            self.assertIsNotNone(stored.cover_path)
            self.assertIsNotNone(stored.spine_tint)
            self.assertRegex(stored.spine_tint, r'^#[0-9A-F]{6}$')
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
