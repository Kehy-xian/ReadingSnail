"""ttk 위젯에 우리 팔레트를 입힌다. **색의 출처는 언제나 theme.PALETTE 다.**

왜 이 계층이 있는가
    ttkbootstrap 은 자기 색 체계를 들고 온다. 그냥 쓰면 6-a 에서 대비를 계산해
    맞춘 팔레트가 통째로 덮인다. 그래서 우리 색으로 사용자 테마를 만들어 등록한다.

    ttkbootstrap 이 없어도 돌아간다. 그때는 기본 ttk('clam')에 같은 색을 입힌다.
    보기가 조금 덜 다듬어질 뿐 색과 대비는 같다.

    **의존성을 필수로 만들지 않는다.** 설치가 덜 끝났다고 앱이 안 뜨면 안 된다
    (CLAUDE.md '무너져도 기록에는 닿아야 한다').
"""

from __future__ import annotations

from typing import Any

from ..theme import PALETTE, font

THEME_NAME = 'readingsnail'

# ttkbootstrap 이 요구하는 색 이름 → 우리 팔레트
# 이름이 낯설어도 뜻은 단순하다: bg 바탕, fg 글자, primary 강조, danger 경고.
BOOTSTRAP_COLORS = {
    'primary':   PALETTE['moss_deep'],     # 흰 글자를 얹는 강조 배경
    'secondary': PALETTE['ink_soft'],
    'success':   PALETTE['moss_deep'],
    'info':      PALETTE['shell_text'],
    'warning':   PALETTE['shell_text'],
    'danger':    PALETTE['berry'],
    'light':     PALETTE['paper_deep'],
    'dark':      PALETTE['ink'],
    'bg':        PALETTE['paper'],
    'fg':        PALETTE['ink'],
    'selectbg':  PALETTE['moss_deep'],
    'selectfg':  PALETTE['on_accent'],
    'border':    PALETTE['border'],
    'inputfg':   PALETTE['ink'],
    'inputbg':   PALETTE['paper'],
    'active':    PALETTE['paper_deep'],
}


def _try_bootstrap(root) -> Any | None:
    """ttkbootstrap 이 있으면 우리 색으로 테마를 만들어 적용한다.

    **기본 root 에서만 쓴다.** ttkbootstrap.Style 은 master 를 받지 않고
    `tkinter._default_root` 에 붙는다. 창이 둘 이상일 때 다른 창에 물리면
    폰트 캐시·Tk 이미지에서 겪은 것과 같은 종류의 문제가 난다.
    앱은 root 가 하나라 문제없고, 테스트에서 창을 여럿 만들 때만 기본 ttk 로 간다.
    """
    import tkinter

    # ttk 스타일은 위젯이 아니라 **인터프리터** 단위다. ttkbootstrap.Style 은
    # master 를 받지 않고 tkinter._default_root 에 붙으므로, 이 창이 그 기본
    # root 와 같은 인터프리터일 때만 쓴다. 창이 여럿인 상황(테스트 등)에서는
    # 기본 ttk 로 간다 — 폰트 캐시·Tk 이미지에서 겪은 것과 같은 종류의 문제다.
    default = tkinter._default_root
    if default is None or default.tk is not root.tk:
        return None
    try:
        import ttkbootstrap as tb
        from ttkbootstrap.style import Style as BootstrapStyle
        from ttkbootstrap.style import ThemeDefinition
    except ImportError:
        return None

    # ttkbootstrap.Style 은 **프로세스 전역 싱글턴**이라 처음 만든 root 를 계속
    # 붙들고 있다. 그 root 가 죽은 뒤에는 ttk 조작마다 죽은 위젯에
    # <<ThemeChanged>> 를 쏘아 ttk 전체가 오염된다.
    # 창을 다시 만드는 경로(SPEC 7항 배율 전환)에서 실제로 걸리므로,
    # 붙들고 있는 root 가 살아 있지 않으면 싱글턴을 비우고 새로 만든다.
    stale = getattr(BootstrapStyle, 'instance', None)
    if stale is not None:
        try:
            alive = bool(stale.master.winfo_exists()) and stale.master.tk is root.tk
        except Exception:
            alive = False
        if not alive:
            try:
                BootstrapStyle.instance = None
            except Exception:
                return None

    try:
        style = tb.Style()
        if THEME_NAME not in style.theme_names():
            style.register_theme(
                ThemeDefinition(name=THEME_NAME, colors=dict(BOOTSTRAP_COLORS),
                                mode='light'))
        style.theme_use(THEME_NAME)
        return style
    except Exception:
        # 버전이 달라 API 가 어긋나도 앱은 떠야 한다. 기본 ttk 로 내려간다.
        return None


