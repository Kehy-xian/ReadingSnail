"""바탕화면 달팽이 창. **한 파일, 한 클래스.**

전작에서 고친 것 — 여기가 최대 기술부채였다
    BookEater 는 pet_window.py(700줄) 위에 v2~v11 이 한 겹씩 올라탄 11단계 상속
    체인이었다(3,469줄). 메서드 하나를 고치려면 어느 겹에서 덮였는지 열한 파일을
    거슬러 올라가야 했고, 새 기능은 늘 새 겹으로 붙어 체인이 더 길어졌다.
    여기서는 겹을 만들지 않는다. 창이 커지면 상속이 아니라 **패널을 별도 모듈로**
    떼어낸다(services/ 나 pet/panels/). PetWindow 를 상속하지 말 것.

투명 처리
    '-transparentcolor' 는 **Windows 전용**이다. X11/macOS 에는 없고 TclError 가
    난다. 없으면 알파로 물러나되, 그때는 창이 네모로 보인다는 걸 감수한다.
    (PySide6 로 갈아타지 않기로 했으므로 이건 선명한 외곽선 그림체로 우회한다.)

그림
    스프라이트는 5단계다. 지금은 벡터 폴백으로 그린다. 프레임이 없어도 앱이
    동작해야 한다는 원칙(docs/SPRITE_GUIDE_KO.md)의 바닥이 이 코드다.
"""

from __future__ import annotations

import sys
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from typing import Callable

from ..theme import PALETTE, TRANSPARENT_KEY, font
from . import art
from .behavior import PetMotion, RoamPlanner, WorkArea
from .sprites import SpriteCache, frame_index

BASE_SIZE = art.CANVAS   # 원화 캔버스 크기. 스프라이트 규격과 같다.
ROAM_INTERVAL_MS = 70    # 이동 틱
DRAW_INTERVAL_MS = 120   # 그리기 틱
BUBBLE_HOLD_MS = 9000    # 말풍선이 떠 있는 시간


