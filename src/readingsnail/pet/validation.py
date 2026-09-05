"""스프라이트 팩 검증. 원화를 받았을 때 규격이 맞는지 본다.

왜 도구가 필요한가
    규격이 어긋난 그림은 앱에서 조용히 이상해진다 — 프레임마다 여백이 다르면
    이동할 때 위아래로 튀고, 반투명 픽셀이 많으면 색상 키 투명에서 테두리에
    얼룩이 생긴다. 눈으로는 알아채기 어렵고 움직여야 보인다.
    그래서 그림을 받는 자리에서 걸러낸다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import art

# 반투명 픽셀 비율이 이보다 높으면 색상 키 투명에서 테두리가 지저분해진다.
MAX_SOFT_ALPHA_RATIO = 0.18
# 바닥선이 프레임마다 이보다 더 흔들리면 이동할 때 튀어 보인다.
MAX_BASELINE_DRIFT = 3
SOFT_ALPHA_RANGE = (16, 239)


@dataclass(frozen=True)
class Issue:
    code: str
    path: str
    message: str

    def __str__(self) -> str:
        return f'{self.code}  {self.path}\n    {self.message}'


def _bbox_bottom(image) -> int | None:
    box = image.getbbox()
    return None if box is None else box[3]


def validate_frame(path: Path) -> tuple[list[Issue], int | None]:
    """한 장. (문제 목록, 바닥선 y)"""
    from PIL import Image

    issues: list[Issue] = []
    try:
        with Image.open(path) as source:
            image = source.convert('RGBA')
    except Exception as exc:                      # noqa: BLE001
        return [Issue('UNREADABLE', str(path), f'열 수 없다: {exc}')], None

    if image.size != (art.CANVAS, art.CANVAS):
        issues.append(Issue('SIZE', str(path),
                            f'{art.CANVAS}x{art.CANVAS} 여야 한다 (현재 {image.width}x{image.height})'))

    alpha = image.getchannel('A')
    counts = alpha.histogram()
    total = image.width * image.height
    opaque = counts[255]
    clear = counts[0]
    soft = total - opaque - clear
    if total and soft / total > MAX_SOFT_ALPHA_RATIO:
        issues.append(Issue('SOFT_EDGES', str(path),
                            f'반투명 픽셀이 {soft / total:.0%}다. 색상 키 투명에서 테두리가 얼룩진다. '
                            '선명한 외곽선으로 그릴 것'))
    if clear == 0:
        issues.append(Issue('NO_TRANSPARENCY', str(path),
                            '완전 투명 픽셀이 없다. 배경을 지우지 않았을 수 있다'))
    return issues, _bbox_bottom(image)


def validate_pack(root: str | Path, *, slug: str = art.SLUG,
                  states: tuple[str, ...] | None = None,
                  require: bool = False) -> list[Issue]:
    """팩 하나. states 를 주면 그것만, require 면 없는 상태도 문제로 센다."""
    folder = Path(root)
    issues: list[Issue] = []
    if not folder.is_dir():
        return [Issue('NO_PACK', str(folder), '폴더가 없다')]

    targets = states or art.STATES
    for state in targets:
        if state not in art.ANIMATIONS:
            issues.append(Issue('UNKNOWN_STATE', str(folder), f'알 수 없는 상태: {state}'))
            continue
        full = art.has_full_animation(folder, state, slug=slug)
        layered = art.has_layered_animation(folder, state, slug=slug)
        if not (full or layered):
            if require:
                missing = [p.name for p in art.frame_paths(folder, state, slug=slug)
                           if not p.is_file()]
                issues.append(Issue('INCOMPLETE', str(folder),
                                    f'{state}: {len(missing)}장 빠짐 (첫 번째 {missing[0]}). '
                                    '한 장이라도 없으면 그 상태는 벡터 폴백으로 간다'))
            continue

        paths = art.frame_paths(folder, state, slug=slug, body_only=not full)
        baselines: list[int] = []
        for path in paths:
            found, bottom = validate_frame(path)
            issues.extend(found)
            if bottom is not None:
                baselines.append(bottom)
        if len(baselines) >= 2:
            drift = max(baselines) - min(baselines)
            if drift > MAX_BASELINE_DRIFT:
                issues.append(Issue('BASELINE_DRIFT', str(folder),
                                    f'{state}: 바닥선이 프레임마다 {drift}px 흔들린다 '
                                    f'(허용 {MAX_BASELINE_DRIFT}px). 이동할 때 위아래로 튄다'))

    if art.shell_path(folder, slug=slug).is_file():
        found, _ = validate_frame(art.shell_path(folder, slug=slug))
        issues.extend(found)
    for name in art.list_props(folder):
        found, _ = validate_frame(art.prop_path(folder, name))
        issues.extend(found)
    return issues


def summarize(root: str | Path, *, slug: str = art.SLUG) -> dict:
    """무엇이 있고 무엇이 없는지. 원화 작업 진행 상황을 보는 용도."""
    folder = Path(root)
    have = set(art.available_states(folder, slug=slug))
    return {
        'root': str(folder),
        'states_present': tuple(s for s in art.STATES if s in have),
        'states_missing': tuple(s for s in art.STATES if s not in have),
        'required_missing': tuple(s for s in art.REQUIRED_STATES if s not in have),
        'has_shell': art.shell_path(folder, slug=slug).is_file(),
        'props': art.list_props(folder),
    }
