"""폰트·색·간격을 한 곳에서 관리한다. (6-a 정비판)

tkinter 는 **함수 안에서** 불러온다. 색·간격은 순수 데이터인데 모듈 수준에서
tkinter 를 끌어오면 빌드 도구·검증기·헤드리스 스크립트가 팔레트조차 못 읽는다.
(자리표시 스프라이트 생성기가 실제로 여기서 막혔다.)

전작에서 고친 것
    BookEater 는 `font=('', 18, 'bold')` 처럼 가족명 없이 30군데 넘게 흩어져 있었다.
    Tk 기본 폰트로 렌더링되어 화면이 낡아 보였다. 여기서만 고치면 전부 따라온다.

대비를 실측해서 골랐다
    이전 팔레트는 이끼색 버튼 위 흰 글자가 2.25 였다 — 거의 안 읽힌다.
    아래 색들은 WCAG 대비를 계산해 맞춘 값이다. tests/test_theme.py 가 지킨다.
    **채우기용 색과 글자용 색을 나눈 이유가 그것이다.** 달팽이 몸에 쓰는 연한
    이끼색은 글자로 쓰면 안 된다.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:                      # 타입 힌트용. 실행 시에는 불러오지 않는다.
    import tkinter
    import tkinter.font as tkfont

# ── 폰트 ──────────────────────────────────────────────
# 앞에서부터 설치·동봉된 것을 찾아 쓴다. 전부 없으면 Tk 기본값.
DISPLAY_STACK = ('NanumSquareRound', 'NanumSquareRoundOTF', 'Gowun Dodum', 'Malgun Gothic')
BODY_STACK = ('Pretendard', 'Pretendard Variable', 'Malgun Gothic', 'Segoe UI')
MONO_STACK = ('D2Coding', 'Consolas', 'Courier New')

FONTS_RELATIVE = Path('resources') / 'fonts'

# 동봉 후보. 둘 다 SIL Open Font License 1.1 이라 **동봉·재배포가 허용된다.**
#   NanumSquareRound  © NAVER Corporation, OFL 1.1
#   Pretendard        © Kil Hyung-jin, OFL 1.1
# OFL 은 글꼴 단독 판매만 금지한다. 앱에 묶어 배포하는 것은 허용된다.
# **다만 라이선스 전문(OFL.txt)을 함께 넣어야 한다.** resources/fonts/README.txt 참조.
BUNDLED_FONTS: tuple[str, ...] = (
    'NanumSquareRoundR.ttf',
    'NanumSquareRoundB.ttf',
    'Pretendard-Regular.ttf',
    'Pretendard-SemiBold.ttf',
)

_SIZES = {
    'title': 20,
    'heading': 15,
    'subheading': 13,
    'body': 11,
    'small': 10,
    'caption': 9,
    'bubble': 12,   # 달팽이 말풍선
    'quote': 13,    # 필사한 문장을 보여줄 때. 본문보다 조금 크게.
    'mono': 10,
}
DISPLAY_ROLES = ('title', 'heading', 'bubble', 'quote')

# Tk 이름있는 폰트는 **인터프리터마다 따로** 산다. Tk root 를 새로 만들면 옛 Font
# 객체는 죽은 인터프리터를 가리켜 TclError 가 나거나, 더 나쁘게는 그 이름이 새
# 인터프리터에 없어 조용히 다른 폰트로 그려진다. 그래서 인터프리터별로 나눠 담는다.
# (창 배율을 바꾸느라 창을 다시 만드는 경로에서 실제로 걸린다.)
_resolved: dict[tuple[object, str, bool], object] = {}
_registered: set[str] = set()


def reset_font_cache() -> None:
    """캐시를 비운다. Tk root 를 버리고 새로 만들 때 부른다."""
    _resolved.clear()


def load_bundled_fonts(resource_root: str | Path) -> tuple[str, ...]:
    """동봉 폰트를 **설치 없이** 이 프로세스에만 등록한다 (Windows).

    사용자 컴퓨터에 폰트를 설치하지 않는다. 설치·삭제가 사용자 환경을 건드리지
    않아야 한다는 제약과 같은 태도다. 등록에 실패해도 조용히 넘어간다 —
    폰트가 없으면 스택의 다음 후보로 내려갈 뿐이다.

    Windows 밖에서는 아무 일도 하지 않는다. Tk 가 fontconfig 를 쓰므로
    개발 중에는 시스템에 설치된 폰트를 그대로 본다.

    돌려주는 값은 실제로 등록된 파일 이름들.
    """
    import sys

    folder = Path(resource_root) / FONTS_RELATIVE
    if not sys.platform.startswith('win') or not folder.is_dir():
        return ()

    try:
        import ctypes
        add_font = ctypes.windll.gdi32.AddFontResourceExW
    except Exception:
        return ()

    FR_PRIVATE = 0x10          # 이 프로세스만. 시스템 폰트 목록을 더럽히지 않는다.
    added: list[str] = []
    for name in BUNDLED_FONTS:
        path = folder / name
        if not path.is_file() or name in _registered:
            continue
        try:
            if add_font(str(path), FR_PRIVATE, 0):
                _registered.add(name)
                added.append(name)
        except Exception:
            continue
    if added:
        # 등록 직후에는 Tk 가 목록을 다시 읽어야 새 폰트를 본다.
        reset_font_cache()
    return tuple(added)


def _first_available(stack: tuple[str, ...], master: 'tkinter.Misc | None') -> str:
    import tkinter.font as tkfont

    families = set(tkfont.families(root=master) if master is not None else tkfont.families())
    for name in stack:
        if name in families:
            return name
    return ''          # 전부 없으면 Tk 기본값


def font(role: str = 'body', *, bold: bool = False,
         master: 'tkinter.Misc | None' = None) -> 'tkfont.Font':
    """역할 이름으로 폰트를 얻는다. tkinter 초기화 이후에만 호출할 것.

    master 를 넘기면 그 창의 인터프리터에 만든다. 창이 둘 이상이면 반드시 넘길 것.
    """
    import tkinter
    import tkinter.font as tkfont

    root = master if master is not None else tkinter._default_root
    if root is None:
        raise RuntimeError('tkinter 초기화 이후에만 theme.font() 를 부를 것')
    # 키에 인터프리터 객체 자체를 넣는다. id() 를 쓰면 옛 객체가 회수된 뒤
    # 같은 주소를 새 인터프리터가 물려받아 죽은 폰트를 돌려줄 수 있다.
    key = (root.tk, role, bold)
    cached = _resolved.get(key)
    if cached is not None:
        return cached
    if role == 'mono':
        stack = MONO_STACK
    elif role in DISPLAY_ROLES:
        stack = DISPLAY_STACK
    else:
        stack = BODY_STACK
    created = tkfont.Font(
        root=root,
        family=_first_available(stack, root),
        size=_SIZES.get(role, _SIZES['body']),
        weight='bold' if bold else 'normal',
    )
    _resolved[key] = created
    return created


# ── 색 ────────────────────────────────────────────────
# 채도를 낮춘 파스텔. 종이·잉크·이끼에서 가져왔다.
#
# **채우기용과 글자용을 나눈다.** 연한 이끼색은 달팽이 몸에는 좋지만 글자로 쓰면
# 종이 위에서 대비 2.25 로 읽히지 않는다. `_text` 가 붙은 것이 글자·테두리용,
# `_deep` 이 붙은 것이 흰 글자를 얹을 배경용이다.
PALETTE = {
    # 바탕
    'paper':      '#FBF7F0',   # 패널 바탕
    'paper_deep': '#F2EADC',   # 눌린 영역, 목록 줄무늬

    # 글자
    'ink':        '#3A3330',   # 본문           종이 위 11.6 (AAA)
    'ink_soft':   '#726761',   # 보조 글자      종이 5.1 / 눌림 4.6 (AA)
    'on_accent':  '#FBF7F0',   # 강조 배경 위 글자

    # 선
    'line':       '#E3D9C8',   # **장식용 구분선.** 대비 1.3 — 뜻을 담지 않는다.
    'border':     '#938B87',   # 입력칸·초점 테두리. 종이 위 3.1 (비텍스트 AA)

    # 이끼 — 강조
    'moss':       '#8FB08A',   # 채우기 전용 (달팽이 몸)
    'moss_text':  '#567851',   # 종이 위 글자·아이콘   4.7 (AA)
    'moss_deep':  '#5A7958',   # 흰 글자를 얹는 배경   4.6 (AA)

    # 껍데기 — 보조 강조
    'shell':      '#D8A15C',   # 채우기 전용
    'shell_text': '#9A6625',   # 종이 위 글자          4.6 (AA)

    # 자두 — 경고·삭제
    'berry':      '#B7505C',   # 종이 위 글자로도, 흰 글자 배경으로도  4.6 (AA)
    'berry_soft': '#E8CDD1',   # 경고 영역 바탕 (그 위에는 ink 를 쓴다)

    'shelf_wood': '#C4A484',   # 책장 선반 (장식)
}

# 창 투명도 키 색. 어떤 원화에도 등장하지 않을 색이어야 한다.
TRANSPARENT_KEY = '#FF00FF'

# ── 간격 ──────────────────────────────────────────────
PAD_XS, PAD_S, PAD_M, PAD_L = 4, 8, 14, 22
RADIUS = 12   # 이미지 기반 패널 배경을 그릴 때 쓰는 모서리 반경


# ── 대비 계산 ─────────────────────────────────────────
def relative_luminance(color: str) -> float:
    """WCAG 상대 휘도."""
    text = color.lstrip('#')
    if len(text) != 6:
        raise ValueError(f'#RRGGBB 형식이어야 한다: {color}')
    channels = []
    for i in (0, 2, 4):
        value = int(text[i:i + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.04045
                        else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(foreground: str, background: str) -> float:
    """WCAG 대비비. 4.5 이상이면 본문, 3.0 이상이면 큰 글자·비텍스트."""
    a, b = relative_luminance(foreground), relative_luminance(background)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)
