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

import queue
import random
import sqlite3
import sys
import threading
from collections import OrderedDict

from .nlp.encoder import default_encoder
from .paths import (default_data_dir, default_db_path, legacy_db_path,
                    readonly_uri, resource_root)
from .services import dialogue, recall
from .services import autostart, backup, single_instance
from .services.catalog import build_source
from .services.covers import attach_cover
from .services.embedding import EmbeddingWorker
from .services.speaker import Speaker, prune_utterance_log
from .storage.db import StorageError, open_database
from .storage.drafts import Drafts
from .storage.journal import Journal
from .storage.migrate import MigrationError, legacy_looks_migratable, migrate
from .storage.settings import Settings
from .theme import load_bundled_fonts

# 주기적으로 한 마디. 너무 잦으면 잔소리가 된다.
SPEAK_EVERY_MS = 6 * 60 * 1000

# 달팽이에게 얹을 소품. 쉼표로 구분한 이름들.
SETTING_PROPS = 'pet.props'
SETTING_SCALE = 'pet.scale'
SETTING_VERSION = 'app.version'

# 트레이 이벤트를 확인하는 주기.
TRAY_POLL_MS = 400


class Companion:
    """달팽이가 말하는 리듬을 쥔다.

    두 가지 말이 있다.
      · 주기적 발화 — 4갈래에서 뽑는다. SPEAK_EVERY_MS 마다.
      · 되살리기 — 기록을 저장하고 90~300초 뒤(SPEC 3항), 방금 쓴 글과 가장
        비슷한 과거 기록을 뱉는다. 무작위 추출과 체감이 갈리는 지점이다.

    스레드 규칙 — 여기가 이 클래스의 존재 이유다
        tkinter 는 **인터프리터를 만든 스레드에서만** 안전하다. root.after 조차
        다른 스레드에서 부르면 안 된다(전작이 queue 를 쓴 이유가 그것이다).

        그래서 배경에서 만든 말은 큐에 넣고, UI 스레드가 _pump 로 꺼내 말한다.
        무거운 계산(인코딩, 최근접 탐색)은 전부 배경에서 한다. 최근접 탐색은
        기록 5,000건에 0.3초쯤 걸리는데, UI 스레드에서 하면 그만큼 창이 얼어붙는다.
    """

    PUMP_MS = 250

    def __init__(self, pet, db, journal: Journal, encoder):
        self.pet = pet
        self.db = db
        self.journal = journal
        self.speaker = Speaker(journal)
        self.worker = EmbeddingWorker(journal, encoder, on_done=self._encoded)
        self.model = self.worker.model

        self._say_queue: queue.Queue[str] = queue.Queue()
        self._timers: set[threading.Timer] = set()
        self._timer_lock = threading.Lock()
        self._echoed: OrderedDict[str, None] = OrderedDict()
        self._stopped = False

    # ── 수명 ──────────────────────────────────────────
    def start(self) -> None:
        self.worker.start()
        self._pump()
        self._speak_loop()

    def stop(self) -> None:
        """타이머를 세우고 **합류까지 기다린다.**

        기다리지 않으면 아직 도는 타이머 스레드가 Companion 의 마지막 참조를
        쥔 채 끝나고, 거기서 Tk 객체가 회수되면 인터프리터가
        'Tcl_AsyncDelete: async handler deleted by the wrong thread' 로 죽는다.
        """
        self._stopped = True
        with self._timer_lock:
            timers = list(self._timers)
            self._timers.clear()
        for timer in timers:
            timer.cancel()
        for timer in timers:
            timer.join(timeout=2.0)
        self.worker.stop()

    # ── UI 스레드 ─────────────────────────────────────
    def _pump(self) -> None:
        """배경이 만들어 둔 말을 꺼내 말한다. **UI 스레드에서만 돈다.**"""
        if self._stopped:
            return
        try:
            while True:
                self.pet.say(self._say_queue.get_nowait())
        except queue.Empty:
            pass
        self.pet.call_later(self.PUMP_MS, self._pump)

    def _speak_loop(self) -> None:
        if self._stopped:
            return
        self._say_now()
        self.pet.call_later(SPEAK_EVERY_MS, self._speak_loop)

    def _say_now(self) -> None:
        try:
            with self.db.write() as conn:
                spoken = self.speaker.speak(conn)
                prune_utterance_log(conn)
        except sqlite3.DatabaseError:
            return
        if spoken is not None:
            self.pet.say(spoken.utterance.text)

    # ── 되살리기 ──────────────────────────────────────
    def note_saved(self) -> None:
        """기록 창이 저장을 마쳤다. 인코딩을 깨운다."""
        self.worker.wake()

    def _encoded(self, entry_id: str) -> None:
        """**배경 스레드에서 불린다.** 화면도 root.after 도 건드리지 않는다."""
        if self._stopped or entry_id in self._echoed:
            return
        self._echoed[entry_id] = None
        while len(self._echoed) > 500:
            self._echoed.popitem(last=False)

        delay = random.randint(*dialogue.ECHO_DELAY_SEC)
        timer = threading.Timer(delay, self._echo_in_background, args=(entry_id,))
        timer.daemon = True
        with self._timer_lock:
            if self._stopped:
                return
            self._timers.add(timer)
        timer.start()

    def _echo_in_background(self, entry_id: str) -> None:
        """타이머 스레드. 최근접 탐색과 DB 쓰기까지 여기서 끝내고 큐에만 넣는다."""
        try:
            with self._timer_lock:
                self._timers = {t for t in self._timers if t.is_alive()}
            if self._stopped:
                return
            found = recall.similar_entry(self.journal, source_entry_id=entry_id,
                                         model=self.model)
            if found is None:
                return          # 억지로 이어붙이지 않는다
            with self.db.write() as conn:
                spoken = self.speaker.echo(conn, found)
        except (sqlite3.DatabaseError, ValueError, KeyError):
            return
        self._say_queue.put(spoken.utterance.text)


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
    from . import __version__
    from .pet.window import PetWindow, enable_dpi_awareness

    # 달팽이를 두 마리 띄우지 않는다. 자동 시작과 바로가기가 겹칠 수 있다.
    guard = single_instance.acquire()
    if not guard.acquired:
        print('이미 실행 중입니다.', file=sys.stderr)
        return 0

    enable_dpi_awareness()          # Tk 보다 먼저
    # 동봉 폰트를 이 프로세스에만 등록한다. 사용자 컴퓨터에 설치하지 않는다.
    # Tk 를 만들기 전에 해야 첫 창부터 제대로 된 폰트로 뜬다.
    load_bundled_fonts(resource_root())

    db_path = default_db_path()
    data_dir = default_data_dir()

    # 새 버전이 처음 켜질 때, 스키마를 손대기 **전에** 통째로 복사해 둔다.
    # 마이그레이션이 잘못돼도 어제로 돌아갈 수 있다.
    stored_version = _read_stored_version(db_path)
    try:
        backup.backup_for_version(db_path, data_dir, __version__,
                                  stored_version=stored_version)
    except backup.BackupError as exc:
        print(f'버전 백업을 만들지 못했습니다: {exc}', file=sys.stderr)

    try:
        db = open_database(db_path)
    except StorageError as exc:
        print(f'기록을 열 수 없습니다: {exc}', file=sys.stderr)
        return 1

    journal = Journal(db)
    drafts = Drafts(db)
    settings = Settings(db)
    settings.set(SETTING_VERSION, __version__)
    catalog = build_source(settings)

    def on_write(book_id: str | None = None) -> None:
        from .pet.panels import WritePanel
        # **책마다 창 하나.** 같은 책의 창을 두 번 열면 둘이 같은 draft_key 를
        # 두고 다투지만, 다른 책이면 초안도 다르므로 따로 떠야 한다.
        # 키를 'write' 하나로 두면 책장에서 책을 눌러도 앞서 열린 창이 돌아와
        # 책이 안 잡힌다.
        key = f'write:{book_id or ""}'
        pet.show_once(key, lambda: WritePanel(
            pet.root, journal, drafts, book_id=book_id, owner=pet,
            on_saved=companion.note_saved))

    def on_library() -> None:
        from .pet.panels import LibraryPanel
        pet.show_once('library', lambda: LibraryPanel(
            pet.root, journal, owner=pet, on_write=on_write))

    def on_shelf() -> None:
        from .pet.panels import ShelfPanel
        pet.show_once('shelf', lambda: ShelfPanel(
            pet.root, journal, owner=pet, on_open_book=on_write))

    def on_props() -> None:
        from .pet.panels import PropsPanel
        pet.show_once('props', lambda: PropsPanel(
            pet.root, pet.sprites, settings, owner=pet, setting_key=SETTING_PROPS))

    def on_add_book() -> None:
        from .pet.panels import AddBookPanel
        pet.show_once('add_book', lambda: AddBookPanel(
            pet.root, journal, source=catalog, owner=pet, on_added=fetch_cover))

    def fetch_cover(book_id: str, url: str | None) -> None:
        """표지 내려받기는 네트워크다. UI 스레드를 막지 않는다."""
        if not url:
            return
        threading.Thread(
            target=attach_cover, args=(journal, book_id, url, data_dir),
            name='cover', daemon=True).start()

    def on_weekly() -> None:
        from .pet.panels import WeeklyPanel
        pet.show_once('weekly', lambda: WeeklyPanel(pet.root, journal, owner=pet))

    def on_settings() -> None:
        from .pet.panels import SettingsPanel
        pet.show_once('settings', lambda: SettingsPanel(
            pet.root, journal=journal, settings=settings, db_path=db_path,
            data_dir=data_dir, owner=pet, on_scale=lambda _s: _ask_restart(pet)))

    def on_tray() -> None:
        """집에 보내기. 트레이가 없으면 그냥 숨기지 않는다 — 돌아올 길이 없다."""
        if not tray.show():
            from tkinter import messagebox
            messagebox.showinfo('책 읽는 달팽이',
                                '트레이를 쓸 수 없어 숨기지 않습니다.\n'
                                '(pystray 가 설치되지 않았습니다)', parent=pet.root)
            return
        pet.root.withdraw()

    def poll_tray() -> None:
        for event in tray.drain():
            if event == 'restore':
                tray.hide()
                pet.root.deiconify()
            elif event == 'quit':
                tray.hide()
                pet.close()
                return
        pet.call_later(TRAY_POLL_MS, poll_tray)

    def on_quit() -> None:
        companion.stop()
        tray.hide()
        db.close()
        guard.close()

    from .pet.tray import TrayIcon
    tray = TrayIcon()
    scale = _read_scale(settings)
    pet = PetWindow(scale=scale, on_write=lambda: on_write(),
                    on_library=on_library, on_add_book=on_add_book,
                    on_shelf=on_shelf, on_props=on_props, on_weekly=on_weekly,
                    on_settings=on_settings, on_tray=on_tray, on_quit=on_quit,
                    resource_root=resource_root(), data_dir=data_dir)
    # 소품은 순수 사용자 선택이다 — 해금 개념이 없다(CLAUDE.md).
    if pet.sprites is not None:
        chosen = [p for p in (settings.get(SETTING_PROPS, '') or '').split(',') if p.strip()]
        pet.sprites.set_props(tuple(p.strip() for p in chosen))
    companion = Companion(pet, db, journal, default_encoder(resource_root()))
    _offer_migration(pet.root, db)
    companion.start()
    poll_tray()
    pet.run()
    return 0


def _read_scale(settings) -> float:
    try:
        return max(0.5, min(1.0, float(settings.get(SETTING_SCALE, '1.0') or '1.0')))
    except (TypeError, ValueError):
        return 1.0


def _read_stored_version(db_path) -> str | None:
    """DB 를 열기 **전에** 지난 버전을 본다. 스키마를 손대기 전에 백업해야 하므로
    open_database() 를 거칠 수 없다."""
    from pathlib import Path
    if not Path(db_path).is_file():
        return None
    try:
        con = sqlite3.connect(readonly_uri(db_path), uri=True, timeout=5)
    except sqlite3.DatabaseError:
        return None
    try:
        row = con.execute("SELECT value FROM settings WHERE key=?",
                          (SETTING_VERSION,)).fetchone()
        return str(row[0]) if row else None
    except sqlite3.DatabaseError:
        return None
    finally:
        con.close()


def _ask_restart(pet) -> None:
    from tkinter import messagebox
    messagebox.showinfo('책 읽는 달팽이',
                        '앱을 다시 켜면 새 크기로 뜹니다.', parent=pet.root)


if __name__ == '__main__':
    raise SystemExit(main())
