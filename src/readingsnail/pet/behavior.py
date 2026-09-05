"""달팽이의 이동·상태 결정. tkinter 가 전혀 들어오지 않는다.

창을 띄우지 않고도 이동을 통째로 검증할 수 있게 순수 함수로 둔다.
전작 pet_behavior.py 의 태도를 그대로 가져왔다.

전작에서 바꾼 것
    1. **8방향으로 움직인다.** 전작 choose_walk_target 은 목표 y 를 항상 바닥(max_y)
       으로 고정해서 사실상 좌우로만 걸었다. 여기서는 작업 영역 안 아무 곳이나
       목표가 된다.
    2. **수직 속도가 수평의 절반이다.** 같은 속도로 위아래로 가면 기어오르는 게
       아니라 나는 것으로 보인다.
    3. **bond(친밀도)를 뺐다.** 성장 스탯이다. 말수는 기록이 정하지 캐릭터 육성이
       정하지 않는다(CLAUDE.md).
    4. 간식·씻기·놀기 상태를 뺐다. 돌보기 기능이 없다.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

# 평소 상태. 계획기가 자유롭게 바꾼다.
AMBIENT_STATES = ('idle', 'walk', 'read', 'sleep', 'talk', 'bump')

# 연출 중인 상태. 끝날 때까지 계획기가 건드리지 않는다.
INTERRUPT_STATES = ('eat', 'shelve', 'spit_memory', 'drop', 'tuck')

# 수직 속도 배율. 1.0 이면 날아다니는 것처럼 보인다.
VERTICAL_RATIO = 0.5

# 드래그해서 놓았을 때 낙하 가속(픽셀/틱^2)과 최대 속도.
GRAVITY = 3
MAX_FALL_SPEED = 42


@dataclass(frozen=True)
class WorkArea:
    """달팽이가 돌아다닐 수 있는 화면 영역. 작업 표시줄은 빼고 넘긴다."""

    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError('작업 영역이 뒤집혔다')


@dataclass(frozen=True)
class PetMotion:
    x: int
    y: int
    state: str = 'idle'
    target_x: int | None = None
    target_y: int | None = None
    facing: int = -1          # -1 왼쪽(원화 방향), 1 오른쪽(좌우 반전)
    hold_ticks: int = 0
    fall_speed: int = 0


class RoamPlanner:
    """돌아다님을 결정한다. rng 를 넣으면 결과가 결정적이라 시험할 수 있다."""

    def __init__(
        self,
        *,
        rng: random.Random | None = None,
        step_px: int = 5,
        window_width: int = 190,
        window_height: int = 190,
        margin: int = 8,
        vertical_ratio: float = VERTICAL_RATIO,
    ) -> None:
        self.rng = rng or random.Random()
        self.step_px = max(1, int(step_px))
        self.window_width = max(1, int(window_width))
        self.window_height = max(1, int(window_height))
        self.margin = max(0, int(margin))
        self.vertical_ratio = max(0.05, min(1.0, float(vertical_ratio)))

    # ── 경계 ──────────────────────────────────────────
    def bounds(self, area: WorkArea) -> tuple[int, int, int, int]:
        """(min_x, max_x, min_y, max_y). 창 왼쪽 위 좌표가 들어갈 수 있는 범위."""
        min_x = area.left + self.margin
        max_x = max(min_x, area.right - self.window_width - self.margin)
        min_y = area.top + self.margin
        max_y = max(min_y, area.bottom - self.window_height - self.margin)
        return min_x, max_x, min_y, max_y

    def clamp(self, x: int, y: int, area: WorkArea) -> tuple[int, int]:
        min_x, max_x, min_y, max_y = self.bounds(area)
        return max(min_x, min(max_x, int(x))), max(min_y, min(max_y, int(y)))

    def floor_y(self, area: WorkArea) -> int:
        return self.bounds(area)[3]

    def on_edge(self, x: int, y: int, area: WorkArea) -> bool:
        min_x, max_x, min_y, max_y = self.bounds(area)
        return x in (min_x, max_x) or y in (min_y, max_y)

    # ── 계획 ──────────────────────────────────────────
    def choose_walk_target(self, motion: PetMotion, area: WorkArea) -> PetMotion:
        """8방향 어디로든 목표를 잡는다. 가끔 가장자리를 골라 부딪는 연출을 만든다."""
        min_x, max_x, min_y, max_y = self.bounds(area)
        if self.rng.random() < 0.16:
            tx = self.rng.choice((min_x, max_x))
            ty = self.rng.randint(min_y, max_y)
        elif self.rng.random() < 0.12:
            tx = self.rng.randint(min_x, max_x)
            ty = self.rng.choice((min_y, max_y))
        else:
            tx = self.rng.randint(min_x, max_x)
            ty = self.rng.randint(min_y, max_y)
        return replace(
            motion, state='walk', target_x=tx, target_y=ty,
            facing=self._facing(tx - motion.x, motion.facing), hold_ticks=0,
        )

    def choose_ambient_pause(self, motion: PetMotion) -> PetMotion:
        """멈춰 서서 하는 것들. 재촉하지 않는 캐릭터라 대부분 가만히 있는다."""
        state = self.rng.choices(
            population=('idle', 'read', 'sleep', 'talk'),
            weights=(48, 18, 11, 9), k=1,
        )[0]
        hold = {
            'idle': self.rng.randint(7, 20),
            'read': self.rng.randint(16, 34),
            'sleep': self.rng.randint(24, 48),
            'talk': self.rng.randint(8, 18),
        }[state]
        return replace(motion, state=state, target_x=None, target_y=None, hold_ticks=hold)

    @staticmethod
    def _facing(dx: float, current: int) -> int:
        """좌우 반전만 쓴다. 정면·후면 프레임이 없으므로 수직 이동은 방향을 유지한다."""
        if dx < 0:
            return -1
        if dx > 0:
            return 1
        return current

    # ── 진행 ──────────────────────────────────────────
    def tick(self, motion: PetMotion, area: WorkArea, *, blocked: bool = False) -> PetMotion:
        """한 틱. blocked 는 사용자가 창을 붙잡고 있는 등 움직이면 안 되는 상황."""
        x, y = self.clamp(motion.x, motion.y, area)
        motion = replace(motion, x=x, y=y)

        # blocked 를 먼저 본다. 낙하 판정이 앞에 있으면 사용자가 떨어지는 달팽이를
        # 붙잡아도 손 안에서 계속 떨어진다.
        if blocked:
            return motion
        if motion.state == 'drop':
            return self._fall(motion, area)
        if motion.state in INTERRUPT_STATES:
            return motion
        if motion.state == 'walk' and motion.target_x is not None and motion.target_y is not None:
            return self._walk(motion, area)
        if motion.hold_ticks > 0:
            return replace(motion, hold_ticks=motion.hold_ticks - 1)
        # 멈춤이 끝나면 대개 다시 걷는다.
        if self.rng.random() < 0.82:
            return self.choose_walk_target(motion, area)
        return self.choose_ambient_pause(motion)

    def _walk(self, motion: PetMotion, area: WorkArea) -> PetMotion:
        dx = motion.target_x - motion.x
        dy = motion.target_y - motion.y
        dist = math.hypot(dx, dy)
        if dist == 0:
            return self._arrive(motion, area)

        # 수직만 느리게 한다. 방향은 그대로 두고 y 성분에만 배율을 건다.
        move_x = self.step_px * (dx / dist)
        move_y = self.step_px * self.vertical_ratio * (dy / dist)
        if abs(move_x) >= abs(dx) and abs(move_y) >= abs(dy):
            return self._arrive(replace(motion, x=motion.target_x, y=motion.target_y), area)

        nx, ny = self.clamp(
            int(round(motion.x + move_x)), int(round(motion.y + move_y)), area)
        if (nx, ny) == (motion.x, motion.y):
            # 경계에 눌려 한 발도 못 나간다. 목표를 붙잡고 있으면 영원히 제자리다.
            return self._arrive(motion, area)
        return replace(motion, x=nx, y=ny, facing=self._facing(dx, motion.facing))

    def _arrive(self, motion: PetMotion, area: WorkArea) -> PetMotion:
        arrived = replace(motion, target_x=None, target_y=None)
        if self.on_edge(arrived.x, arrived.y, area):
            return replace(arrived, state='bump', hold_ticks=7)
        return self.choose_ambient_pause(arrived)

    # ── 드래그와 낙하 ─────────────────────────────────
    def grab(self, motion: PetMotion) -> PetMotion:
        """사용자가 집어 들었다. 진행 중이던 목표를 버린다."""
        return replace(motion, state='idle', target_x=None, target_y=None,
                       hold_ticks=0, fall_speed=0)

    def release(self, motion: PetMotion, area: WorkArea) -> PetMotion:
        """놓았다. 바닥이면 그대로 서고, 공중이면 떨어진다."""
        x, y = self.clamp(motion.x, motion.y, area)
        if y >= self.floor_y(area):
            return replace(motion, x=x, y=y, state='idle', hold_ticks=6, fall_speed=0)
        return replace(motion, x=x, y=y, state='drop', target_x=None, target_y=None,
                       hold_ticks=0, fall_speed=0)

    def _fall(self, motion: PetMotion, area: WorkArea) -> PetMotion:
        floor = self.floor_y(area)
        if motion.y >= floor:
            return replace(motion, y=floor, state='bump', hold_ticks=5, fall_speed=0)
        speed = min(MAX_FALL_SPEED, motion.fall_speed + GRAVITY)
        ny = motion.y + speed
        if ny >= floor:
            return replace(motion, y=floor, state='bump', hold_ticks=5, fall_speed=0)
        return replace(motion, y=ny, fall_speed=speed)
