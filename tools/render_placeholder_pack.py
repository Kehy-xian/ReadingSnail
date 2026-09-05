#!/usr/bin/env python3
"""자리표시 스프라이트 팩을 그린다. **원화가 아니다.**

왜 필요한가
    원화가 오기 전까지 파이프라인이 실제 PNG 로 도는지 확인할 방법이 없다.
    이 도구가 규격에 맞는 팩을 만들어 로더·합성·반전·소품까지 한 번에 시험하게 한다.
    원화가 들어오면 이 팩을 덮어쓰면 된다. 앱 코드는 바뀌지 않는다.

무엇을 만드는가
    · 몸통 프레임 snail_body_<state>_<nn>.png  (분리 방식 — 껍데기는 한 장뿐)
    · 고정 껍데기 snail_shell.png
    · 소품 예시 prop_leaf.png, prop_glasses.png
    규격은 docs/SPRITE_GUIDE_KO.md — 190×190 RGBA, 좌향, 바닥선 고정.

    idle 은 가이드가 정한 리듬 (0,-1,-2,-3,-3,-2,-1,0 px)을 그대로 따른다.
    발과 접지 그림자는 고정하고 몸통만 움직인다. 캐릭터 전체를 올리면 뜬 것처럼 보인다.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from readingsnail.pet import art          # noqa: E402
from readingsnail.theme import PALETTE    # noqa: E402

SIZE = art.CANVAS
SS = 4          # 초과표본. 외곽선이 계단지지 않게 4배로 그리고 줄인다.

IDLE_RHYTHM = (0, -1, -2, -3, -3, -2, -1, 0)


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


INK = _rgb(PALETTE['ink'])
MOSS = _rgb(PALETTE['moss'])
SHELL = _rgb(PALETTE['shell'])
PAPER = _rgb(PALETTE['paper'])
LINE = _rgb(PALETTE['line'])


def _canvas():
    from PIL import Image
    return Image.new('RGBA', (SIZE * SS, SIZE * SS), (0, 0, 0, 0))


def _shrink(image):
    from PIL import Image
    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def _draw_body(draw, *, lift: int, lean: int = 0, squash: int = 0, mouth: int = 0):
    """발·머리·눈자루. 껍데기는 그리지 않는다(고정 레이어라서)."""
    s = SS
    ground = 150                 # 바닥선. **무슨 일이 있어도 움직이지 않는다.**
    base = ground - squash
    y = base + lift

    # 접지 그림자는 바닥선에 고정한다. squash 를 따라 올리면 웅크릴 때 그림자까지
    # 떠올라 프레임마다 바닥선이 흔들린다(검증기의 BASELINE_DRIFT).
    draw.ellipse([22 * s, (ground + 12) * s, 156 * s, (ground + 24) * s], fill=LINE + (110,))

    foot = [(24 + lean, y + 14), (30 + lean, y - 6), (52, y - 16), (96, y - 18),
            (146, y - 6), (152, y + 10), (140, y + 16), (40, y + 16)]
    draw.polygon([(x * s, v * s) for x, v in foot], fill=MOSS,
                 outline=INK, width=2 * s)
    draw.ellipse([(20 + lean) * s, (y - 20) * s, (58 + lean) * s, (y + 10 + mouth) * s],
                 fill=MOSS, outline=INK, width=2 * s)

    for tip_x, tip_y, root_x in ((22 + lean, y - 58, 30 + lean), (44 + lean, y - 66, 44)):
        draw.line([root_x * s, (y - 12) * s, tip_x * s, tip_y * s], fill=INK, width=2 * s)
        draw.ellipse([(tip_x - 7) * s, (tip_y - 7) * s, (tip_x + 7) * s, (tip_y + 7) * s],
                     fill=PAPER, outline=INK, width=2 * s)
        draw.ellipse([(tip_x - 3) * s, (tip_y - 3) * s, (tip_x + 3) * s, (tip_y + 3) * s],
                     fill=INK)


def body_frame(state: str, index: int):
    from PIL import ImageDraw
    canvas = _canvas()
    draw = ImageDraw.Draw(canvas)
    spec = art.ANIMATIONS[state]
    t = index / max(1, spec.frames - 1) if spec.frames > 1 else 0.0

    if state == 'idle':
        _draw_body(draw, lift=IDLE_RHYTHM[index % len(IDLE_RHYTHM)])
    elif state == 'walk':
        # 12장이 한 주기. 첫 장과 끝 장이 이어지도록 사인파로 만든다.
        phase = 2 * math.pi * index / spec.frames
        _draw_body(draw, lift=round(-2 * abs(math.sin(phase))),
                   lean=round(3 * math.sin(phase)))
    elif state == 'talk':
        _draw_body(draw, lift=0, mouth=2 if index % 2 else 0)
    elif state == 'sleep':
        _draw_body(draw, lift=1, squash=8)
    elif state == 'bump':
        _draw_body(draw, lift=round(3 * (1 - t)), squash=6, lean=round(-4 * (1 - t)))
    elif state == 'drop':
        _draw_body(draw, lift=round(-4 * t), lean=2)
    elif state in ('eat', 'shelve'):
        _draw_body(draw, lift=round(-2 * math.sin(math.pi * t)), mouth=round(6 * math.sin(math.pi * t)))
    elif state == 'spit_memory':
        _draw_body(draw, lift=round(-3 * math.sin(math.pi * t)), mouth=round(4 * math.sin(math.pi * t)))
    elif state == 'tuck':
        _draw_body(draw, lift=0, squash=round(14 * t))
    else:                                     # read 등
        _draw_body(draw, lift=0)
    return _shrink(canvas)


def shell_layer():
    """고정 껍데기 한 장. 프레임마다 다시 그리지 않는다."""
    from PIL import ImageDraw
    canvas = _canvas()
    draw = ImageDraw.Draw(canvas)
    s = SS
    draw.ellipse([70 * s, 82 * s, 154 * s, 158 * s], fill=SHELL, outline=INK, width=2 * s)
    draw.ellipse([94 * s, 104 * s, 132 * s, 138 * s], outline=INK, width=2 * s)
    draw.ellipse([106 * s, 114 * s, 122 * s, 128 * s], outline=INK, width=2 * s)
    return _shrink(canvas)


def prop_leaf():
    from PIL import ImageDraw
    canvas = _canvas()
    draw = ImageDraw.Draw(canvas)
    s = SS
    draw.polygon([(118 * s, 74 * s), (140 * s, 56 * s), (150 * s, 76 * s), (126 * s, 86 * s)],
                 fill=(143, 176, 138), outline=INK, width=2 * s)
    draw.line([118 * s, 74 * s, 148 * s, 62 * s], fill=INK, width=s)
    return _shrink(canvas)


def prop_glasses():
    from PIL import ImageDraw
    canvas = _canvas()
    draw = ImageDraw.Draw(canvas)
    s = SS
    for cx in (22, 44):
        draw.ellipse([(cx - 9) * s, 76 * s, (cx + 9) * s, 94 * s], outline=INK, width=2 * s)
    draw.line([31 * s, 85 * s, 35 * s, 85 * s], fill=INK, width=2 * s)
    return _shrink(canvas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='자리표시 스프라이트 팩 생성 (원화 아님)')
    parser.add_argument('out', type=Path, nargs='?',
                        default=ROOT / 'resources' / 'sprites',
                        help='스프라이트를 쓸 폴더')
    parser.add_argument('--props', type=Path, default=None,
                        help='소품 폴더 (기본: resources/props)')
    parser.add_argument('--states', default='',
                        help='쉼표로 구분. 비우면 전체')
    args = parser.parse_args(argv)

    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit('Pillow 가 필요하다:  pip install Pillow')

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    states = ([s.strip() for s in args.states.split(',') if s.strip()]
              or list(art.STATES))

    written = 0
    for state in states:
        if state not in art.ANIMATIONS:
            print(f'  건너뜀: 알 수 없는 상태 {state}', file=sys.stderr)
            continue
        for index in range(art.ANIMATIONS[state].frames):
            path = out / art.frame_name(state, index, body_only=True)
            body_frame(state, index).save(path)
            written += 1
    shell_layer().save(art.shell_path(out))
    written += 1

    props = args.props or (ROOT / 'resources' / 'props')
    props.mkdir(parents=True, exist_ok=True)
    prop_leaf().save(art.prop_path(props, 'leaf'))
    prop_glasses().save(art.prop_path(props, 'glasses'))
    written += 2

    print(f'{written}장 생성 → {out}')
    print('원화가 아니다. 규격 확인용 자리표시다. docs/SPRITE_GUIDE_KO.md 참조.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
