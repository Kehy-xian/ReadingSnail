"""5단계 — 스프라이트 규약·합성·검증.

원화는 없다. 자리표시 팩(tools/render_placeholder_pack.py)으로 파이프라인을 시험한다.
Pillow 가 없으면 합성 시험은 건너뛰되, 규약 자체는 언제나 검사한다.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))

from readingsnail.pet import art                                    # noqa: E402
from readingsnail.pet.sprites import frame_index, pillow_available  # noqa: E402

HAS_PIL = pillow_available()


class Contract(unittest.TestCase):
    """규약은 그림이 없어도 검사할 수 있다."""

    def test_가이드의_장수와_일치한다(self):
        # docs/SPRITE_GUIDE_KO.md — 필수 6종 66장, 전부 하면 93장
        self.assertEqual(sum(art.ANIMATIONS[s].frames for s in art.REQUIRED_STATES), 66)
        self.assertEqual(sum(a.frames for a in art.ANIMATIONS.values()), 93)

    def test_필수_상태는_여섯_종(self):
        self.assertEqual(set(art.REQUIRED_STATES),
                         {'idle', 'walk', 'talk', 'spit_memory', 'eat', 'shelve'})

    def test_돌보기_상태가_없다(self):
        for gone in ('snack', 'delicious', 'play', 'wash'):
            self.assertNotIn(gone, art.STATES)

    def test_파일_이름_규칙(self):
        self.assertEqual(art.frame_name('idle', 0), 'snail_idle_00.png')
        self.assertEqual(art.frame_name('walk', 11), 'snail_walk_11.png')
        self.assertEqual(art.frame_name('walk', 3, body_only=True), 'snail_body_walk_03.png')
        self.assertEqual(art.prop_name('leaf'), 'prop_leaf.png')

    def test_대문자는_소문자로_맞춘다(self):
        self.assertEqual(art.check_slug('Snail'), 'snail')
        self.assertEqual(art.check_slug('  SNAIL  '), 'snail')

    def test_이상한_이름은_거부한다(self):
        for bad in ('', '달팽이', 'snail pack', 'snail/../x', 'snail.png'):
            with self.assertRaises(ValueError, msg=bad):
                art.check_slug(bad)
        with self.assertRaises(ValueError):
            art.frame_name('없는상태', 0)
        with self.assertRaises(ValueError):
            art.frame_name('idle', -1)

    def test_프레임이_하나라도_없으면_그_상태는_안_쓴다(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for path in art.frame_paths(folder, 'idle')[:-1]:
                path.write_bytes(b'x')
            self.assertFalse(art.has_full_animation(folder, 'idle'))
            self.assertNotIn('idle', art.available_states(folder))
            art.frame_paths(folder, 'idle')[-1].write_bytes(b'x')
            self.assertTrue(art.has_full_animation(folder, 'idle'))

    def test_분리_방식은_껍데기가_있어야_성립한다(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for path in art.frame_paths(folder, 'idle', body_only=True):
                path.write_bytes(b'x')
            self.assertFalse(art.has_layered_animation(folder, 'idle'))
            art.shell_path(folder).write_bytes(b'x')
            self.assertTrue(art.has_layered_animation(folder, 'idle'))


class Timing(unittest.TestCase):
    def test_반복하는_상태는_되감는다(self):
        spec = art.ANIMATIONS['idle']
        self.assertEqual(frame_index('idle', 0), 0)
        self.assertEqual(frame_index('idle', spec.frame_ms), 1)
        self.assertEqual(frame_index('idle', spec.frame_ms * spec.frames), 0)

    def test_반복하지_않는_상태는_마지막에_멈춘다(self):
        spec = art.ANIMATIONS['eat']
        self.assertFalse(spec.loop)
        self.assertEqual(frame_index('eat', spec.frame_ms * 999), spec.frames - 1)

    def test_알_수_없는_상태와_음수(self):
        self.assertEqual(frame_index('없는상태', 500), 0)
        self.assertEqual(frame_index('idle', -100), 0)


@unittest.skipUnless(HAS_PIL, 'Pillow 없음')
class Composition(unittest.TestCase):
    """몸통 → 껍데기 → 소품 순으로 쌓인다."""

    @classmethod
    def setUpClass(cls) -> None:
        import render_placeholder_pack as renderer
        cls._tmp = TemporaryDirectory()
        cls.pack = Path(cls._tmp.name) / 'sprites'
        cls.props = Path(cls._tmp.name) / 'props'
        renderer.main([str(cls.pack), '--props', str(cls.props),
                       '--states', 'idle,walk', '--quiet'])

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_자리표시_팩이_규격을_지킨다(self):
        from readingsnail.pet.validation import validate_pack
        issues = validate_pack(self.pack, states=('idle', 'walk'), require=True)
        self.assertEqual([str(i) for i in issues], [])

    def test_분리_레이어를_합성한다(self):
        from readingsnail.pet.sprites import compose_frame
        image = compose_frame(self.pack, 'idle', 0)
        self.assertEqual(image.size, (art.CANVAS, art.CANVAS))
        self.assertEqual(image.mode, 'RGBA')

    def test_소품이_위에_얹힌다(self):
        from readingsnail.pet.sprites import compose_frame
        plain = compose_frame(self.pack, 'idle', 0)
        with_prop = compose_frame(self.pack, 'idle', 0, props=('leaf',),
                                  prop_root=self.props)
        self.assertNotEqual(plain.tobytes(), with_prop.tobytes())
        # 소품이 붙어도 캔버스는 그대로다
        self.assertEqual(with_prop.size, plain.size)

    def test_없는_소품은_그냥_안_그린다(self):
        from readingsnail.pet.sprites import compose_frame
        plain = compose_frame(self.pack, 'idle', 0)
        missing = compose_frame(self.pack, 'idle', 0, props=('nosuchprop',),
                                prop_root=self.props)
        self.assertEqual(plain.tobytes(), missing.tobytes())

    def test_이상한_소품_이름에도_그리기가_멈추지_않는다(self):
        """소품 이름은 설정에서 온다. 설정 한 줄이 달팽이를 지우면 안 된다."""
        from readingsnail.pet.sprites import compose_frame
        plain = compose_frame(self.pack, 'idle', 0)
        for bad in ('달팽이', '', '../../etc/passwd', 'a b'):
            drawn = compose_frame(self.pack, 'idle', 0, props=(bad,),
                                  prop_root=self.props)
            self.assertEqual(plain.tobytes(), drawn.tobytes(), bad)

    def test_프레임이_없으면_알려준다(self):
        from readingsnail.pet.sprites import compose_frame
        with self.assertRaises(FileNotFoundError):
            compose_frame(self.pack, 'eat', 0)

    def test_좌우_반전(self):
        from PIL import Image
        from readingsnail.pet.sprites import _prepare
        left = _prepare(Image.new('RGBA', (190, 190)), facing=-1, size=190)
        source = Image.new('RGBA', (190, 190), (0, 0, 0, 0))
        source.putpixel((10, 95), (255, 0, 0, 255))
        right = _prepare(source, facing=1, size=190)
        self.assertEqual(right.getpixel((179, 95))[:3], (255, 0, 0))
        self.assertEqual(left.size, (190, 190))

    def test_크기를_줄여도_정사각형(self):
        from PIL import Image
        from readingsnail.pet.sprites import _prepare
        small = _prepare(Image.new('RGBA', (190, 190)), facing=-1, size=95)
        self.assertEqual(small.size, (95, 95))


@unittest.skipUnless(HAS_PIL, 'Pillow 없음')
class Validation(unittest.TestCase):
    """규격이 어긋난 그림은 앱에서 조용히 이상해진다. 받는 자리에서 걸러낸다."""

    def setUp(self) -> None:
        import render_placeholder_pack as renderer
        self._tmp = TemporaryDirectory()
        self.pack = Path(self._tmp.name) / 'sprites'
        renderer.main([str(self.pack), '--props', str(Path(self._tmp.name) / 'props'),
                       '--states', 'idle', '--quiet'])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _codes(self, **kw):
        from readingsnail.pet.validation import validate_pack
        return {i.code for i in validate_pack(self.pack, states=('idle',), **kw)}

    def test_깨끗한_팩은_통과(self):
        self.assertEqual(self._codes(require=True), set())

    def test_크기가_다르면_잡는다(self):
        from PIL import Image
        Image.new('RGBA', (120, 120)).save(
            self.pack / art.frame_name('idle', 0, body_only=True))
        self.assertIn('SIZE', self._codes())

    def test_배경이_불투명하면_잡는다(self):
        from PIL import Image
        Image.new('RGBA', (190, 190), (255, 255, 255, 255)).save(
            self.pack / art.frame_name('idle', 1, body_only=True))
        self.assertIn('NO_TRANSPARENCY', self._codes())

    def test_반투명_범벅이면_잡는다(self):
        from PIL import Image
        Image.new('RGBA', (190, 190), (140, 176, 138, 120)).save(
            self.pack / art.frame_name('idle', 2, body_only=True))
        self.assertIn('SOFT_EDGES', self._codes())

    def test_바닥선이_흔들리면_잡는다(self):
        from PIL import Image, ImageDraw
        image = Image.new('RGBA', (190, 190), (0, 0, 0, 0))
        ImageDraw.Draw(image).ellipse([40, 20, 150, 60], fill=(0, 0, 0, 255))
        image.save(self.pack / art.frame_name('idle', 3, body_only=True))
        self.assertIn('BASELINE_DRIFT', self._codes())

    def test_프레임이_빠지면_잡는다(self):
        (self.pack / art.frame_name('idle', 4, body_only=True)).unlink()
        self.assertIn('INCOMPLETE', self._codes(require=True))

    def test_읽을_수_없는_파일(self):
        (self.pack / art.frame_name('idle', 5, body_only=True)).write_bytes(b'not a png')
        self.assertIn('UNREADABLE', self._codes())

    def test_폴더가_없으면(self):
        from readingsnail.pet.validation import validate_pack
        issues = validate_pack(Path(self._tmp.name) / '없음')
        self.assertEqual([i.code for i in issues], ['NO_PACK'])


@unittest.skipUnless(HAS_PIL, 'Pillow 없음')
class Install(unittest.TestCase):
    """원화는 설치본이 아니라 데이터 폴더에 둔다 — 업데이트가 지우지 않게."""

    def setUp(self) -> None:
        import render_placeholder_pack as renderer
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.pack = self.root / 'art'
        renderer.main([str(self.pack), '--props', str(self.root / 'props'),
                       '--states', 'idle,walk', '--quiet'])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_갖춰진_상태만_옮긴다(self):
        import install_sprite_pack as installer
        target = self.root / 'overrides'
        moved = installer.install(self.pack, target, ('idle', 'walk', 'eat'))
        self.assertTrue(moved)
        self.assertIn('idle', art.available_states(target))
        self.assertIn('walk', art.available_states(target))
        self.assertNotIn('eat', art.available_states(target))

    def test_절반짜리_설치가_남지_않는다(self):
        import install_sprite_pack as installer
        target = self.root / 'overrides2'
        installer.install(self.pack, target, ('idle',))
        leftovers = [p for p in target.iterdir() if p.is_dir()]
        self.assertEqual(leftovers, [], '임시 폴더가 남았다')

    def test_규격_위반은_설치를_막는다(self):
        import install_sprite_pack as installer
        from PIL import Image
        Image.new('RGBA', (64, 64)).save(self.pack / art.frame_name('idle', 0, body_only=True))
        code = installer.main([str(self.pack), '--target', str(self.root / 'blocked'),
                               '--states', 'idle'])
        self.assertEqual(code, 1)
        self.assertFalse((self.root / 'blocked').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)


@unittest.skipUnless(HAS_PIL, 'Pillow 없음')
class MalformedArt(unittest.TestCase):
    """잘못 만든 팩 하나가 앱을 메모리로 눌러서는 안 된다."""

    def setUp(self) -> None:
        import render_placeholder_pack as renderer
        self._tmp = TemporaryDirectory()
        self.pack = Path(self._tmp.name) / 'sprites'
        self.props = Path(self._tmp.name) / 'props'
        renderer.main([str(self.pack), '--props', str(self.props), '--states', 'idle', '--quiet'])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_지나치게_큰_그림은_거부한다(self):
        from PIL import Image

        from readingsnail.pet.sprites import MAX_SOURCE_SIDE, compose_frame
        side = MAX_SOURCE_SIDE + 10
        Image.new('RGBA', (side, side)).save(
            self.pack / art.frame_name('idle', 0, body_only=True))
        with self.assertRaises(ValueError):
            compose_frame(self.pack, 'idle', 0)

    def test_2배_원화는_받아준다(self):
        """규격은 190 이지만 크게 그려 온 원화를 무조건 막지는 않는다."""
        from PIL import Image

        from readingsnail.pet.sprites import compose_frame
        Image.new('RGBA', (380, 380)).save(
            self.pack / art.frame_name('idle', 0, body_only=True))
        image = compose_frame(self.pack, 'idle', 0)
        self.assertEqual(image.size, (380, 380))

    def test_거대한_소품은_그리지_않고_넘어간다(self):
        from PIL import Image

        from readingsnail.pet.sprites import MAX_SOURCE_SIDE, compose_frame
        side = MAX_SOURCE_SIDE + 10
        Image.new('RGBA', (side, side), (255, 0, 0, 255)).save(
            art.prop_path(self.props, 'huge'))
        plain = compose_frame(self.pack, 'idle', 0)
        drawn = compose_frame(self.pack, 'idle', 0, props=('huge',), prop_root=self.props)
        self.assertEqual(plain.tobytes(), drawn.tobytes())

    def test_알파가_없는_그림도_합성은_된다(self):
        """검증기가 경고하되, 그리기가 멈추지는 않는다."""
        from PIL import Image

        from readingsnail.pet.sprites import compose_frame
        from readingsnail.pet.validation import validate_pack
        for mode in ('RGB', 'P', 'L'):
            Image.new(mode, (190, 190)).save(
                self.pack / art.frame_name('idle', 0, body_only=True))
            image = compose_frame(self.pack, 'idle', 0)
            self.assertEqual(image.mode, 'RGBA')
            codes = {i.code for i in validate_pack(self.pack, states=('idle',))}
            self.assertIn('NO_TRANSPARENCY', codes, mode)

    def test_0바이트_파일은_적재에서_걸러진다(self):
        from readingsnail.pet.validation import validate_pack
        (self.pack / art.frame_name('idle', 1, body_only=True)).write_bytes(b'')
        codes = {i.code for i in validate_pack(self.pack, states=('idle',))}
        self.assertIn('UNREADABLE', codes)