def apply(root) -> Any:
    """창 하나에 스타일을 입힌다. 만들어진 Style 을 돌려준다.

    Tk 스타일은 인터프리터마다 따로 산다. **창마다 한 번씩** 부를 것.
    """
    from tkinter import ttk

    style = _try_bootstrap(root)
    if style is None:
        style = ttk.Style(master=root)
        if 'clam' in style.theme_names():
            style.theme_use('clam')

    paper, deep = PALETTE['paper'], PALETTE['paper_deep']
    ink, soft = PALETTE['ink'], PALETTE['ink_soft']
    border, accent = PALETTE['border'], PALETTE['moss_deep']

    body = font('body', master=root)
    heading = font('heading', bold=True, master=root)
    caption = font('caption', master=root)
    quote = font('quote', master=root)

    root.configure(bg=paper)
    style.configure('.', background=paper, foreground=ink, font=body,
                    bordercolor=border, focuscolor=accent)
    style.configure('TFrame', background=paper)
    style.configure('TLabel', background=paper, foreground=ink, font=body)
    style.configure('Heading.TLabel', font=heading, foreground=ink)
    style.configure('Caption.TLabel', font=caption, foreground=soft)
    style.configure('Quote.TLabel', font=quote, foreground=ink, background=deep)
    style.configure('Muted.TLabel', foreground=soft, font=caption)

    style.configure('TButton', font=body, padding=(12, 6))
    style.configure('Accent.TButton', font=body, padding=(14, 7),
                    background=accent, foreground=PALETTE['on_accent'])
    style.map('Accent.TButton',
              background=[('active', PALETTE['moss_text']),
                          ('disabled', PALETTE['line'])])
    style.configure('Danger.TButton', background=PALETTE['berry'],
                    foreground=PALETTE['on_accent'])

    style.configure('TEntry', fieldbackground=paper, foreground=ink,
                    bordercolor=border, padding=4)
    style.configure('TCombobox', fieldbackground=paper, foreground=ink,
                    bordercolor=border, padding=4)
    style.configure('TRadiobutton', background=paper, foreground=ink, font=body)
    style.configure('TCheckbutton', background=paper, foreground=ink, font=body)
    style.configure('TNotebook', background=paper, bordercolor=border)
    style.configure('TNotebook.Tab', font=body, padding=(14, 7))
    style.configure('Treeview', background=paper, fieldbackground=paper,
                    foreground=ink, font=body, rowheight=26, bordercolor=border)
    style.configure('Treeview.Heading', font=caption, foreground=soft)
    style.map('Treeview', background=[('selected', accent)],
              foreground=[('selected', PALETTE['on_accent'])])
    style.configure('TSeparator', background=PALETTE['line'])
    style.configure('Card.TFrame', background=deep)
    return style


def text_defaults(master=None) -> dict:
    """tk.Text 는 ttk 가 아니라 스타일이 안 먹는다. 여기서 같은 색을 넘긴다."""
    return {
        'bg': PALETTE['paper'],
        'fg': PALETTE['ink'],
        'insertbackground': PALETTE['ink'],
        'selectbackground': PALETTE['moss_deep'],
        'selectforeground': PALETTE['on_accent'],
        'highlightthickness': 1,
        'highlightbackground': PALETTE['border'],
        'highlightcolor': PALETTE['moss_deep'],
        'relief': 'flat',
        'padx': 8,
        'pady': 6,
        'font': font('body', master=master),
    }
