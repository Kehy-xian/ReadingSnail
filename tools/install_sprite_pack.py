#!/usr/bin/env python3
"""원화를 사용자 교체 폴더에 설치한다.

    python tools/install_sprite_pack.py ~/내그림
    python tools/install_sprite_pack.py ~/내그림 --states idle,walk

왜 설치본이 아니라 별도 폴더인가
    설치·업데이트·삭제가 사용자 데이터를 건드리지 않아야 한다(CLAUDE.md).
    설치본 안에 그림을 덮어쓰면 앱을 업데이트할 때 날아간다.
    교체본은 데이터 폴더의 art_overrides/ 에 두고, 앱이 그쪽을 먼저 본다.

**규격을 통과한 상태만 설치한다.** 어긋난 그림은 앱에서 조용히 이상해지므로
설치하는 자리에서 막는 편이 낫다. --force 로 넘길 수 있지만 권하지 않는다.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from readingsnail.paths import default_data_dir                    # noqa: E402
from readingsnail.pet import art                                   # noqa: E402
from readingsnail.pet.sprites import override_root                 # noqa: E402
from readingsnail.pet.validation import validate_pack              # noqa: E402


def install(source: Path, target: Path, states: tuple[str, ...], *,
            slug: str = art.SLUG) -> list[Path]:
    """통째로 갖춰진 상태만 옮긴다. 옮긴 파일 목록을 돌려준다.

    임시 폴더에 모아 두었다가 한 번에 옮긴다. 중간에 끊겨도 앱이 절반짜리
    애니메이션을 보지 않는다.
    """
    target.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[Path, Path]] = []
    with tempfile.TemporaryDirectory(dir=target) as tmp:
        stage = Path(tmp)
        for state in states:
            full = art.has_full_animation(source, state, slug=slug)
            layered = art.has_layered_animation(source, state, slug=slug)
            if not (full or layered):
                continue
            for path in art.frame_paths(source, state, slug=slug, body_only=not full):
                shutil.copy2(path, stage / path.name)
                staged.append((stage / path.name, target / path.name))
        shell = art.shell_path(source, slug=slug)
        if shell.is_file():
            shutil.copy2(shell, stage / shell.name)
            staged.append((stage / shell.name, target / shell.name))
        for name in art.list_props(source):
            path = art.prop_path(source, name)
            shutil.copy2(path, stage / path.name)
            staged.append((stage / path.name, target / path.name))

        moved = []
        for src, dst in staged:
            shutil.move(str(src), str(dst))
            moved.append(dst)
    return moved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='달팽이 원화 설치')
    parser.add_argument('source', type=Path, help='그림이 있는 폴더')
    parser.add_argument('--states', default='', help='쉼표 구분. 비우면 갖춰진 것 전부')
    parser.add_argument('--slug', default=art.SLUG)
    parser.add_argument('--target', type=Path, default=None,
                        help='기본: 데이터 폴더의 art_overrides/')
    parser.add_argument('--force', action='store_true', help='규격 위반도 설치')
    args = parser.parse_args(argv)

    if not args.source.is_dir():
        sys.exit(f'그림 폴더가 없다: {args.source}')

    states = (tuple(s.strip() for s in args.states.split(',') if s.strip())
              or art.available_states(args.source, slug=args.slug))
    if not states:
        sys.exit('설치할 수 있는 상태가 없다. 프레임이 통째로 갖춰져야 한다.\n'
                 '  python tools/validate_sprite_pack.py <폴더> 로 확인할 것')

    issues = validate_pack(args.source, slug=args.slug, states=states)
    if issues and not args.force:
        print(f'규격 문제 {len(issues)}건 — 설치하지 않는다.')
        for issue in issues:
            print(issue)
        print('\n그래도 설치하려면 --force')
        return 1

    target = args.target or override_root(default_data_dir())
    moved = install(args.source, target, states, slug=args.slug)
    print(f'{len(moved)}장 설치 → {target}')
    print(f'  상태: {", ".join(states)}')
    print('앱을 다시 켜면 반영된다. 되돌리려면 그 폴더를 지우면 번들 그림으로 돌아간다.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
