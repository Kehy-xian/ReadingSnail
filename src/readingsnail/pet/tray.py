"""트레이 아이콘. 달팽이를 집에 보내고 다시 부른다.

스레드 규칙
    pystray 는 자기 스레드에서 돈다. **메뉴를 눌러도 Tk 를 직접 만지지 않는다** —
    큐에 넣고 UI 스레드가 꺼낸다. 전작 pet_window.py 가 쓰던 방식이고,
    이 프로젝트가 반복해서 데인 함정이기도 하다.

없으면 없는 대로
    pystray 가 없으면 트레이 기능만 빠진다. 앱은 그대로 뜬다.
"""

from __future__ import annotations

import queue
import threading
from typing import Any

APP_NAME = 'ReadingSnail'
TITLE = '책 읽는 달팽이'

RESTORE = 'restore'
QUIT = 'quit'


def pystray_available() -> bool:
    try:
        import pystray  # noqa: F401
    except Exception:
        return False
    return True


def _icon_image(size: int = 64):
    """트레이에 쓸 작은 달팽이. 스프라이트가 없어도 되게 직접 그린다."""
    from PIL import Image, ImageDraw

    from ..theme import PALETTE

    def rgb(value: str) -> tuple[int, int, int]:
        value = value.lstrip('#')
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))

    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    ink = rgb(PALETTE['ink'])
    draw.ellipse([size * 0.06, size * 0.55, size * 0.94, size * 0.86],
                 fill=rgb(PALETTE['moss']), outline=ink, width=2)
    draw.ellipse([size * 0.34, size * 0.16, size * 0.94, size * 0.76],
                 fill=rgb(PALETTE['shell']), outline=ink, width=2)
    draw.ellipse([size * 0.52, size * 0.34, size * 0.76, size * 0.58],
                 outline=ink, width=2)
    for x, y in ((size * 0.14, size * 0.30), (size * 0.28, size * 0.22)):
        draw.line([x + 4, size * 0.62, x, y], fill=ink, width=2)
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=ink)
    return image


class TrayIcon:
    """트레이에 아이콘을 올린다. 눌린 것은 큐로만 알린다."""

    def __init__(self, *, on_event=None):
        self.events: queue.Queue[str] = queue.Queue()
        self.on_event = on_event
        self._icon: Any = None
        self._thread: threading.Thread | None = None

    @property
    def visible(self) -> bool:
        return self._icon is not None

    def show(self) -> bool:
        """올렸으면 True. pystray 가 없거나 실패하면 False — 앱은 계속 돈다."""
        if self._icon is not None:
            return True
        try:
            import pystray
        except Exception:
            return False
        try:
            menu = pystray.Menu(
                pystray.MenuItem('돌아오기', lambda _i, _m: self._emit(RESTORE),
                                 default=True),
                pystray.MenuItem('종료', lambda _i, _m: self._emit(QUIT)),
            )
            icon = pystray.Icon(APP_NAME, _icon_image(), TITLE, menu)
        except Exception:
            return False

        self._icon = icon
        self._thread = threading.Thread(target=self._run, name='tray', daemon=True)
        self._thread.start()
        return True

    def _run(self) -> None:
        try:
            self._icon.run()
        except Exception:
            pass

    def _emit(self, event: str) -> None:
        """**pystray 스레드에서 불린다.** Tk 를 건드리지 않는다."""
        self.events.put(event)
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:
                pass

    def drain(self) -> list[str]:
        """UI 스레드가 꺼낸다."""
        out: list[str] = []
        try:
            while True:
                out.append(self.events.get_nowait())
        except queue.Empty:
            pass
        return out

    def hide(self) -> None:
        icon, self._icon = self._icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
