#!/usr/bin/env python3
"""스프라이트 팩 규격 검사.

    python tools/validate_sprite_pack.py resources/sprites
    python tools/validate_sprite_pack.py ~/내그림 --require   # 필수 6종을 반드시

규격이 어긋난 그림은 앱에서 조용히 이상해진다. 여기서 걸러낸다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from readingsnail.pet import art                                   # noqa: E402
from readingsnail.pet.validation import summarize, validate_pack   # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='스프라이트 팩 규격 검사')
    parser.add_argument('root', type=Path, help='<slug>_<state>_NN.png 가 있는 폴더')
    parser.add_argument('--slug', default=art.SLUG)
    parser.add_argument('--states', default='', help='쉼표 구분. 비우면 전체')
    parser.add_argument('--require', action='store_true',
                        help='필수 6종이 없으면 실패로 센다')
    args = parser.parse_args(argv)

    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit('Pillow 가 필요하다:  pip install Pillow')

    states = tuple(s.strip() for s in args.states.split(',') if s.strip()) or None
    if args.require and states is None:
        states = art.REQUIRED_STATES

    info = summarize(args.root, slug=args.slug)
    print(f"폴더  {info['root']}")
    print(f"  있음  {', '.join(info['states_present']) or '(없음)'}")
    print(f"  없음  {', '.join(info['states_missing']) or '(없음)'}")
    if info['required_missing']:
        print(f"  필수 중 빠진 것  {', '.join(info['required_missing'])}")
    print(f"  고정 껍데기  {'있음' if info['has_shell'] else '없음'}"
          f"  |  소품  {', '.join(info['props']) or '(없음)'}")

    issues = validate_pack(args.root, slug=args.slug, states=states, require=args.require)
    if not issues:
        print('\n규격 통과.')
        return 0
    print(f'\n문제 {len(issues)}건')
    for issue in issues:
        print(issue)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
