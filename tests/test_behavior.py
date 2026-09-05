"""달팽이 이동. 창을 띄우지 않고 검증한다.

SPEC 4항이 요구하는 것
  · 8방향 자유 이동
  · 수직 속도는 수평의 약 절반
  · 정면·후면 프레임 없음 → 좌향 + 좌우 반전만
  · 화면 끝 충돌, 드래그 후 낙하
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from readingsnail.pet.behavior import (                        # noqa: E402
    INTERRUPT_STATES, VERTICAL_RATIO, PetMotion, RoamPlanner, WorkArea)

AREA = WorkArea(left=0, top=0, right=1920, bottom=1040)


def planner(seed: int = 7, **kw) -> RoamPlanner:
    return RoamPlanner(rng=random.Random(seed), **kw)


class Bounds(unittest.TestCase):
    def test_작업_영역이_뒤집히면_거부한다(self):
        for bad in ((10, 0, 10, 100), (0, 10, 100, 10), (100, 0, 0, 100)):
            with self.assertRaises(ValueError):
                WorkArea(*bad)

    def test_창_크기와_여백만큼_안쪽으로_제한된다(self):
        p = planner(window_width=190, window_height=190, margin=8)
        self.assertEqual(p.bounds(AREA), (8, 1920 - 190 - 8, 8, 1040 - 190 - 8))

    def test_밖으로_나간_좌표는_끌어들인다(self):
        p = planner()
        self.assertEqual(p.clamp(-500, -500, AREA), (8, 8))
        self.assertEqual(p.clamp(99999, 99999, AREA), (1722, 842))

    def test_영역이_창보다_작아도_터지지_않는다(self):
        tiny = WorkArea(0, 0, 100, 100)
        p = planner(window_width=190, window_height=190)
        min_x, max_x, min_y, max_y = p.bounds(tiny)
        self.assertLessEqual(min_x, max_x)
        self.assertLessEqual(min_y, max_y)
        self.assertEqual(p.clamp(50, 50, tiny), (8, 8))


class EightWay(unittest.TestCase):
    def test_수직으로도_움직인다(self):
        """전작은 목표 y 를 항상 바닥으로 고정해 좌우로만 걸었다."""
        p = planner()
        m = PetMotion(x=800, y=400)
        ys = set()
        for _ in range(4000):
            m = p.tick(m, AREA)
            ys.add(m.y)
        self.assertGreater(len(ys), 50, '수직 위치가 거의 변하지 않는다')

    def test_네_사분면을_모두_돌아다닌다(self):
        p = planner()
        m = PetMotion(x=800, y=400)
        seen = set()
        for _ in range(6000):
            m = p.tick(m, AREA)
            seen.add((m.x < 865, m.y < 425))
        self.assertEqual(len(seen), 4, f'가보지 못한 사분면이 있다: {seen}')

    def test_수직_속도가_수평의_절반이다(self):
        p = planner(step_px=10)
        # 정확히 위로만
        up = p._walk(PetMotion(x=800, y=400, state='walk', target_x=800, target_y=100), AREA)
        self.assertEqual(400 - up.y, round(10 * VERTICAL_RATIO))
        # 정확히 오른쪽으로만
        right = p._walk(PetMotion(x=800, y=400, state='walk', target_x=1200, target_y=400), AREA)
        self.assertEqual(right.x - 800, 10)

    def test_대각선에서도_수직이_더_느리다(self):
        p = planner(step_px=10)
        m = p._walk(PetMotion(x=800, y=400, state='walk', target_x=1200, target_y=800), AREA)
        self.assertGreater(m.x - 800, m.y - 400)

    def test_목표에_결국_도착한다(self):
        p = planner(step_px=5)
        m = PetMotion(x=100, y=800, state='walk', target_x=1500, target_y=100)
        for _ in range(2000):
            m = p.tick(m, AREA)
            if m.target_x is None:
                break
        self.assertIsNone(m.target_x, '목표에 도달하지 못했다')


class Facing(unittest.TestCase):
    def test_왼쪽으로_가면_좌향(self):
        p = planner(step_px=10)
        m = p._walk(PetMotion(x=800, y=400, facing=1, state='walk',
                              target_x=400, target_y=400), AREA)
        self.assertEqual(m.facing, -1)

    def test_오른쪽으로_가면_반전(self):
        p = planner(step_px=10)
        m = p._walk(PetMotion(x=800, y=400, facing=-1, state='walk',
                              target_x=1200, target_y=400), AREA)
        self.assertEqual(m.facing, 1)

    def test_수직_이동은_방향을_유지한다(self):
        """정면·후면 프레임이 없다. 위로 갈 때 방향을 바꾸면 홱 뒤집혀 보인다."""
        p = planner(step_px=10)
        for start in (-1, 1):
            m = p._walk(PetMotion(x=800, y=400, facing=start, state='walk',
                                  target_x=800, target_y=100), AREA)
            self.assertEqual(m.facing, start)

    def test_방향은_늘_둘_중_하나다(self):
        p = planner()
        m = PetMotion(x=800, y=400)
        for _ in range(3000):
            m = p.tick(m, AREA)
            self.assertIn(m.facing, (-1, 1))


class Collision(unittest.TestCase):
    def test_가장자리에_닿으면_부딪는다(self):
        p = planner(step_px=10)
        min_x, _, _, max_y = p.bounds(AREA)
        m = p._walk(PetMotion(x=min_x + 3, y=max_y, state='walk',
                              target_x=min_x, target_y=max_y), AREA)
        self.assertEqual(m.state, 'bump')

    def test_위쪽_가장자리에서도_부딪는다(self):
        p = planner(step_px=10)
        _, _, min_y, _ = p.bounds(AREA)
        m = p._walk(PetMotion(x=800, y=min_y + 2, state='walk',
                              target_x=800, target_y=min_y), AREA)
        self.assertEqual(m.state, 'bump')

    def test_영역_밖으로_절대_나가지_않는다(self):
        p = planner()
        min_x, max_x, min_y, max_y = p.bounds(AREA)
        m = PetMotion(x=800, y=400)
        for _ in range(8000):
            m = p.tick(m, AREA)
            self.assertTrue(min_x <= m.x <= max_x, f'x 이탈: {m.x}')
            self.assertTrue(min_y <= m.y <= max_y, f'y 이탈: {m.y}')

    def test_화면이_갑자기_작아져도_따라온다(self):
        """노트북 도킹 해제처럼 해상도가 줄면 달팽이가 화면 밖에 남는다."""
        p = planner()
        m = PetMotion(x=1700, y=800)
        small = WorkArea(0, 0, 1024, 768)
        m = p.tick(m, small)
        min_x, max_x, min_y, max_y = p.bounds(small)
        self.assertTrue(min_x <= m.x <= max_x and min_y <= m.y <= max_y)


class DragAndDrop(unittest.TestCase):
    def test_집으면_목표를_버린다(self):
        p = planner()
        m = p.grab(PetMotion(x=800, y=400, state='walk', target_x=100, target_y=100))
        self.assertIsNone(m.target_x)
        self.assertEqual(m.state, 'idle')

    def test_공중에서_놓으면_떨어진다(self):
        p = planner()
        m = p.release(PetMotion(x=800, y=100), AREA)
        self.assertEqual(m.state, 'drop')
        for _ in range(200):
            m = p.tick(m, AREA)
            if m.state != 'drop':
                break
        self.assertEqual(m.y, p.floor_y(AREA))
        self.assertEqual(m.state, 'bump')

    def test_낙하가_가속된다(self):
        p = planner()
        m = p.release(PetMotion(x=800, y=0), AREA)
        steps = []
        for _ in range(5):
            before = m.y
            m = p.tick(m, AREA)
            steps.append(m.y - before)
        self.assertEqual(steps, sorted(steps))
        self.assertGreater(steps[-1], steps[0])

    def test_바닥에서_놓으면_떨어지지_않는다(self):
        p = planner()
        m = p.release(PetMotion(x=800, y=p.floor_y(AREA)), AREA)
        self.assertEqual(m.state, 'idle')

    def test_붙잡고_있는_동안은_안_움직인다(self):
        p = planner()
        m = PetMotion(x=800, y=400, state='walk', target_x=100, target_y=100)
        for _ in range(50):
            m = p.tick(m, AREA, blocked=True)
        self.assertEqual((m.x, m.y), (800, 400))


class Interrupts(unittest.TestCase):
    def test_연출_중에는_계획기가_끼어들지_않는다(self):
        p = planner()
        for state in INTERRUPT_STATES:
            if state == 'drop':
                continue          # 낙하는 스스로 진행한다
            m = PetMotion(x=800, y=400, state=state)
            for _ in range(60):
                m = p.tick(m, AREA)
            self.assertEqual(m.state, state, f'{state} 중에 상태가 바뀌었다')

    def test_돌보기_상태가_없다(self):
        for gone in ('snack', 'delicious', 'play', 'wash'):
            self.assertNotIn(gone, INTERRUPT_STATES)

    def test_친밀도_개념이_없다(self):
        self.assertFalse(hasattr(RoamPlanner, 'set_bond'))
        self.assertFalse(hasattr(planner(), 'bond'))


class Determinism(unittest.TestCase):
    def test_같은_씨앗이면_같은_경로(self):
        def run(seed):
            p = planner(seed)
            m = PetMotion(x=800, y=400)
            return [(m := p.tick(m, AREA)).x for _ in range(300)]
        self.assertEqual(run(11), run(11))
        self.assertNotEqual(run(11), run(12))

    def test_오래_돌려도_멈추지_않는다(self):
        """어느 상태에서도 영원히 굳지 않아야 한다."""
        p = planner()
        m = PetMotion(x=800, y=400)
        positions = set()
        for _ in range(20_000):
            m = p.tick(m, AREA)
            positions.add((m.x, m.y))
        self.assertGreater(len(positions), 500)


if __name__ == '__main__':
    unittest.main(verbosity=2)


class BlockedWhileFalling(unittest.TestCase):
    """떨어지는 달팽이를 붙잡으면 손 안에서 계속 떨어지면 안 된다."""

    def test_붙잡으면_낙하도_멈춘다(self):
        p = planner()
        m = p.release(PetMotion(x=800, y=100), AREA)
        self.assertEqual(m.state, 'drop')
        for _ in range(20):
            m = p.tick(m, AREA, blocked=True)
        self.assertEqual(m.y, 100)

    def test_놓으면_다시_떨어진다(self):
        p = planner()
        m = p.release(PetMotion(x=800, y=100), AREA)
        for _ in range(5):
            m = p.tick(m, AREA, blocked=True)
        for _ in range(5):
            m = p.tick(m, AREA)
        self.assertGreater(m.y, 100)
