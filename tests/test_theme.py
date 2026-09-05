"""6-a — 폰트·색 정비.

색은 순수 데이터라 tkinter 없이 검사할 수 있다. 대비는 눈으로 보면 놓친다.
이전 팔레트는 이끼색 버튼 위 흰 글자가 **2.25** 였다 — 거의 안 읽힌다.
그런 게 다시 들어오지 못하게 여기서 막는다.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from readingsnail import theme                                      # noqa: E402

AA_TEXT = 4.5        # 본문 크기 글자
AA_LARGE = 3.0       # 큰 글자·비텍스트 요소

# (용도, 앞색, 뒷색, 요구 대비)
PAIRS = (
    ('본문 글자',            'ink',        'paper',      AA_TEXT),
    ('본문 글자(눌린 영역)',  'ink',        'paper_deep', AA_TEXT),
    ('보조 글자',            'ink_soft',   'paper',      AA_TEXT),
    ('보조 글자(눌린 영역)',  'ink_soft',   'paper_deep', AA_TEXT),
    ('이끼 글자',            'moss_text',  'paper',      AA_TEXT),
    ('이끼 버튼 위 글자',     'on_accent',  'moss_deep',  AA_TEXT),
    ('껍데기 글자',          'shell_text', 'paper',      AA_TEXT),
    ('경고 글자',            'berry',      'paper',      AA_TEXT),
    ('경고 버튼 위 글자',     'on_accent',  'berry',      AA_TEXT),
    ('경고 영역 위 글자',     'ink',        'berry_soft', AA_TEXT),
    ('테두리',              'border',     'paper',      AA_LARGE),
)

# 채우기 전용 — 글자로 쓰면 안 되는 색. 이름으로 구분되게 두었다.
FILL_ONLY = ('moss', 'shell', 'berry_soft', 'line', 'shelf_wood', 'paper_deep')


class Contrast(unittest.TestCase):
    def test_모든_글자_조합이_기준을_넘는다(self):
        for label, fg, bg, need in PAIRS:
            with self.subTest(label):
                got = theme.contrast(theme.PALETTE[fg], theme.PALETTE[bg])
                self.assertGreaterEqual(
                    round(got, 2), need,
                    f'{label}: {theme.PALETTE[fg]} on {theme.PALETTE[bg]} = {got:.2f}')

    def test_대비_계산이_맞는다(self):
        self.assertAlmostEqual(theme.contrast('#000000', '#FFFFFF'), 21.0, places=1)
        self.assertAlmostEqual(theme.contrast('#FFFFFF', '#FFFFFF'), 1.0, places=3)
        # 순서를 바꿔도 같다
        self.assertAlmostEqual(theme.contrast('#3A3330', '#FBF7F0'),
                               theme.contrast('#FBF7F0', '#3A3330'), places=6)

    def test_잘못된_색은_거부한다(self):
        for bad in ('#FFF', 'red', '', '#GGGGGG'):
            with self.assertRaises(ValueError, msg=bad):
                theme.relative_luminance(bad)

    def test_채우기_전용_색은_글자로_쓰기에_부족하다(self):
        """이름으로 구분해 둔 이유가 이것이다. 헷갈려 쓰면 안 읽힌다."""
        for name in FILL_ONLY:
            if name == 'paper_deep':
                continue                      # 이건 바탕색이다
            got = theme.contrast(theme.PALETTE[name], theme.PALETTE['paper'])
            self.assertLess(got, AA_TEXT,
                            f'{name} 이 글자로 써도 될 만큼 진해졌다면 이름을 바꿀 것')

    def test_모든_색이_여섯_자리_16진(self):
        for name, value in theme.PALETTE.items():
            self.assertRegex(value, r'^#[0-9A-F]{6}$', name)


class FontRoles(unittest.TestCase):
    def test_역할마다_크기가_있다(self):
        for role in ('title', 'heading', 'subheading', 'body', 'small',
                     'caption', 'bubble', 'quote', 'mono'):
            self.assertIn(role, theme._SIZES)

    def test_제목_계열이_본문보다_크다(self):
        self.assertGreater(theme._SIZES['title'], theme._SIZES['body'])
        self.assertGreater(theme._SIZES['quote'], theme._SIZES['body'])
        self.assertLess(theme._SIZES['caption'], theme._SIZES['body'])

    def test_스택_맨_뒤는_어디에나_있는_폰트다(self):
        """전부 없으면 Tk 기본값으로 내려가지만, 그 전에 시스템 한글 폰트를 본다."""
        self.assertIn('Malgun Gothic', theme.DISPLAY_STACK)
        self.assertIn('Malgun Gothic', theme.BODY_STACK)

    def test_동봉_폰트_목록과_스택이_어긋나지_않는다(self):
        for filename in theme.BUNDLED_FONTS:
            family = filename.split('-')[0].replace('.ttf', '')
            family = family.rstrip('RB') if family.startswith('NanumSquare') else family
            self.assertTrue(
                any(family in name.replace(' ', '') for name in
                    theme.DISPLAY_STACK + theme.BODY_STACK),
                f'{filename} 은 어느 스택에도 없다')


class BundledFonts(unittest.TestCase):
    def test_없는_폴더에도_터지지_않는다(self):
        self.assertEqual(theme.load_bundled_fonts(ROOT / '없는폴더'), ())

    def test_Windows가_아니면_아무것도_안_한다(self):
        self.assertEqual(theme.load_bundled_fonts(ROOT), ())

    def test_라이선스_안내가_저장소에_있다(self):
        """OFL 은 전문 동봉을 요구한다. 잊으면 위반이다."""
        readme = ROOT / 'resources' / 'fonts' / 'README.txt'
        self.assertTrue(readme.is_file())
        text = readme.read_text(encoding='utf-8')
        self.assertIn('SIL Open Font License 1.1', text)
        self.assertIn('전문', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
