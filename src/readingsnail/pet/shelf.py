"""책장 배치. **계산은 순수 함수, 그리기는 따로.**

배치를 순수 함수로 두면 화면 없이 검증할 수 있다. 이동 로직(pet/behavior.py)과
같은 태도다.

SPEC 5항이 요구하는 것
    · 책등은 템플릿 5~6종 × 표지 추출 색 tint
    · 기울어진 책 1~2권, 눕힌 책 1권을 섞어 **정돈감을 깬다**
    · 완독 권수에 따라 선반이 아래로 늘어남
    · 책 클릭 → 그 책의 기록 타임라인

흐트러뜨리되 흔들리지 않게
    기울임과 눕힘은 book_id 해시로 정한다. 무작위로 하면 창을 열 때마다
    책이 춤춘다. 같은 책은 언제 열어도 같은 자세다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

SPINE_TEMPLATES = 6          # spine_0.png ~ spine_5.png
SPINE_WIDTH = 34             # 세워 꽂은 책등의 너비
SPINE_HEIGHT = 132           # 세워 꽂은 책등의 높이
LYING_HEIGHT = 26            # 눕힌 책의 두께
SHELF_THICKNESS = 10         # 선반 판 두께
SHELF_GAP = 26               # 선반과 선반 사이 여백
BOOK_GAP = 4                 # 책 사이 간격
SIDE_PAD = 16                # 책장 좌우 여백

# 기울임 각도. 너무 크면 쓰러져 보인다.
TILT_DEGREES = 8


@dataclass(frozen=True)
class Slot:
    """책 한 권이 놓일 자리. 좌표는 캔버스 기준, 원점은 왼쪽 위."""

    book_id: str
    title: str
    x: int
    y: int                    # 책등 위쪽
    width: int
    height: int
    tint: str | None
    template: int
    tilt: int                 # 도 단위. 0 이면 똑바로
    lying: bool               # 눕혀 놓았는가

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass(frozen=True)
class Shelf:
    """선반 한 층."""

    index: int
    top: int                  # 책이 놓이는 바닥선
    left: int
    right: int

    @property
    def board_top(self) -> int:
        return self.top


def _seed(book_id: str) -> int:
    """같은 책은 언제나 같은 자세. 창을 열 때마다 춤추지 않게 한다."""
    return int(hashlib.sha1(str(book_id).encode('utf-8')).hexdigest()[:8], 16)


def pose_for(book_id: str, *, allow_lying: bool = True) -> tuple[int, bool]:
    """(기울기, 눕힘). 정돈감을 깨되 규칙은 고정한다."""
    seed = _seed(book_id)
    bucket = seed % 16
    if allow_lying and bucket == 0:
        return 0, True                      # 16권에 한 권쯤 눕는다
    if bucket in (1, 2):
        return TILT_DEGREES, False
    if bucket in (3, 4):
        return -TILT_DEGREES, False
    return 0, False


def layout(books, *, width: int, top: int = SIDE_PAD,
           spine_width: int = SPINE_WIDTH,
           spine_height: int = SPINE_HEIGHT) -> tuple[list[Shelf], list[Slot]]:
    """책들을 선반에 꽂는다. (선반 목록, 자리 목록).

    books 는 book_id / title / spine_tint / spine_style 을 가진 것이면 된다.
    저장소 타입에 묶이지 않게 덕 타이핑으로 받는다.
    """
    usable = max(spine_width, int(width) - SIDE_PAD * 2)
    shelves: list[Shelf] = []
    slots: list[Slot] = []

    cursor_x = SIDE_PAD
    shelf_index = 0
    baseline = int(top) + spine_height

    def open_shelf() -> None:
        shelves.append(Shelf(index=shelf_index, top=baseline,
                             left=SIDE_PAD, right=SIDE_PAD + usable))

    open_shelf()
    for book in books:
        book_id = str(getattr(book, 'book_id', '') or '')
        title = str(getattr(book, 'title', '') or '')
        tilt, lying = pose_for(book_id)
        item_w = spine_height if lying else spine_width
        item_h = LYING_HEIGHT if lying else spine_height

        if cursor_x + item_w > SIDE_PAD + usable and slots:
            # 선반이 찼다. 아래로 한 층 늘린다.
            shelf_index += 1
            baseline += spine_height + SHELF_THICKNESS + SHELF_GAP
            cursor_x = SIDE_PAD
            open_shelf()

        slots.append(Slot(
            book_id=book_id, title=title,
            x=cursor_x, y=baseline - item_h,
            width=item_w, height=item_h,
            tint=getattr(book, 'spine_tint', None),
            template=int(getattr(book, 'spine_style', 0) or 0) % SPINE_TEMPLATES,
            tilt=tilt, lying=lying,
        ))
        cursor_x += item_w + BOOK_GAP

    return shelves, slots


def canvas_height(shelves: list[Shelf]) -> int:
    """스크롤 영역 높이. 마지막 선반 판까지 담는다."""
    if not shelves:
        return SPINE_HEIGHT + SHELF_THICKNESS + SIDE_PAD * 2
    return shelves[-1].top + SHELF_THICKNESS + SIDE_PAD


def slot_at(slots: list[Slot], x: int, y: int) -> Slot | None:
    """클릭한 자리의 책. 기울기는 판정에 넣지 않는다 — 몇 픽셀 차이로
    안 눌리는 것보다 넉넉히 잡히는 편이 낫다."""
    for slot in reversed(slots):
        if slot.x <= x <= slot.x + slot.width and slot.y <= y <= slot.bottom:
            return slot
    return None
