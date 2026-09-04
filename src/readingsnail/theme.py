"""폰트·색·간격을 한 곳에서 관리한다.

BookEater에서는 폰트가 `font=('', 18, 'bold')`처럼 가족명 없이 30군데 넘게
흩어져 있었다. 그 결과 Tk 기본 폰트로 렌더링되어 화면이 낡아 보였다.
여기서만 고치면 전부 따라오도록 상수로 묶는다.

동봉 폰트는 재배포가 허용된 것만 쓴다. 각 폰트의 라이선스 원문을 직접
확인한 뒤 resources/fonts 에 넣고 FONT_FILES 에 등록할 것.
"""

from __future__ import annotations

import tkinter.font as tkfont

# ── 폰트 ──────────────────────────────────────────────
# 앞에서부터 설치/동봉된 것을 찾아 쓴다. 전부 없으면 Tk 기본값.
DISPLAY_STACK = ('NanumSquareRound', 'Gowun Dodum', 'Malgun Gothic')
BODY_STACK = ('Pretendard', 'Malgun Gothic')

FONT_FILES: tuple[str, ...] = ()  # 예: ('NanumSquareRoundR.ttf',)

_SIZES = {
    'title': 20,
    'heading': 15,
    'subheading': 13,
    'body': 11,
    'small': 10,
    'caption': 9,
    'bubble': 12,   # 달팽이 말풍선
}

_resolved: dict[str, tkfont.Font] = {}


def _first_available(stack: tuple[str, ...]) -> str:
    families = set(tkfont.families())
    for name in stack:
        if name in families:
            return name
    return ''


def font(role: str = 'body', *, bold: bool = False) -> tkfont.Font:
    """역할 이름으로 폰트를 얻는다. tkinter 초기화 이후에만 호출할 것."""
    key = f'{role}:{"b" if bold else "r"}'
    if key not in _resolved:
        stack = DISPLAY_STACK if role in ('title', 'heading', 'bubble') else BODY_STACK
        _resolved[key] = tkfont.Font(
            family=_first_available(stack),
            size=_SIZES.get(role, _SIZES['body']),
            weight='bold' if bold else 'normal',
        )
    return _resolved[key]


# ── 색 ────────────────────────────────────────────────
# 채도를 낮춘 파스텔. 종이·잉크·이끼에서 가져왔다.
PALETTE = {
    'paper':      '#FBF7F0',   # 패널 바탕
    'paper_deep': '#F2EADC',   # 눌린 영역, 목록 줄무늬
    'ink':        '#3A3330',   # 본문 글자
    'ink_soft':   '#7A6F68',   # 보조 글자
    'line':       '#E3D9C8',   # 구분선·테두리
    'moss':       '#8FB08A',   # 강조 (달팽이 몸)
    'moss_deep':  '#5E7F5C',   # 눌림·활성
    'shell':      '#D8A15C',   # 보조 강조 (껍데기)
    'berry':      '#C97B84',   # 경고·삭제
    'shelf_wood': '#C4A484',   # 책장 선반
}

# 창 투명도 키 색. 어떤 원화에도 등장하지 않을 색이어야 한다.
TRANSPARENT_KEY = '#FF00FF'

# ── 간격 ──────────────────────────────────────────────
PAD_XS, PAD_S, PAD_M, PAD_L = 4, 8, 14, 22
RADIUS = 12   # 이미지 기반 패널 배경을 그릴 때 쓰는 모서리 반경