def enable_dpi_awareness() -> None:
    """Windows 고DPI. 이걸 안 하면 좌표와 화면 크기가 배율만큼 어긋난다.

    Tk 를 만들기 **전에** 불러야 한다.
    """
    if not sys.platform.startswith('win'):
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # 시스템 DPI 인식
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def desktop_work_area(root: tk.Misc) -> WorkArea:
    """작업 표시줄을 뺀 실제 사용 영역.

    Windows 는 SPI_GETWORKAREA 로 물어본다. 안 되면 화면 전체를 쓰되,
    계획기가 여백을 두므로 작업 표시줄 위로 살짝 걸치는 정도로 끝난다.
    """
    if sys.platform.startswith('win'):
        try:
            import ctypes

            class RECT(ctypes.Structure):
                _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                            ('right', ctypes.c_long), ('bottom', ctypes.c_long)]

            rect = RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                if rect.right > rect.left and rect.bottom > rect.top:
                    return WorkArea(rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            pass
    return WorkArea(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())


class PetWindow:
    """달팽이 한 마리. 상속하지 말 것 — 늘어나면 패널을 따로 뗀다."""

    def __init__(
        self,
        *,
        scale: float = 1.0,
        start_at: tuple[int, int] = (120, 120),
        on_write: Callable[[], None] | None = None,
        on_library: Callable[[], None] | None = None,
        on_add_book: Callable[[], None] | None = None,
        on_shelf: Callable[[], None] | None = None,
        on_props: Callable[[], None] | None = None,
        sprites: SpriteCache | None = None,
        resource_root: str | Path | None = None,
        data_dir: str | Path | None = None,
        on_quit: Callable[[], None] | None = None,
        root: tk.Tk | None = None,
    ) -> None:
        self.scale = max(0.5, min(1.0, float(scale)))
        self.size = max(95, round(BASE_SIZE * self.scale))
        self.on_write = on_write
        self.on_library = on_library
        self.on_add_book = on_add_book
        self.on_shelf = on_shelf
        self.on_props = on_props
        # 스프라이트가 없으면 벡터로 그린다. 원화가 한 상태씩 들어와도
        # 그 상태만 교체되고 나머지는 그대로 벡터다(SPRITE_GUIDE_KO.md).
        self.on_quit = on_quit

        self.root = root if root is not None else tk.Tk()
        self.root.title('책 읽는 달팽이')
        self.root.geometry(f'{self.size}x{self.size}+{start_at[0]}+{start_at[1]}')
        self.root.overrideredirect(True)
        try:
            self.root.wm_attributes('-topmost', True)
        except tk.TclError:
            pass

        self.transparent = self._enable_transparency()
        bg = TRANSPARENT_KEY if self.transparent else PALETTE['paper']
        self.root.configure(bg=bg)
        self.canvas = tk.Canvas(self.root, width=self.size, height=self.size, bg=bg,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill='both', expand=True)

        # 캐시는 **이 창에 묶인다.** root 가 생긴 뒤에 만들어야 한다.
        # 밖에서 만든 캐시를 다른 창에 물리면 Tk 이미지가 깨진다
        # ('image "pyimageN" doesn't exist').
        if sprites is None and resource_root is not None:
            sprites = SpriteCache(tk, resource_root, master=self.root, data_dir=data_dir)
        self.sprites = sprites
        self._state_started_ms = 0
        self._sprite_state: str | None = None

        self.planner = RoamPlanner(step_px=6, window_width=self.size,
                                   window_height=self.size, margin=8)
        # 켜자마자 돌아다니면 산만하다. 잠깐 가만히 있다 움직인다.
        self.motion = PetMotion(x=start_at[0], y=start_at[1], state='idle', hold_ticks=14)

        self._dragging = False
        self._grab_dx = 0
        self._grab_dy = 0
        self._paused = False        # 메뉴·패널이 열려 있으면 멈춘다
        self._closed = False
        self._bubble: str | None = None
        self._bubble_after: str | None = None
        # 예약해 둔 after 들. 닫을 때 취소하지 않으면 Tk 가 사라진 뒤에도 남아
        # 'invalid command name ...' 이 뜨고, 창이 둘 이상이면 엉뚱한 곳에서 터진다.
        self._after_ids: set[str] = set()
        # 창을 닫기 전에 불러줄 것들. 패널이 쓰던 글을 초안으로 남길 기회다.
        # root.destroy() 는 자식 Toplevel 을 그냥 없애버리므로 이게 없으면 글이 사라진다.
        self._closers: list[Callable[[], None]] = []
        # 한 번에 하나만 띄우는 창들. show_once() 가 관리한다.
        self._panels: dict[str, object] = {}

        self.canvas.bind('<ButtonPress-1>', self._drag_start)
        self.canvas.bind('<B1-Motion>', self._drag_move)
        self.canvas.bind('<ButtonRelease-1>', self._drag_end)
        self.canvas.bind('<Double-Button-1>', lambda _e: self._call(self.on_write))
        self.canvas.bind('<Button-3>', self._show_menu)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label='기록 남기기', command=lambda: self._call(self.on_write))
        self.menu.add_command(label='책 등록', command=lambda: self._call(self.on_add_book))
        self.menu.add_command(label='내 서재', command=lambda: self._call(self.on_library))
        self.menu.add_command(label='책장', command=lambda: self._call(self.on_shelf))
        self.menu.add_separator()
        self.menu.add_command(label='소품', command=lambda: self._call(self.on_props))
        self.menu.add_separator()
        self.menu.add_command(label='종료', command=self.close)
        self.root.protocol('WM_DELETE_WINDOW', self.close)

        self.root.update_idletasks()
        self._sync_from_window()
        self.draw()

    # ── 창 ────────────────────────────────────────────
    def _enable_transparency(self) -> bool:
        """색상 키 투명이 되면 True. 안 되면 알파로 물러나고 False."""
        try:
            self.root.wm_attributes('-transparentcolor', TRANSPARENT_KEY)
            return True
        except tk.TclError:
            try:
                self.root.wm_attributes('-alpha', 0.97)
            except tk.TclError:
                pass
            return False

    def work_area(self) -> WorkArea:
        return desktop_work_area(self.root)

    def _sync_from_window(self) -> None:
        """실제 창 위치를 상태에 맞춘다. 사용자가 끌어다 놓은 뒤에 필요하다."""
        x, y = self.planner.clamp(
            int(self.root.winfo_x()), int(self.root.winfo_y()), self.work_area())
        self.motion = PetMotion(
            x=x, y=y, state=self.motion.state, target_x=self.motion.target_x,
            target_y=self.motion.target_y, facing=self.motion.facing,
            hold_ticks=self.motion.hold_ticks, fall_speed=self.motion.fall_speed)

    def _place(self) -> None:
        self.root.geometry(f'{self.size}x{self.size}+{self.motion.x}+{self.motion.y}')

    # ── 입력 ──────────────────────────────────────────
    def _drag_start(self, event: tk.Event) -> None:
        self._dragging = True
        self._grab_dx = event.x_root - self.root.winfo_x()
        self._grab_dy = event.y_root - self.root.winfo_y()
        self.motion = self.planner.grab(self.motion)

    def _drag_move(self, event: tk.Event) -> None:
        if not self._dragging:
            return
        x, y = self.planner.clamp(event.x_root - self._grab_dx,
                                  event.y_root - self._grab_dy, self.work_area())
        self.motion = PetMotion(x=x, y=y, state='idle', facing=self.motion.facing)
        self._place()

    def _drag_end(self, _event: tk.Event) -> None:
        if not self._dragging:
            return
        self._dragging = False
        self.motion = self.planner.release(self.motion, self.work_area())

    def _show_menu(self, event: tk.Event) -> None:
        self._paused = True
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
            self._paused = False

    def _call(self, handler: Callable[[], None] | None) -> None:
        if handler is not None:
            handler()

    # ── 말풍선 ────────────────────────────────────────
    def say(self, text: str | None, *, hold_ms: int = BUBBLE_HOLD_MS) -> None:
        """달팽이가 말한다. 발화 내용은 services/speaker.py 가 정한다.

        hold_ms 뒤에 저절로 사라진다. 말풍선이 계속 떠 있으면 바탕화면을 가린다.
        """
        if self._closed:
            return
        self._bubble = text or None
        if self._bubble_after is not None:
            self._cancel(self._bubble_after)
            self._bubble_after = None
        if self._bubble and hold_ms > 0:
            self._bubble_after = self._after(hold_ms, lambda: self.say(None))
        if self._bubble and self.motion.state in ('idle', 'walk'):
            # 말할 때는 멈춰 선다. 걸어가면서 말풍선이 따라다니면 읽기 어렵다.
            self.motion = replace(self.motion, state='talk', target_x=None,
                                  target_y=None, hold_ticks=max(8, hold_ms // 400))
        self.draw()

    def call_later(self, delay_ms: int, fn: Callable[[], None]) -> None:
        """UI 스레드에서 나중에 부른다. 배경 스레드가 화면을 만지면 안 되므로
        모든 발화는 이 문을 지난다."""
        self._after(max(0, int(delay_ms)), fn)

    def _after(self, delay_ms: int, fn: Callable[[], None]) -> str | None:
        """취소할 수 있게 id 를 들고 있는 after."""
        if self._closed:
            return None

        def wrapped() -> None:
            self._after_ids.discard(handle)
            if not self._closed:
                fn()

        try:
            handle = self.root.after(delay_ms, wrapped)
        except tk.TclError:
            return None
        self._after_ids.add(handle)
        return handle

    # ── 틱 ────────────────────────────────────────────
    def step(self) -> None:
        """이동 한 틱. 테스트에서 직접 부를 수 있게 루프와 분리했다."""
        blocked = self._dragging or self._paused
        self.motion = self.planner.tick(self.motion, self.work_area(), blocked=blocked)
        if not blocked:
            self._place()

    def _roam_loop(self) -> None:
        if self._closed:
            return
        self.step()
        self._after(ROAM_INTERVAL_MS, self._roam_loop)

    def _draw_loop(self) -> None:
        if self._closed:
            return
        self.draw()
        self._after(DRAW_INTERVAL_MS, self._draw_loop)

    # ── 그리기 ────────────────────────────────────────
    def _elapsed_ms(self) -> int:
        """현재 상태가 시작된 뒤 흐른 시간. 프레임 번호를 여기서 뽑는다."""
        now = int(time.monotonic() * 1000)
        if self.motion.state != self._sprite_state:
            self._sprite_state = self.motion.state
            self._state_started_ms = now
        return now - self._state_started_ms

    def draw(self) -> None:
        """스프라이트가 있으면 그걸로, 없으면 벡터로."""
        if self._draw_sprite():
            if self._bubble:
                self._draw_bubble(self.canvas, self.size / BASE_SIZE)
            return
        self._draw_vector()

    def _draw_sprite(self) -> bool:
        """그렸으면 True. 한 상태라도 그림이 없으면 그 상태만 벡터로 내려간다."""
        if self.sprites is None:
            return False
        elapsed = self._elapsed_ms()
        frames = self.sprites.frames(self.motion.state, facing=self.motion.facing,
                                     size=self.size)
        if not frames:
            return False
        image = frames[frame_index(self.motion.state, elapsed) % len(frames)]
        c = self.canvas
        c.delete('all')
        # 이미지 참조는 캐시가 붙들고 있다. Tk 는 참조가 사라지면 그림을 회수한다.
        c.create_image(self.size // 2, self.size // 2, image=image)
        return True

    def _draw_vector(self) -> None:
        """벡터 폴백. 프레임이 없어도 앱이 동작해야 한다는 원칙의 바닥이다."""
        c = self.canvas
        c.delete('all')
        s = self.size / BASE_SIZE
        flip = self.motion.facing

        def px(x: float, y: float) -> tuple[float, float]:
            """원화 좌표(190 기준)를 실제 캔버스 좌표로. facing 이 1이면 좌우 반전."""
            cx = (BASE_SIZE - x) if flip > 0 else x
            return cx * s, y * s

        state = self.motion.state
        # 잘 때는 몸을 낮추고, 부딪히면 살짝 움츠린다.
        squash = {'sleep': 8, 'bump': 6}.get(state, 0)
        base_y = 150 - squash

        # 접지 그림자. 고정이라 몸만 움직여도 떠 보이지 않는다.
        x0, y0 = px(22, base_y + 12)
        x1, y1 = px(156, base_y + 24)
        c.create_oval(min(x0, x1), y0, max(x0, x1), y1,
                      fill=PALETTE['line'], outline='')

        # 발(몸통). 껍데기보다 앞으로 길게 빼야 달팽이로 읽힌다.
        # 전작처럼 껍데기 밑에 가두면 공 얹힌 웅덩이가 된다.
        foot = [px(24, base_y + 14), px(30, base_y - 6), px(52, base_y - 16),
                px(96, base_y - 18), px(146, base_y - 6), px(152, base_y + 10),
                px(140, base_y + 16), px(40, base_y + 16)]
        c.create_polygon([v for pt in foot for v in pt], fill=PALETTE['moss'],
                         outline=PALETTE['ink'], width=max(1, 2 * s), smooth=True)

        # 머리. 발 앞끝을 살짝 들어 올린다.
        hx0, hy0 = px(20, base_y - 20)
        hx1, hy1 = px(58, base_y + 10)
        c.create_oval(min(hx0, hx1), hy0, max(hx0, hx1), hy1,
                      fill=PALETTE['moss'], outline=PALETTE['ink'], width=max(1, 2 * s))

        # 껍데기 — 원화에서는 고정 레이어로 분리할 부분이다.
        sx0, sy0 = px(70, base_y - 68)
        sx1, sy1 = px(154, base_y + 8)
        c.create_oval(min(sx0, sx1), sy0, max(sx0, sx1), sy1,
                      fill=PALETTE['shell'], outline=PALETTE['ink'], width=max(1, 2 * s))
        ix0, iy0 = px(94, base_y - 46)
        ix1, iy1 = px(132, base_y - 12)
        c.create_oval(min(ix0, ix1), iy0, max(ix0, ix1), iy1,
                      fill='', outline=PALETTE['ink'], width=max(1, 2 * s))
        jx0, jy0 = px(106, base_y - 36)
        jx1, jy1 = px(122, base_y - 22)
        c.create_oval(min(jx0, jx1), jy0, max(jx0, jx1), jy1,
                      fill='', outline=PALETTE['ink'], width=max(1, 1.5 * s))

        # 눈자루와 눈. 머리에서 뻗는다.
        for tip_x, tip_y, root_x in ((22, base_y - 58, 30), (44, base_y - 66, 44)):
            rx, ry = px(root_x, base_y - 12)
            tx, ty = px(tip_x, tip_y)
            c.create_line(rx, ry, tx, ty, fill=PALETTE['ink'], width=max(1, 2 * s))
            e0, e1 = px(tip_x - 7, tip_y - 7), px(tip_x + 7, tip_y + 7)
            c.create_oval(min(e0[0], e1[0]), e0[1], max(e0[0], e1[0]), e1[1],
                          fill=PALETTE['paper'], outline=PALETTE['ink'], width=max(1, 1.5 * s))
            if state == 'sleep':
                l0, l1 = px(tip_x - 4, tip_y), px(tip_x + 4, tip_y)
                c.create_line(l0[0], l0[1], l1[0], l1[1],
                              fill=PALETTE['ink'], width=max(1, 1.5 * s))
            else:
                p0, p1 = px(tip_x - 3, tip_y - 3), px(tip_x + 3, tip_y + 3)
                c.create_oval(min(p0[0], p1[0]), p0[1], max(p0[0], p1[0]), p1[1],
                              fill=PALETTE['ink'], outline='')

        if state == 'read':
            k0, k1 = px(8, base_y - 2), px(44, base_y + 18)
            c.create_rectangle(min(k0[0], k1[0]), k0[1], max(k0[0], k1[0]), k1[1],
                               fill=PALETTE['paper'], outline=PALETTE['ink'],
                               width=max(1, 1.5 * s))
        if state == 'sleep':
            zx, zy = px(120, base_y - 86)
            c.create_text(zx, zy, text='z z', fill=PALETTE['ink_soft'],
                          font=font('caption', master=self.root))

        if self._bubble:
            self._draw_bubble(c, s)

    def _draw_bubble(self, c: tk.Canvas, s: float) -> None:
        """말풍선은 창 안에 갇힌다. 긴 발화는 별도 패널이 받는다(3단계)."""
        text = self._bubble if len(self._bubble) <= 40 else self._bubble[:39] + '…'
        pad = 8 * s
        item = c.create_text(self.size / 2, 22 * s, text=text, width=self.size - 4 * pad,
                             fill=PALETTE['ink'], font=font('bubble', master=self.root),
                             justify='center')
        x0, y0, x1, y1 = c.bbox(item)
        c.create_rectangle(x0 - pad, y0 - pad, x1 + pad, y1 + pad,
                           fill=PALETTE['paper'], outline=PALETTE['border'],
                           width=max(1, 1.5 * s))
        c.tag_raise(item)

    # ── 수명 ──────────────────────────────────────────
    def run(self) -> None:
        self._roam_loop()
        self._draw_loop()
        self.root.mainloop()

    def show_once(self, key: str, factory: Callable[[], object]) -> object:
        """같은 종류의 창을 두 번 열지 않는다. 이미 있으면 앞으로 끌어온다.

        기록 창을 두 번 열면 둘 다 같은 draft_key 를 쓴다. 양쪽에 글을 쓰고 닫으면
        **나중에 닫은 쪽이 앞의 글을 덮어쓴다.** 글을 잃지 않는다는 원칙이 깨진다.
        """
        panel = self._panels.get(key)
        top = getattr(panel, 'top', None)
        if top is not None:
            try:
                if top.winfo_exists():
                    top.deiconify()
                    top.lift()
                    top.focus_force()
                    return panel
            except tk.TclError:
                pass
        panel = factory()
        self._panels[key] = panel
        self._prune_panels()
        return panel

    def _prune_panels(self) -> None:
        """닫힌 창의 자리를 비운다. 책마다 키가 생기므로 그냥 두면 쌓인다."""
        for key, panel in list(self._panels.items()):
            top = getattr(panel, 'top', None)
            try:
                alive = top is not None and bool(top.winfo_exists())
            except tk.TclError:
                alive = False
            if not alive:
                self._panels.pop(key, None)

    def register_closer(self, closer: Callable[[], None]) -> None:
        """창이 닫히기 전에 불릴 정리 함수. 패널이 자기 초안을 저장할 기회다."""
        self._closers.append(closer)

    def unregister_closer(self, closer: Callable[[], None]) -> None:
        if closer in self._closers:
            self._closers.remove(closer)

    def _cancel(self, handle: str | None) -> None:
        if handle is None:
            return
        self._after_ids.discard(handle)
        try:
            self.root.after_cancel(handle)
        except tk.TclError:
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for handle in list(self._after_ids):
            self._cancel(handle)
        self._after_ids.clear()
        # 패널 먼저. 하나가 터져도 나머지는 저장 기회를 얻어야 한다.
        for closer in list(self._closers):
            try:
                closer()
            except Exception:
                pass
        self._closers.clear()
        self._panels.clear()
        # 스프라이트 이미지를 **root 를 부수기 전에** 놓아준다.
        # ImageTk.PhotoImage 는 회수될 때 자기 인터프리터에 'image delete' 를 보낸다.
        # 인터프리터가 먼저 사라지면 'main thread is not in main loop' 를 거쳐
        # 'Tcl_AsyncDelete' 로 프로세스가 죽는다. 폰트 캐시와 같은 부류다.
        if self.sprites is not None:
            self.sprites.invalidate()
        self._call(self.on_quit)
        try:
            self.root.destroy()
        except tk.TclError:
            pass
