"""주간 요약. **알림으로 띄우지 않는다**(SPEC 6항).

기록장 안의 탭이다. 사용자가 보러 왔을 때만 보인다.
읽으라고 재촉하지 않는다 — 이번 주에 무엇을 했는지 보여줄 뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..storage.journal import TIME_FORMAT


@dataclass(frozen=True)
class WeekSummary:
    start: str
    end: str
    entries: int
    quotes: int
    notes: int
    finished: list[tuple[str, str]] = field(default_factory=list)   # (제목, 저자)
    active: list[tuple[str, int]] = field(default_factory=list)     # (제목, 기록 수)
    total_entries: int = 0
    total_finished: int = 0

    @property
    def quiet(self) -> bool:
        return self.entries == 0 and not self.finished


def week_bounds(now: datetime | None = None, *, days: int = 7) -> tuple[str, str]:
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(days=int(days))
    return start.strftime(TIME_FORMAT), end.strftime(TIME_FORMAT)


def summarize(journal, *, now: datetime | None = None, days: int = 7) -> WeekSummary:
    start, end = week_bounds(now, days=days)
    db = journal.db

    with db.connect() as con:
        counts = con.execute(
            'SELECT kind, count(*) AS n FROM entries '
            'WHERE created_at >= ? AND created_at <= ? GROUP BY kind',
            (start, end)).fetchall()
        by_kind = {str(r['kind']): int(r['n']) for r in counts}

        finished = con.execute(
            "SELECT title, author FROM books WHERE status='completed' "
            'AND finished_at IS NOT NULL AND finished_at >= ? AND finished_at <= ? '
            'ORDER BY finished_at DESC LIMIT 20', (start, end)).fetchall()

        active = con.execute(
            'SELECT b.title AS title, count(e.entry_id) AS n FROM entries e '
            'JOIN books b ON b.book_id = e.book_id '
            'WHERE e.created_at >= ? AND e.created_at <= ? '
            'GROUP BY e.book_id ORDER BY n DESC LIMIT 5', (start, end)).fetchall()

    return WeekSummary(
        start=start, end=end,
        entries=sum(by_kind.values()),
        quotes=by_kind.get('quote', 0),
        notes=by_kind.get('note', 0),
        finished=[(str(r['title']), str(r['author'] or '')) for r in finished],
        active=[(str(r['title']), int(r['n'])) for r in active],
        total_entries=journal.count_entries(),
        total_finished=journal.count_books(status='completed'),
    )


def as_lines(summary: WeekSummary) -> list[str]:
    """화면에 그대로 뿌릴 수 있는 줄들. 재촉하는 말은 넣지 않는다."""
    lines = [f'{summary.start[:10]} ~ {summary.end[:10]}', '']
    if summary.quiet:
        lines.append('이번 주는 조용했습니다.')
        lines.append('')
    else:
        lines.append(f'기록 {summary.entries}건'
                     f'  (필사 {summary.quotes} · 생각 {summary.notes})')
        if summary.finished:
            lines.append(f'다 읽은 책 {len(summary.finished)}권')
            for title, author in summary.finished:
                lines.append(f'  · {title}{" — " + author if author else ""}')
        if summary.active:
            lines.append('')
            lines.append('이어 읽는 중')
            for title, count in summary.active:
                lines.append(f'  · {title}  ({count}건)')
        lines.append('')
    lines.append(f'전체 기록 {summary.total_entries}건 · 다 읽은 책 {summary.total_finished}권')
    return lines
