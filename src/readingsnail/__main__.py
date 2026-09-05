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
from .paths import default_data_dir, default_db_path, legacy_db_path, resource_root
from .services import dialogue, recall
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
    from .pet.window import PetWindow, enable_dpi_awareness

    enable_dpi_awareness()          # Tk 보다 먼저
    # 동봉 폰트를 이 프로세스에만 등록한다. 사용자 컴퓨터에 설치하지 않는다.
    # Tk 를 만들기 전에 해야 첫 창부터 제대로 된 폰트로 뜬다.
    load_bundled_fonts(resource_root())

    try:
        db = open_database(default_db_path())
    except StorageError as exc:
        print(f'기록을 열 수 없습니다: {exc}', file=sys.stderr)
        return 1

    journal = Journal(db)
    drafts = Drafts(db)
    settings = Settings(db)
    catalog = build_source(settings)
    data_dir = default_data_dir()

    def on_write() -> None:
        from .pet.panels import WritePanel
        # 같은 창을 두 번 열면 두 창이 같은 초안을 두고 다툰다. 하나만 띄운다.
        pet.show_once('write', lambda: WritePanel(
            pet.root, journal, drafts, owner=pet, on_saved=companion.note_saved))

    def on_library() -> None:
        from .pet.panels import LibraryPanel
        pet.show_once('library', lambda: LibraryPanel(pet.root, journal))

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

    def on_quit() -> None:
        companion.stop()
        db.close()

    pet = PetWindow(on_write=on_write, on_library=on_library,
                    on_add_book=on_add_book, on_quit=on_quit,
                    resource_root=resource_root(), data_dir=data_dir)
    # 소품은 순수 사용자 선택이다 — 해금 개념이 없다(CLAUDE.md).
    if pet.sprites is not None:
        chosen = [p for p in (settings.get(SETTING_PROPS, '') or '').split(',') if p.strip()]
        pet.sprites.set_props(tuple(p.strip() for p in chosen))
    companion = Companion(pet, db, journal, default_encoder(resource_root()))
    _offer_migration(pet.root, db)
    companion.start()
    pet.run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
