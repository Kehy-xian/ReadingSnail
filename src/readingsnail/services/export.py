"""기록 내보내기. **선택 기능이 아니다**(SPEC 1항).

왜 필수인가
    데이터 락인을 만들지 않기 위해서다. 이 앱을 그만 쓰기로 해도 몇 년치 기록을
    들고 나갈 수 있어야 한다. 그게 보장돼야 마음 놓고 기록을 쌓는다.

형식
    Markdown  사람이 읽는 것. 책별로 묶고 시간순으로 편다. 옵시디언·노션에 붙는다.
    CSV       표 계산기로 여는 것. 한 줄에 기록 하나.

    CSV 는 **UTF-8 BOM** 을 붙인다. 안 붙이면 엑셀에서 한글이 깨진다.

수식 주입을 막는다
    '=' 나 '+' 로 시작하는 칸을 엑셀은 **수식으로 해석한다.** 기록에는 웹에서
    붙여넣은 글이 섞이므로 `=cmd|"/c calc"!A1` 같은 것이 들어올 수 있고,
    그 CSV 를 동료에게 보내면 그 사람 컴퓨터에서 실행된다.

    그런 칸 앞에 작은따옴표를 붙인다. 엑셀은 그것을 '이건 글자다'라는 표시로
    읽고 화면에 보여주지 않는다. **Markdown 쪽은 건드리지 않는다** — 거기서는
    수식이 실행될 일이 없고, 기록은 쓴 그대로 남아야 한다.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path

CSV_COLUMNS = ('created_at', 'kind', 'book_title', 'book_author', 'page',
               'body', 'book_status', 'isbn13', 'entry_id', 'book_id')
KIND_KO = {'quote': '필사', 'note': '생각'}
STATUS_KO = {'reading': '읽는 중', 'completed': '다 읽음',
             'wishlist': '읽고 싶은', 'paused': '잠시 멈춤'}

# 엑셀·리브레오피스가 수식으로 읽기 시작하는 글자들.
_FORMULA_LEAD = ('=', '+', '-', '@', '\t', '\r')


def _csv_safe(value: object) -> str:
    """엑셀이 수식으로 해석하지 않게 한다. 화면에 보이는 내용은 그대로다."""
    text = '' if value is None else str(value)
    if text[:1] in _FORMULA_LEAD:
        return "'" + text
    return text


def _rows(journal, *, limit: int = 100_000):
    """(book, entry) 쌍을 책별·시간순으로. 책 없는 기록은 마지막에."""
    books = {b.book_id: b for b in journal.list_books(limit=limit)}
    for book in books.values():
        for entry in journal.entries_for_book(book.book_id, limit=limit):
            yield book, entry
    loose = [e for e in journal.recent_entries(limit=limit) if e.book_id is None]
    for entry in sorted(loose, key=lambda e: e.created_at):
        yield None, entry


def to_markdown(journal, *, title: str = '책 읽는 달팽이 — 기록',
                limit: int = 100_000) -> str:
    """사람이 읽는 형식. 책별로 묶고 시간순으로 편다."""
    out: list[str] = [f'# {title}', '']
    out.append(f'내보낸 날짜: {datetime.now(timezone.utc).strftime("%Y-%m-%d")}')
    out.append(f'책 {journal.count_books()}권 · 기록 {journal.count_entries()}건')
    out.append('')

    current: object = object()
    for book, entry in _rows(journal, limit=limit):
        key = book.book_id if book else None
        if key != current:
            current = key
            out.append('')
            if book is None:
                out.append('## (책 없는 기록)')
            else:
                heading = book.title
                if book.author:
                    heading += f' — {book.author}'
                out.append(f'## {heading}')
                meta = [STATUS_KO.get(book.status, book.status)]
                if book.publisher:
                    meta.append(book.publisher)
                if book.isbn13:
                    meta.append(f'ISBN {book.isbn13}')
                out.append(f'*{" · ".join(meta)}*')
            out.append('')

        head = entry.created_at[:10]
        if entry.page:
            head += f' · {entry.page}'
        head += f' · {KIND_KO.get(entry.kind, entry.kind)}'
        out.append(f'**{head}**')
        out.append('')
        if entry.kind == 'quote':
            # 필사한 문장은 인용으로. 여러 줄이면 줄마다 인용 부호를 붙인다.
            for line in entry.body.splitlines() or ['']:
                out.append(f'> {line}')
        else:
            out.append(entry.body)
        out.append('')
    return '\n'.join(out).rstrip() + '\n'


def to_csv(journal, *, limit: int = 100_000) -> str:
    """표 계산기로 여는 형식. 한 줄에 기록 하나."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(CSV_COLUMNS)
    for book, entry in _rows(journal, limit=limit):
        writer.writerow([_csv_safe(v) for v in (
            entry.created_at,
            KIND_KO.get(entry.kind, entry.kind),
            book.title if book else '',
            book.author if book else '',
            entry.page or '',
            entry.body,
            STATUS_KO.get(book.status, '') if book else '',
            (book.isbn13 or '') if book else '',
            entry.entry_id,
            entry.book_id or '',
        )])
    return buffer.getvalue()


def write_markdown(journal, path: str | Path, **kw) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_markdown(journal, **kw), encoding='utf-8')
    return target


def write_csv(journal, path: str | Path, **kw) -> Path:
    """UTF-8 BOM 을 붙인다. 안 붙이면 엑셀에서 한글이 깨진다."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_csv(journal, **kw), encoding='utf-8-sig')
    return target


def suggested_name(kind: str = 'md') -> str:
    stamp = datetime.now().strftime('%Y%m%d')
    return f'책읽는달팽이-기록-{stamp}.{kind}'
