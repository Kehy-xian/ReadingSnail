"""python -m readingsnail

부팅 순서가 중요하다.
  1. DPI 인식 — Tk 를 만들기 전에 해야 좌표가 어긋나지 않는다(Windows).
  2. DB 열기 — 스키마 적용과 명언 시드까지.
  3. 전작 기록 확인 — 있으면 물어보고 옮긴다.
  4. 창 띄우기.

DB 를 못 열면 창을 띄우지 않는다. 기록을 저장할 수 없는 채로 돌아다니는 달팽이는
사용자를 속이는 것이다.
"""

from __future__ import annotations

import random
import sys

from .paths import default_db_path, legacy_db_path
from .services import dialogue
from .storage.db import StorageError, open_database
from .storage.drafts import Drafts
from .storage.journal import Journal
from .storage.migrate import MigrationError, legacy_looks_migratable, migrate


def _first_words(journal: Journal, conn) -> str | None:
    """켤 때 한마디. 기록이 없으면 명언으로 콜드 스타트를 넘긴다."""
    count = journal.count_entries()
    available = set()
    if count:
        available.add(dialogue.Channel.MY_NOTE)
    row = conn.execute(
        'SELECT body, source FROM quotes ORDER BY random() LIMIT 1').fetchone()
    if row is not None:
        available.add(dialogue.Channel.QUOTE)

    channel = dialogue.pick_channel(count, available)
    if channel is dialogue.Channel.QUOTE and row is not None:
        return dialogue.render(channel, body=str(row['body']), source=str(row['source']))
    if channel is dialogue.Channel.MY_NOTE:
        recent = journal.recent_entries(limit=20)
        if recent:
            return dialogue.render(channel, body=random.choice(recent).body)
    return None


# 전작 기록 이전을 거절한 횟수. 이만큼 거절하면 더 묻지 않는다.
DECLINE_KEY = 'migration_declined'
MAX_ASKS = 3


def _offer_migration(root, db) -> None:
    """전작 기록이 있으면 옮길지 물어본다. 원본은 읽기만 한다."""
    from tkinter import messagebox
    from .storage.migrate import MIGRATION_MARKER

    if db.get_meta(MIGRATION_MARKER):
        return
    source = legacy_db_path()
    if not legacy_looks_migratable(source):
        return
    # 거절해도 다음에 한 번 더 묻되, 계속 묻지는 않는다.
    # 매번 물으면 잔소리가 되고, 한 번에 막으면 실수로 거절한 사람이 영영 못 옮긴다.
    declined = int(db.get_meta(DECLINE_KEY, '0') or 0)
    if declined >= MAX_ASKS:
        return
    if not messagebox.askyesno(
            '책 읽는 달팽이',
            '전작 「책먹는 몬스터」의 기록이 있습니다.\n'
            '책과 기록을 가져올까요?\n\n'
            '(원본은 읽기만 하며 바뀌지 않습니다.)', parent=root):
        db.set_meta(DECLINE_KEY, str(declined + 1))
        return
    try:
        report = migrate(db, source)
    except MigrationError as exc:
        messagebox.showerror('책 읽는 달팽이', f'가져오지 못했습니다.\n{exc}', parent=root)
        return
    note = report.summary()
    if report.covers_to_fetch:
        note += '\n표지는 다시 내려받아야 합니다.'
    messagebox.showinfo('책 읽는 달팽이', f'가져왔습니다.\n{note}', parent=root)


def main(argv: list[str] | None = None) -> int:
    from .pet.window import PetWindow, enable_dpi_awareness

    enable_dpi_awareness()          # Tk 보다 먼저

    try:
        db = open_database(default_db_path())
    except StorageError as exc:
        print(f'기록을 열 수 없습니다: {exc}', file=sys.stderr)
        return 1

    journal = Journal(db)
    drafts = Drafts(db)

    def on_write() -> None:
        from .pet.panels import WritePanel
        WritePanel(pet.root, journal, drafts, owner=pet)

    def on_library() -> None:
        from .pet.panels import LibraryPanel
        LibraryPanel(pet.root, journal)

    pet = PetWindow(on_write=on_write, on_library=on_library, on_quit=db.close)
    _offer_migration(pet.root, db)
    with db.connect() as conn:
        pet.say(_first_words(journal, conn))
    pet.run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
