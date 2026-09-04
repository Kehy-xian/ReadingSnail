"""달팽이 발화 선택.

네 갈래에서 가중치로 뽑되, 최근에 말한 것은 다시 뽑지 않는다.
기록이 적은 초기에는 명언 비중을 자동으로 올려 콜드 스타트를 넘긴다.

BookEater의 dialogue.py와 달리 진화 노선(route_a/b/c) 개념이 없다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum


class Channel(str, Enum):
    MY_NOTE = 'my_note'        # 내 기록·감상
    BOOK_QUOTE = 'book_quote'  # 필사한 책 문장
    WISHLIST = 'wishlist'      # 위시리스트 책 제목
    QUOTE = 'quote'            # 독서 명언
    STALLED = 'stalled'        # 읽는 중인데 한동안 기록이 없는 책


BASE_WEIGHTS: dict[Channel, float] = {
    Channel.MY_NOTE: 35,
    Channel.BOOK_QUOTE: 30,
    Channel.WISHLIST: 15,
    Channel.QUOTE: 10,
    Channel.STALLED: 10,
}

# 최근 이만큼의 발화에 등장한 ref_id는 다시 뽑지 않는다.
RECENT_BLOCK = 12

# 이 일수 이상 기록이 없는 '읽는 중' 책을 정체 상태로 본다.
STALLED_DAYS = 7


@dataclass(frozen=True)
class Utterance:
    channel: Channel
    ref_id: str
    text: str


def effective_weights(note_count: int) -> dict[Channel, float]:
    """기록이 적을수록 명언에 기대고, 쌓일수록 내 기록으로 무게를 옮긴다."""
    w = dict(BASE_WEIGHTS)
    if note_count == 0:
        return {Channel.QUOTE: 1.0}
    if note_count < 5:
        w[Channel.QUOTE] = 45
        w[Channel.MY_NOTE] = 15
        w[Channel.BOOK_QUOTE] = 10
    elif note_count < 20:
        w[Channel.QUOTE] = 25
        w[Channel.MY_NOTE] = 28
        w[Channel.BOOK_QUOTE] = 22
    return w


def pick_channel(note_count: int, available: set[Channel],
                 rng: random.Random | None = None) -> Channel | None:
    """비어 있는 갈래는 제외하고 가중치 추첨."""
    rng = rng or random
    pool = {c: w for c, w in effective_weights(note_count).items()
            if c in available and w > 0}
    if not pool:
        return None
    return rng.choices(list(pool), weights=list(pool.values()), k=1)[0]


# ── 말투 ──────────────────────────────────────────────
# 달팽이는 조용하고 느리다. 재촉하지 않는다.
# "3일째 안 읽으셨네요" 같은 죄책감 자극은 넣지 않는다.

FRAMES: dict[Channel, tuple[str, ...]] = {
    Channel.MY_NOTE: (
        '{body}\n\n…예전에 네가 남긴 말이야.',
        '문득 이게 떠올랐어.\n\n{body}',
    ),
    Channel.BOOK_QUOTE: (
        '{body}',
        '이 문장, 아직 안 잊었어.\n\n{body}',
    ),
    Channel.WISHLIST: (
        '{title}… 언젠가 읽을 거라고 했잖아.',
        '{title}, 아직 기다리고 있어.',
    ),
    Channel.QUOTE: (
        '{body}\n— {source}',
    ),
    Channel.STALLED: (
        '{title}, 어디까지 읽었더라?',
        '{title}는 아직 껍데기 밖에 있어.',
    ),
}


def render(channel: Channel, **fields: str) -> str:
    rng = random
    return rng.choice(FRAMES[channel]).format(**fields)


# ── 의미 검색 연동 지점 ───────────────────────────────
# 방금 저장한 기록의 임베딩으로 과거 기록 중 가장 가까운 것을 찾아
# MY_NOTE 채널로 뱉는다. 무작위 추출과 여기서 체감 차이가 난다.
# 구현은 services/recall.py 참조 (TODO).
ECHO_DELAY_SEC = (90, 300)   # 저장 직후 이 범위에서 무작위 지연
ECHO_MIN_SIMILARITY = 0.72   # 이보다 낮으면 억지 연결이므로 뱉지 않는다
