"""달팽이가 무슨 말을 할지 정한다. dialogue.py 의 가중치를 실제 기록에 연결한다.

dialogue.py 는 '어느 갈래를 고를까'만 안다. 여기서 그 갈래에 실제로 꺼낼 것이
있는지 저장소에 물어보고, 최근에 한 말은 빼고, 문장으로 만든다.

지키는 것 (SPEC 3항)
    · 최근 RECENT_BLOCK 회 안에 나온 항목은 다시 뽑지 않는다.
      같은 문장을 이틀 연속 보면 그 순간 인형이 된다.
    · 꺼낼 게 없는 갈래는 아예 후보에서 뺀다. 빈 갈래가 뽑히면 침묵이 된다.
    · **죄책감을 자극하지 않는다.** '3일째 안 읽으셨네요' 류는 넣지 않는다.
      기록이 없으면 말수가 줄어들 뿐이다.
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass

from ..storage.journal import Journal, utc_now
from . import dialogue
from .dialogue import RECENT_BLOCK, Channel, Utterance


@dataclass(frozen=True)
class Spoken:
    utterance: Utterance
    entry_id: str | None = None
    book_id: str | None = None


def recent_refs(conn: sqlite3.Connection, *, limit: int = RECENT_BLOCK) -> set[str]:
    """최근에 말한 항목들. 이만큼은 다시 꺼내지 않는다."""
    rows = conn.execute(
        'SELECT ref_id FROM utterance_log ORDER BY said_at DESC, rowid DESC LIMIT ?',
        (int(limit),)).fetchall()
    return {str(r['ref_id']) for r in rows}


def log_utterance(conn: sqlite3.Connection, channel: Channel, ref_id: str) -> None:
    conn.execute(
        'INSERT INTO utterance_log(said_at, channel, ref_id) VALUES (?,?,?)',
        (utc_now(), channel.value, str(ref_id)))


def prune_utterance_log(conn: sqlite3.Connection, *, keep: int = 500) -> None:
    """오래된 발화 이력을 버린다. 최근 몇 개만 쓰는데 무한히 쌓을 이유가 없다."""
    conn.execute(
        'DELETE FROM utterance_log WHERE rowid NOT IN '
        '(SELECT rowid FROM utterance_log ORDER BY said_at DESC, rowid DESC LIMIT ?)',
        (int(keep),))


class Speaker:
    """한 마디를 고르고, 말한 것을 기록해 다음에 겹치지 않게 한다."""

    def __init__(self, journal: Journal, *, rng: random.Random | None = None,
                 stalled_days: int = dialogue.STALLED_DAYS):
        self.journal = journal
        self.rng = rng or random.Random()
        self.stalled_days = int(stalled_days)

    # ── 후보 모으기 ───────────────────────────────────
    def _candidates(self, conn: sqlite3.Connection, blocked: set[str]) -> dict[Channel, list]:
        """갈래마다 지금 꺼낼 수 있는 것들. 비어 있는 갈래는 키 자체를 만들지 않는다."""
        found: dict[Channel, list] = {}

        entries = [e for e in self.journal.recent_entries(limit=200)
                   if e.entry_id not in blocked]
        notes = [e for e in entries if e.kind == 'note']
        quotes = [e for e in entries if e.kind == 'quote']
        if notes:
            found[Channel.MY_NOTE] = notes
        if quotes:
            found[Channel.BOOK_QUOTE] = quotes

        wishlist = [b for b in self.journal.list_books(status='wishlist', limit=50)
                    if b.book_id not in blocked]
        if wishlist:
            found[Channel.WISHLIST] = wishlist

        stalled = [b for b in self.journal.stalled_books(days=self.stalled_days, limit=20)
                   if b.book_id not in blocked]
        if stalled:
            found[Channel.STALLED] = stalled

        rows = conn.execute(
            'SELECT quote_id, body, source FROM quotes').fetchall()
        sayable = [r for r in rows if str(r['quote_id']) not in blocked]
        if sayable:
            found[Channel.QUOTE] = sayable
        return found

    # ── 한 마디 ───────────────────────────────────────
    def speak(self, conn: sqlite3.Connection) -> Spoken | None:
        """지금 할 말. 없으면 None — 그때는 조용히 있는다."""
        blocked = recent_refs(conn)
        pool = self._candidates(conn, blocked)
        if not pool:
            # 최근 발화 제외 때문에 다 막힌 경우가 있다. 그때는 제외를 풀고 한 번 더.
            pool = self._candidates(conn, set())
            if not pool:
                return None

        note_count = self.journal.count_entries()
        channel = dialogue.pick_channel(note_count, set(pool), rng=self.rng)
        if channel is None:
            return None

        picked = self.rng.choice(pool[channel])
        spoken = self._render(channel, picked)
        if spoken is not None and spoken.utterance.ref_id:
            # ref_id 를 쓴다. entry_id/book_id 로 하면 명언이 둘 다 없어서
            # 이력에 안 남고, 그러면 같은 명언이 계속 반복된다.
            log_utterance(conn, channel, spoken.utterance.ref_id)
        return spoken

    def _render(self, channel: Channel, picked) -> Spoken | None:
        if channel in (Channel.MY_NOTE, Channel.BOOK_QUOTE):
            text = dialogue.render(channel, body=picked.body)
            return Spoken(Utterance(channel, picked.entry_id, text),
                          entry_id=picked.entry_id, book_id=picked.book_id)
        if channel in (Channel.WISHLIST, Channel.STALLED):
            text = dialogue.render(channel, title=picked.title)
            return Spoken(Utterance(channel, picked.book_id, text), book_id=picked.book_id)
        if channel is Channel.QUOTE:
            quote_id = str(picked['quote_id'])
            text = dialogue.render(channel, body=str(picked['body']),
                                   source=str(picked['source']))
            return Spoken(Utterance(channel, quote_id, text))
        return None

    # ── 되살리기 한 마디 ──────────────────────────────
    def echo(self, conn: sqlite3.Connection, recalled) -> Spoken:
        """의미 검색이 찾아준 과거 기록을 말로 만든다.

        무작위 추출과 체감이 갈리는 지점이라 갈래는 늘 MY_NOTE 로 둔다.
        """
        channel = Channel.MY_NOTE if recalled.entry.kind == 'note' else Channel.BOOK_QUOTE
        text = dialogue.render(channel, body=recalled.entry.body)
        log_utterance(conn, channel, recalled.entry.entry_id)
        return Spoken(Utterance(channel, recalled.entry.entry_id, text),
                      entry_id=recalled.entry.entry_id, book_id=recalled.entry.book_id)
