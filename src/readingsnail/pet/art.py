"""스프라이트 규약. **Pillow 도 tkinter 도 들어오지 않는다.**

파일 이름과 장수만 정하는 곳이라, 그림 없이도 규약을 검증할 수 있다.
규격 원문은 docs/SPRITE_GUIDE_KO.md 다.

두 가지 담는 법
    통짜   snail_walk_00.png … 프레임마다 완성된 그림
    분리   snail_body_walk_00.png … + snail_shell.png (고정 한 장)
           껍데기를 고정 레이어로 빼면 walk 12장에서 몸통만 그리면 된다.
           작업량이 절반 아래로 내려간다(SPRITE_GUIDE_KO.md).

**한 상태는 한 출처에서 통째로 온다.** 프레임 하나가 없으면 그 상태는 통짜로도
분리로도 쓰지 않고 벡터 폴백으로 간다. 절반만 불러오면 애니메이션이 튄다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CANVAS = 190          # 원화 캔버스 한 변. 스프라이트도 패널도 이 크기다.
SLUG = 'snail'

_SLUG_CHARS = set('abcdefghijklmnopqrstuvwxyz0123456789_-')


@dataclass(frozen=True)
class Animation:
    state: str
    frames: int
    frame_ms: int
    loop: bool = True
    required: bool = False        # 원화 작업에서 먼저 채워야 하는 것

    def __post_init__(self) -> None:
        if self.frames <= 0 or self.frame_ms <= 0:
            raise ValueError('프레임 수와 장당 시간은 양수여야 한다')


# docs/SPRITE_GUIDE_KO.md 의 표를 그대로 옮긴 것이다. 여기를 고치면 문서도 고칠 것.
ANIMATIONS: dict[str, Animation] = {
    'idle':        Animation('idle', 8, 200, True, required=True),
    'walk':        Animation('walk', 12, 90, True, required=True),
    'talk':        Animation('talk', 6, 130, True, required=True),
    'spit_memory': Animation('spit_memory', 10, 120, False, required=True),
    'eat':         Animation('eat', 18, 110, False, required=True),
    'shelve':      Animation('shelve', 12, 100, False, required=True),
    'read':        Animation('read', 6, 260, True),
    'sleep':       Animation('sleep', 6, 400, True),
    'tuck':        Animation('tuck', 6, 110, False),
    'bump':        Animation('bump', 5, 120, False),
    'drop':        Animation('drop', 4, 120, True),
}

STATES = tuple(ANIMATIONS)
REQUIRED_STATES = tuple(s for s, a in ANIMATIONS.items() if a.required)

SHELL_FILENAME = f'{SLUG}_shell.png'
PROP_PREFIX = 'prop_'


def check_slug(slug: str) -> str:
    value = str(slug or '').strip().lower()
    if not value or any(ch not in _SLUG_CHARS for ch in value):
        raise ValueError('slug 은 소문자 ASCII 여야 한다')
    return value


def frame_name(state: str, index: int, *, slug: str = SLUG, body_only: bool = False) -> str:
    slug = check_slug(slug)
    if state not in ANIMATIONS:
        raise ValueError(f'알 수 없는 상태: {state}')
    if index < 0:
        raise ValueError('프레임 번호는 음수가 될 수 없다')
    part = 'body_' if body_only else ''
    return f'{slug}_{part}{state}_{index:02d}.png'


def frame_paths(root: str | Path, state: str, *, slug: str = SLUG,
                body_only: bool = False) -> tuple[Path, ...]:
    folder = Path(root)
    count = ANIMATIONS[state].frames
    return tuple(folder / frame_name(state, i, slug=slug, body_only=body_only)
                 for i in range(count))


def shell_path(root: str | Path, *, slug: str = SLUG) -> Path:
    return Path(root) / f'{check_slug(slug)}_shell.png'


def has_full_animation(root: str | Path, state: str, *, slug: str = SLUG) -> bool:
    """통짜 프레임이 빠짐없이 있는가."""
    if state not in ANIMATIONS:
        return False
    return all(p.is_file() for p in frame_paths(root, state, slug=slug))


def has_layered_animation(root: str | Path, state: str, *, slug: str = SLUG) -> bool:
    """몸통 프레임 + 고정 껍데기가 빠짐없이 있는가."""
    if state not in ANIMATIONS:
        return False
    if not shell_path(root, slug=slug).is_file():
        return False
    return all(p.is_file() for p in frame_paths(root, state, slug=slug, body_only=True))


def available_states(root: str | Path, *, slug: str = SLUG) -> tuple[str, ...]:
    """이 폴더가 통째로 제공할 수 있는 상태들."""
    return tuple(s for s in STATES
                 if has_full_animation(root, s, slug=slug)
                 or has_layered_animation(root, s, slug=slug))


def prop_name(name: str) -> str:
    return f'{PROP_PREFIX}{check_slug(name)}.png'


def prop_path(root: str | Path, name: str) -> Path:
    return Path(root) / prop_name(name)


def list_props(root: str | Path) -> tuple[str, ...]:
    """소품 목록. **'해금' 개념이 없다** — 있으면 고를 수 있다(CLAUDE.md)."""
    folder = Path(root)
    if not folder.is_dir():
        return ()
    names = []
    for path in sorted(folder.glob(f'{PROP_PREFIX}*.png')):
        stem = path.stem[len(PROP_PREFIX):]
        if stem:
            names.append(stem)
    return tuple(names)
