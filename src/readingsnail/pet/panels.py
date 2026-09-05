"""기록·서재·책 등록 창. (6-b 재배치판)

PetWindow 를 상속해서 패널을 붙이지 않는다. 전작이 그렇게 하다 11겹이 됐다.
패널은 이렇게 각자 Toplevel 을 들고 산다.

지키는 것
    · 색과 폰트는 `styling.apply()` 를 거친다. 값을 여기 박아넣지 않는다.
    · Tk 변수와 예약한 after 는 `<Destroy>` 에서 거둔다. owner 등록만 믿으면
      owner 없이 만든 패널이 자원을 남긴다.
    · 네트워크는 배경 스레드로. UI 를 최대 8초 얼리지 않는다.
    · **글을 잃지 않는다.** 저장에 실패하면 초안을 지우지 않고, 창이 어떤 경로로
      사라지든 쓰던 글은 초안으로 남는다.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from ..theme import PAD_L, PAD_M, PAD_S, PALETTE, font
from .styling import apply as apply_style
from .styling import text_defaults

BOOK_NONE = '(책 없이)'
# 책장에 한 번에 그릴 최대 권수. 넘으면 요약에 사실대로 적는다.
MAX_SHELF_BOOKS = 2000
STATUS_LABELS = (('읽는 중', 'reading'), ('읽고 싶은', 'wishlist'),
                 ('다 읽음', 'completed'), ('잠시 멈춤', 'paused'))
STATUS_KO = {value: label for label, value in STATUS_LABELS}


class _Panel:
    """모든 패널이 공유하는 뼈대. 상속은 여기까지만 — 한 겹이다."""

    title = '책 읽는 달팽이'
    size = '520x420'

    def __init__(self, parent: tk.Misc, *, owner: object | None = None):
        self.top = tk.Toplevel(parent)
        self.top.title(self.title)
        self.top.geometry(self.size)
        self.top.configure(bg=PALETTE['paper'])
        self.style = apply_style(self.top)
        self._disposed = False
        self.owner = owner if hasattr(owner, 'register_closer') else None
        self.top.bind('<Destroy>', self._on_destroy)
        self.top.bind('<Escape>', lambda _e: self.close())

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self.top:
            self.dispose()

    def dispose(self) -> None:
        """Tk 자원을 놓아준다. 여러 번 불러도 안전하다."""
        if self._disposed:
            return
        self._disposed = True
        self._cleanup()
        if self.owner is not None:
            self.owner.unregister_closer(self.dispose)
            self.owner = None

    def _cleanup(self) -> None:
        """하위 클래스가 자기 자원을 거둔다."""

    def close(self) -> None:
        self.dispose()
        try:
            self.top.destroy()
        except tk.TclError:
            pass


class WritePanel(_Panel):
    """기록 한 건을 남긴다. 닫으면 쓰던 글이 초안으로 남는다."""

    title = '기록 남기기'
    size = '560x460'

    def __init__(self, parent: tk.Misc, journal, drafts, *,
                 book_id: str | None = None, owner: object | None = None,
                 on_saved: Callable[[], None] | None = None):
        super().__init__(parent, owner=owner)
        self.journal = journal
        self.drafts = drafts
        self.book_id = book_id
        self.on_saved = on_saved
        self.draft_key = drafts.key_for_book(book_id)
        # 저장을 끝내고 닫는 경우에는 초안을 다시 쓰지 않는다.
        # 안 그러면 방금 지운 초안이 되살아난다.
        self._submitted = False
        if self.owner is not None:
            self.owner.register_closer(self._save_draft)

        self.kind = tk.StringVar(value='note')
        self.book_choice = tk.StringVar(value=BOOK_NONE)

        outer = ttk.Frame(self.top, padding=PAD_M)
        outer.pack(fill='both', expand=True)

        # 어느 책의, 어떤 종류의 기록인가
        head = ttk.Frame(outer)
        head.pack(fill='x', pady=(0, PAD_S))
        ttk.Label(head, text='책').pack(side='left')
        self.books = {b.display_name: b.book_id for b in journal.list_books(limit=200)}
        self.book_box = ttk.Combobox(head, textvariable=self.book_choice, state='readonly',
                                     values=[BOOK_NONE, *self.books])
        self.book_box.pack(side='left', fill='x', expand=True, padx=(PAD_S, PAD_M))
        if book_id:
            for name, ident in self.books.items():
                if ident == book_id:
                    self.book_choice.set(name)
                    break

        ttk.Label(head, text='쪽').pack(side='left')
        self.page = ttk.Entry(head, width=8)
        self.page.pack(side='left', padx=(PAD_S, 0))

        kinds = ttk.Frame(outer)
        kinds.pack(fill='x', pady=(0, PAD_S))
        ttk.Radiobutton(kinds, text='내 생각', variable=self.kind,
                        value='note').pack(side='left')
        ttk.Radiobutton(kinds, text='필사한 문장', variable=self.kind,
                        value='quote').pack(side='left', padx=(PAD_M, 0))
        self.counter = ttk.Label(kinds, text='0자', style='Muted.TLabel')
        self.counter.pack(side='right')

        self.text = tk.Text(self.top, wrap='word', height=12, undo=True,
                            **text_defaults(self.top))
        self.text.pack(in_=outer, fill='both', expand=True)
        self.text.bind('<KeyRelease>', lambda _e: self._count())
        self.text.bind('<Control-Return>', lambda _e: (self.save(), 'break')[1])

        buttons = ttk.Frame(outer)
        buttons.pack(fill='x', pady=(PAD_M, 0))
        ttk.Label(buttons, text='Ctrl+Enter 로 저장 · Esc 로 닫기',
                  style='Muted.TLabel').pack(side='left')
        ttk.Button(buttons, text='저장', style='Accent.TButton',
                   command=self.save).pack(side='right')
        ttk.Button(buttons, text='닫기', command=self.close).pack(side='right',
                                                                 padx=(0, PAD_S))
        self.top.protocol('WM_DELETE_WINDOW', self.close)

        saved = drafts.load(self.draft_key)
        if saved:
            self.text.insert('1.0', saved.body)
            self.kind.set(saved.kind)
        self._count()
        self.text.focus_set()

    def _count(self) -> None:
        try:
            self.counter.config(text=f'{len(self._body())}자')
        except tk.TclError:
            pass

    def _body(self) -> str:
        return self.text.get('1.0', 'end').strip()

    def _save_draft(self) -> None:
        """쓰던 글을 초안으로. 창이 이미 사라졌으면 조용히 넘어간다."""
        if self._submitted:
            return
        try:
            body = self._body()
            kind = self.kind.get()
        except (tk.TclError, AttributeError):
            return
        self.drafts.save(self.draft_key, body=body, book_id=self.book_id, kind=kind)

    def save(self) -> None:
        body = self._body()
        if not body:
            messagebox.showinfo('책 읽는 달팽이', '남길 글이 없습니다.', parent=self.top)
            return
        chosen = self.books.get(self.book_choice.get())
        try:
            self.journal.add_entry(body, book_id=chosen, kind=self.kind.get(),
                                   page=self.page.get().strip() or None)
        except (ValueError, KeyError) as exc:
            # 저장에 실패하면 초안을 지우지 않는다. 글을 잃지 않는 쪽이 먼저다.
            messagebox.showerror('책 읽는 달팽이', f'저장하지 못했습니다.\n{exc}',
                                 parent=self.top)
            return
        self.drafts.clear(self.draft_key)
        self._submitted = True
        on_saved = self.on_saved
        self.close()
        if on_saved is not None:
            on_saved()

    def _cleanup(self) -> None:
        # **owner 가 있든 없든 초안은 남긴다.** owner 등록에만 기대면 owner 없이
        # 만든 패널에서 쓰던 글이 사라진다.
        if not self._submitted:
            self._save_draft()
        if self.owner is not None:
            self.owner.unregister_closer(self._save_draft)
        self.kind = None
        self.book_choice = None


class LibraryPanel(_Panel):
    """책과 기록을 훑어본다. 책을 고르면 그 책의 기록이 시간순으로 보인다."""

    title = '내 서재'
    size = '760x520'

    def __init__(self, parent: tk.Misc, journal, *, owner: object | None = None,
                 on_write: Callable[[str], None] | None = None):
        super().__init__(parent, owner=owner)
        self.journal = journal
        self.on_write = on_write
        self.books: dict[str, str] = {}

        outer = ttk.Frame(self.top, padding=PAD_M)
        outer.pack(fill='both', expand=True)

        bar = ttk.Frame(outer)
        bar.pack(fill='x', pady=(0, PAD_S))
        ttk.Label(bar, text='내 서재', style='Heading.TLabel').pack(side='left')
        self.summary = ttk.Label(bar, style='Muted.TLabel')
        self.summary.pack(side='right')

        panes = ttk.PanedWindow(outer, orient='horizontal')
        panes.pack(fill='both', expand=True)

        left = ttk.Frame(panes)
        self.tree = ttk.Treeview(left, columns=('status', 'entries'), height=14)
        self.tree.heading('#0', text='책')
        self.tree.heading('status', text='상태')
        self.tree.heading('entries', text='기록')
        self.tree.column('#0', width=280)
        self.tree.column('status', width=70, anchor='center')
        self.tree.column('entries', width=56, anchor='e')
        self.tree.pack(side='left', fill='both', expand=True)
        bar_y = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        bar_y.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=bar_y.set)
        self.tree.bind('<<TreeviewSelect>>', lambda _e: self._show_entries())
        panes.add(left, weight=3)

        right = ttk.Frame(panes)
        ttk.Label(right, text='기록', style='Caption.TLabel').pack(anchor='w')
        self.detail = tk.Text(right, wrap='word', state='disabled', width=34,
                              **text_defaults(self.top))
        self.detail.pack(fill='both', expand=True, pady=(PAD_S // 2, 0))
        actions = ttk.Frame(right)
        actions.pack(fill='x', pady=(PAD_S, 0))
        self.write_button = ttk.Button(actions, text='이 책에 기록 남기기',
                                       style='Accent.TButton', state='disabled',
                                       command=self._write_here)
        self.write_button.pack(fill='x')
        panes.add(right, weight=2)

        self.refresh()

    def refresh(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.books.clear()
        counts = self.journal.entry_counts_by_book()
        for book in self.journal.list_books(limit=500):
            item = self.tree.insert('', 'end', text=book.display_name,
                                    values=(STATUS_KO.get(book.status, book.status),
                                            counts.get(book.book_id, 0)))
            self.books[item] = book.book_id
        loose = counts.get(None, 0)
        if loose:
            item = self.tree.insert('', 'end', text='(책 없는 기록)',
                                    values=('—', loose))
            self.books[item] = ''
        total = self.journal.count_entries()
        self.summary.config(text=f'책 {self.journal.count_books()}권 · 기록 {total}건')

    def _selected_book(self) -> str | None:
        picked = self.tree.selection()
        if not picked:
            return None
        return self.books.get(picked[0])

    def _show_entries(self) -> None:
        book_id = self._selected_book()
        if book_id is None:
            return
        if book_id:
            entries = self.journal.entries_for_book(book_id)
            self.write_button.config(state='normal')
        else:
            entries = [e for e in self.journal.recent_entries(limit=300)
                       if e.book_id is None]
            self.write_button.config(state='disabled')

        self.detail.config(state='normal')
        self.detail.delete('1.0', 'end')
        if not entries:
            self.detail.insert('end', '아직 기록이 없습니다.')
        for entry in entries:
            mark = '“' if entry.kind == 'quote' else '·'
            page = f'  {entry.page}' if entry.page else ''
            self.detail.insert('end', f'{entry.created_at[:10]}{page}\n')
            self.detail.insert('end', f'{mark} {entry.body}\n\n')
        self.detail.config(state='disabled')

    def _write_here(self) -> None:
        book_id = self._selected_book()
        if book_id and self.on_write is not None:
            self.on_write(book_id)

    def _cleanup(self) -> None:
        self.books.clear()


class AddBookPanel(_Panel):
    """책을 등록한다. 검색이 안 되면 수동 입력으로 넘어간다.

    서지 서비스는 또 문을 닫는다(올해만 두 곳). 검색 실패가 등록 실패가 되면
    안 되므로, 수동 입력 칸은 **처음부터 늘 열려 있다.**
    """

    title = '책 등록'
    size = '560x520'

    def __init__(self, parent: tk.Misc, journal, *, source=None,
                 owner: object | None = None,
                 on_added: Callable[[str, str | None], None] | None = None):
        super().__init__(parent, owner=owner)
        self.journal = journal
        self.source = source
        self.on_added = on_added
        self.results: list = []
        self._found: queue.Queue = queue.Queue()
        self._searching = False
        self._poll_after: str | None = None
        if self.owner is not None:
            self.owner.register_closer(self.dispose)

        self.status_var = tk.StringVar(value='reading')

        outer = ttk.Frame(self.top, padding=PAD_M)
        outer.pack(fill='both', expand=True)

        bar = ttk.Frame(outer)
        bar.pack(fill='x')
        self.query = ttk.Entry(bar)
        self.query.pack(side='left', fill='x', expand=True)
        self.query.bind('<Return>', lambda _e: self.search())
        self.search_button = ttk.Button(bar, text='검색', command=self.search)
        self.search_button.pack(side='left', padx=(PAD_S, 0))

        self.status = ttk.Label(outer, style='Muted.TLabel', text=self._idle_status())
        self.status.pack(fill='x', pady=(PAD_S // 2, PAD_S))

        self.listbox = tk.Listbox(outer, height=7, activestyle='none',
                                  bg=PALETTE['paper'], fg=PALETTE['ink'],
                                  selectbackground=PALETTE['moss_deep'],
                                  selectforeground=PALETTE['on_accent'],
                                  highlightthickness=1, relief='flat',
                                  highlightbackground=PALETTE['border'])
        self.listbox.pack(fill='both', expand=True)
        self.listbox.bind('<<ListboxSelect>>', lambda _e: self._fill_from_result())

        ttk.Separator(outer).pack(fill='x', pady=PAD_M)

        form = ttk.Frame(outer)
        form.pack(fill='x')
        form.columnconfigure(1, weight=1)
        self.title_entry = self._row(form, '제목', 0)
        self.author_entry = self._row(form, '저자', 1)
        self.publisher_entry = self._row(form, '출판사', 2)
        self.isbn_entry = self._row(form, 'ISBN', 3)

        statuses = ttk.Frame(outer)
        statuses.pack(fill='x', pady=(PAD_M, 0))
        for label, value in STATUS_LABELS:
            ttk.Radiobutton(statuses, text=label, variable=self.status_var,
                            value=value).pack(side='left', padx=(0, PAD_S))
        ttk.Button(statuses, text='등록', style='Accent.TButton',
                   command=self.add).pack(side='right')
        self.top.protocol('WM_DELETE_WINDOW', self.close)
        self.query.focus_set()

    @staticmethod
    def _row(parent: ttk.Frame, label: str, row: int) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w',
                                           pady=2, padx=(0, PAD_S))
        entry = ttk.Entry(parent)
        entry.grid(row=row, column=1, sticky='ew', pady=2)
        return entry

    def _idle_status(self) -> str:
        if self.source is None:
            return '검색이 꺼져 있습니다. 아래에 직접 입력해 등록하세요.'
        return 'ISBN 또는 제목으로 검색하세요. 못 찾아도 아래에 직접 넣을 수 있습니다.'

    # ── 검색 ──────────────────────────────────────────
    def search(self) -> None:
        """검색은 네트워크다. **배경 스레드로 넘긴다.**

        UI 스레드에서 부르면 응답이 늦는 만큼(최대 8초) 창이 통째로 얼어붙는다.
        """
        text = self.query.get().strip()
        if not text or self._searching:
            return
        self.listbox.delete(0, 'end')
        self.results = []
        if self.source is None:
            self._show_results(text, [])
            return

        self._searching = True
        self.search_button.config(state='disabled')
        self.status.config(text='찾는 중…')
        threading.Thread(target=_search_worker, args=(self.source, text, self._found),
                         name='catalog-search', daemon=True).start()
        self._poll_search()

    def _poll_search(self) -> None:
        """UI 스레드. 큐를 확인하고 결과가 오면 그린다."""
        self._poll_after = None
        if self._disposed:
            return
        try:
            text, records = self._found.get_nowait()
        except queue.Empty:
            if self._searching:
                try:
                    if self.top.winfo_exists():
                        self._poll_after = self.top.after(120, self._poll_search)
                except tk.TclError:
                    self._searching = False
            return
        self._searching = False
        try:
            if self.top.winfo_exists():
                self.search_button.config(state='normal')
                self._show_results(text, records)
        except tk.TclError:
            pass

    def _show_results(self, text: str, records: list) -> None:
        self.results = records
        if not records:
            self.status.config(
                text='찾지 못했습니다. 아래에 직접 입력해 등록하세요.'
                if self.source else self._idle_status())
            self.title_entry.delete(0, 'end')
            self.title_entry.insert(0, text)
            return
        self.status.config(text=f'{len(records)}건. 고르면 아래가 채워집니다.')
        for record in records:
            self.listbox.insert('end', record.display_name)

    def _fill_from_result(self) -> None:
        picked = self.listbox.curselection()
        if not picked:
            return
        record = self.results[picked[0]]
        for entry, value in ((self.title_entry, record.title),
                             (self.author_entry, record.author),
                             (self.publisher_entry, record.publisher or ''),
                             (self.isbn_entry, record.isbn13 or '')):
            entry.delete(0, 'end')
            entry.insert(0, value)

    def add(self) -> None:
        title = self.title_entry.get().strip()
        if not title:
            messagebox.showinfo('책 읽는 달팽이', '제목을 입력하세요.', parent=self.top)
            return
        # 창을 부수기 **전에** 위젯에서 필요한 것을 모두 꺼낸다.
        picked = self.listbox.curselection()
        source = self.results[picked[0]].source if picked else 'manual'
        cover_url = self.results[picked[0]].cover_url if picked else None
        try:
            book = self.journal.add_book(
                title, author=self.author_entry.get().strip(),
                publisher=self.publisher_entry.get().strip() or None,
                isbn13=self.isbn_entry.get().strip() or None,
                status=self.status_var.get(), source=source)
        except ValueError as exc:
            messagebox.showerror('책 읽는 달팽이', f'등록하지 못했습니다.\n{exc}',
                                 parent=self.top)
            return
        on_added = self.on_added
        self.close()
        if on_added is not None:
            on_added(book.book_id, cover_url)

    def _cleanup(self) -> None:
        self._searching = False
        if self._poll_after is not None:
            try:
                self.top.after_cancel(self._poll_after)
            except tk.TclError:
                pass
            self._poll_after = None
        self.status_var = None
        self.results = []


def _search_worker(source, text: str, found: queue.Queue) -> None:
    """배경 스레드에서 도는 검색. **Tk 객체를 하나도 붙들지 않는다.**

    모듈 수준 함수라 패널(그리고 그 너머의 Tk root)을 참조하지 않는다.
    받는 것은 출처·검색어·큐뿐이다.
    """
    from ..services.catalog import search_books
    try:
        found.put((text, search_books(source, text, limit=20)))
    except Exception:
        found.put((text, []))


class ShelfPanel(_Panel):
    """다 읽은 책이 꽂히는 책장. 이 앱의 유일한 보상 화면이다.

    책등은 표지에서 뽑은 색으로 물들이고(`spine_tint`), 기울인 책과 눕힌 책을
    섞어 정돈감을 깬다. 자세는 book_id 로 정해져 있어 열 때마다 춤추지 않는다.
    """

    title = '책장'
    size = '620x560'

    def __init__(self, parent: tk.Misc, journal, *, owner: object | None = None,
                 on_open_book: Callable[[str], None] | None = None,
                 status: str = 'completed'):
        super().__init__(parent, owner=owner)
        self.journal = journal
        self.on_open_book = on_open_book
        self.status = status
        self.slots: list = []
        self._refresh_after: str | None = None

        outer = ttk.Frame(self.top, padding=PAD_M)
        outer.pack(fill='both', expand=True)

        bar = ttk.Frame(outer)
        bar.pack(fill='x', pady=(0, PAD_S))
        ttk.Label(bar, text='책장', style='Heading.TLabel').pack(side='left')
        self.summary = ttk.Label(bar, style='Muted.TLabel')
        self.summary.pack(side='right')

        holder = ttk.Frame(outer)
        holder.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(holder, bg=PALETTE['paper'], highlightthickness=1,
                                highlightbackground=PALETTE['border'], bd=0)
        self.canvas.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(holder, orient='vertical', command=self.canvas.yview)
        scroll.pack(side='right', fill='y')
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.bind('<Button-1>', self._click)
        # 창 크기를 끌면 <Configure> 가 초당 수십 번 온다. 그때마다 500권을
        # 다시 배치하면(79ms) 창이 끈적해진다. 잠깐 모았다 한 번만 그린다.
        self.canvas.bind('<Configure>', self._schedule_refresh)

        self.hint = ttk.Label(outer, style='Muted.TLabel',
                              text='책을 누르면 그 책의 기록이 열립니다.')
        self.hint.pack(fill='x', pady=(PAD_S, 0))
        self.refresh()

    def _schedule_refresh(self, _event: tk.Event | None = None) -> None:
        if self._refresh_after is not None:
            try:
                self.top.after_cancel(self._refresh_after)
            except tk.TclError:
                pass
        try:
            self._refresh_after = self.top.after(80, self._do_refresh)
        except tk.TclError:
            self._refresh_after = None

    def _do_refresh(self) -> None:
        self._refresh_after = None
        if not self._disposed:
            self.refresh()

    def refresh(self) -> None:
        from . import shelf as layout_mod

        books = self.journal.list_books(status=self.status, limit=MAX_SHELF_BOOKS)
        total = self.journal.count_books(status=self.status)
        width = max(240, self.canvas.winfo_width() or 560)
        shelves, self.slots = layout_mod.layout(books, width=width)
        height = layout_mod.canvas_height(shelves)
        self.canvas.delete('all')
        self.canvas.configure(scrollregion=(0, 0, width, height))

        for board in shelves:
            self.canvas.create_rectangle(
                board.left - 6, board.top, board.right + 6,
                board.top + layout_mod.SHELF_THICKNESS,
                fill=PALETTE['shelf_wood'], outline=PALETTE['ink'], width=1)

        for slot in self.slots:
            self._draw_spine(slot)

        if not self.slots:
            self.canvas.create_text(
                width // 2, 90, text='아직 다 읽은 책이 없습니다.',
                fill=PALETTE['ink_soft'], font=font('body', master=self.top))
        # **몇 권인지는 사실대로 말한다.** 잘렸으면 잘렸다고 알린다 —
        # 조용히 절반만 보여주면 사용자는 책이 사라진 줄 안다.
        if total > len(self.slots):
            self.summary.config(text=f'{total}권 중 {len(self.slots)}권 표시')
        else:
            self.summary.config(text=f'{total}권')

    def _draw_spine(self, slot) -> None:
        fill = slot.tint or PALETTE['paper_deep']
        # 기울임은 사각형 대신 다각형으로 낸다. Canvas 사각형은 회전하지 않는다.
        offset = 0 if slot.lying else int(slot.height * slot.tilt / 90)
        points = [
            slot.x + offset, slot.y,
            slot.x + slot.width + offset, slot.y,
            slot.x + slot.width, slot.bottom,
            slot.x, slot.bottom,
        ]
        self.canvas.create_polygon(points, fill=fill, outline=PALETTE['ink'],
                                   width=1, tags=('spine', slot.book_id))
        label = slot.title if len(slot.title) <= 12 else slot.title[:11] + '…'
        self.canvas.create_text(
            slot.x + slot.width // 2 + offset // 2, slot.y + slot.height // 2,
            text=label, angle=0 if slot.lying else 90,
            fill=_readable_on(fill), font=font('caption', master=self.top),
            width=slot.height - 12 if not slot.lying else slot.width - 12,
            tags=('spine', slot.book_id))

    def _click(self, event: tk.Event) -> None:
        from . import shelf as layout_mod

        x = int(self.canvas.canvasx(event.x))
        y = int(self.canvas.canvasy(event.y))
        slot = layout_mod.slot_at(self.slots, x, y)
        if slot is not None and self.on_open_book is not None:
            self.on_open_book(slot.book_id)

    def _cleanup(self) -> None:
        if self._refresh_after is not None:
            try:
                self.top.after_cancel(self._refresh_after)
            except tk.TclError:
                pass
            self._refresh_after = None
        self.slots = []


class PropsPanel(_Panel):
    """달팽이에게 얹을 소품을 고른다.

    **해금 개념이 없다**(CLAUDE.md). 폴더에 있으면 고를 수 있다.
    무엇을 읽었는지와 무관하다 — 순수한 취향이다.
    """

    title = '소품'
    size = '360x420'

    def __init__(self, parent: tk.Misc, sprites, settings, *,
                 owner: object | None = None, setting_key: str = 'pet.props',
                 on_change: Callable[[tuple[str, ...]], None] | None = None):
        super().__init__(parent, owner=owner)
        self.sprites = sprites
        self.settings = settings
        self.setting_key = setting_key
        self.on_change = on_change
        self.vars: dict[str, tk.BooleanVar] = {}

        outer = ttk.Frame(self.top, padding=PAD_M)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='소품', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(outer, style='Muted.TLabel', wraplength=300, justify='left',
                  text='해금은 없습니다. 폴더에 있으면 고를 수 있습니다.').pack(
                      anchor='w', pady=(0, PAD_M))

        available = sprites.available_props() if sprites is not None else ()
        chosen = {p for p in (settings.get(setting_key, '') or '').split(',') if p}
        if not available:
            ttk.Label(outer, style='Muted.TLabel', wraplength=300, justify='left',
                      text='resources/props/ 에 prop_<이름>.png 를 넣으면 '
                           '여기에 나타납니다.').pack(anchor='w')
        for name in available:
            var = tk.BooleanVar(value=name in chosen)
            self.vars[name] = var
            ttk.Checkbutton(outer, text=name, variable=var,
                            command=self._apply).pack(anchor='w', pady=1)

        ttk.Button(outer, text='닫기', command=self.close).pack(side='bottom',
                                                              anchor='e')

    def selected(self) -> tuple[str, ...]:
        return tuple(name for name, var in self.vars.items() if var.get())

    def _apply(self) -> None:
        picked = self.selected()
        self.settings.set(self.setting_key, ','.join(picked))
        if self.sprites is not None:
            self.sprites.set_props(picked)
        if self.on_change is not None:
            self.on_change(picked)

    def _cleanup(self) -> None:
        self.vars = {}


def _readable_on(background: str) -> str:
    """그 바탕 위에서 읽히는 글자색을 고른다. 책등 색은 표지마다 다르다."""
    from ..theme import contrast
    if contrast(PALETTE['ink'], background) >= contrast(PALETTE['on_accent'],
                                                        background):
        return PALETTE['ink']
    return PALETTE['on_accent']
