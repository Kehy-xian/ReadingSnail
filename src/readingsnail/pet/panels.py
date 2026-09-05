"""기록 창과 서재 창.

**의도적으로 꾸미지 않았다.** 개발 순서가 기능(1~4) → 디자인(5~6)이다.
지금 다듬으면 6단계에서 어차피 갈아엎을 화면을 다듬게 된다. 여기서는
저장소 계층이 UI 에 제대로 붙는지만 확인한다.

PetWindow 를 상속해서 패널을 붙이지 않는다. 전작이 그렇게 하다 11겹이 됐다.
패널은 이렇게 각자 Toplevel 을 들고 산다.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Callable

from ..storage.drafts import Drafts
from ..storage.journal import Journal


class WritePanel:
    """기록 한 건을 남긴다. 닫으면 쓰던 글이 초안으로 남는다."""

    def __init__(self, parent: tk.Misc, journal: Journal, drafts: Drafts,
                 *, book_id: str | None = None, owner: object | None = None,
                 on_saved: Callable[[], None] | None = None):
        self.journal = journal
        self.drafts = drafts
        self.book_id = book_id
        self.draft_key = Drafts.key_for_book(book_id)
        self.on_saved = on_saved
        # 달팽이 창이 닫힐 때 쓰던 글을 초안으로 남기기 위해 등록한다.
        # 등록하지 않으면 root.destroy() 가 이 창을 그냥 없애 글이 사라진다.
        self.owner = owner if hasattr(owner, 'register_closer') else None
        if self.owner is not None:
            self.owner.register_closer(self._save_draft)

        self.top = tk.Toplevel(parent)
        self.top.title('기록 남기기')
        self.top.geometry('460x340')

        self.kind = tk.StringVar(value='note')
        row = tk.Frame(self.top)
        row.pack(fill='x', padx=10, pady=(10, 4))
        tk.Radiobutton(row, text='내 생각', variable=self.kind, value='note').pack(side='left')
        tk.Radiobutton(row, text='필사한 문장', variable=self.kind, value='quote').pack(side='left')
        tk.Label(row, text='쪽').pack(side='left', padx=(12, 4))
        self.page = tk.Entry(row, width=8)
        self.page.pack(side='left')

        self.books = {b.display_name: b.book_id for b in journal.list_books()}
        self.book_choice = tk.StringVar(value='(책 없이)')
        tk.OptionMenu(self.top, self.book_choice,
                      '(책 없이)', *self.books).pack(fill='x', padx=10)

        self.text = tk.Text(self.top, wrap='word', height=10)
        self.text.pack(fill='both', expand=True, padx=10, pady=8)

        saved = drafts.load(self.draft_key)
        if saved:
            self.text.insert('1.0', saved.body)
            self.kind.set(saved.kind)

        buttons = tk.Frame(self.top)
        buttons.pack(fill='x', padx=10, pady=(0, 10))
        tk.Button(buttons, text='저장', command=self.save).pack(side='right')
        tk.Button(buttons, text='닫기', command=self.close).pack(side='right', padx=6)
        self.top.protocol('WM_DELETE_WINDOW', self.close)
        self.text.focus_set()

    def _body(self) -> str:
        return self.text.get('1.0', 'end').strip()

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
            messagebox.showerror('책 읽는 달팽이', f'저장하지 못했습니다.\n{exc}', parent=self.top)
            return
        # 저장이 끝났으니 초안은 지운다. 저장 실패 시에는 남겨둬야 글을 잃지 않는다.
        self.drafts.clear(self.draft_key)
        self._detach()
        self.top.destroy()
        # 저장이 끝난 뒤에 알린다. 임베딩 작업자를 깨워 되살리기가 이어진다.
        if self.on_saved is not None:
            self.on_saved()

    def _save_draft(self) -> None:
        """쓰던 글을 초안으로. 창이 이미 사라졌으면 조용히 넘어간다."""
        try:
            body = self._body()
        except tk.TclError:
            return
        self.drafts.save(self.draft_key, body=body,
                         book_id=self.book_id, kind=self.kind.get())

    def close(self) -> None:
        """닫아도 글을 잃지 않는다. 쓰던 그대로 초안에 남긴다."""
        self._save_draft()
        self._detach()
        self.top.destroy()

    def _detach(self) -> None:
        if self.owner is not None:
            self.owner.unregister_closer(self._save_draft)
            self.owner = None


class LibraryPanel:
    """책과 기록 수를 훑어본다."""

    def __init__(self, parent: tk.Misc, journal: Journal):
        self.journal = journal
        self.top = tk.Toplevel(parent)
        self.top.title('내 서재')
        self.top.geometry('460x360')

        self.listbox = tk.Listbox(self.top)
        self.listbox.pack(fill='both', expand=True, padx=10, pady=10)

        books = journal.list_books()
        if not books:
            self.listbox.insert('end', '아직 등록한 책이 없습니다.')
        for book in books:
            n = len(journal.entries_for_book(book.book_id))
            self.listbox.insert('end', f'[{book.status}] {book.display_name} — 기록 {n}건')

        loose = [e for e in journal.recent_entries(limit=200) if e.book_id is None]
        if loose:
            self.listbox.insert('end', f'(책 없는 기록 {len(loose)}건)')

        tk.Label(self.top, text=f'전체 기록 {journal.count_entries()}건').pack(pady=(0, 8))


class AddBookPanel:
    """책을 등록한다. 검색이 안 되면 수동 입력으로 넘어간다.

    서지 서비스는 또 문을 닫는다(올해만 두 곳). 검색 실패가 등록 실패가 되면
    안 되므로, 수동 입력 칸은 **처음부터 늘 열려 있다.** 검색은 그 칸을
    채워주는 보조일 뿐이다.
    """

    def __init__(self, parent: tk.Misc, journal: Journal, *,
                 source=None, on_added: Callable[[str, str | None], None] | None = None):
        self.journal = journal
        self.source = source
        self.on_added = on_added
        self.results: list = []

        self.top = tk.Toplevel(parent)
        self.top.title('책 등록')
        self.top.geometry('520x420')

        bar = tk.Frame(self.top)
        bar.pack(fill='x', padx=10, pady=(10, 4))
        self.query = tk.Entry(bar)
        self.query.pack(side='left', fill='x', expand=True)
        self.query.bind('<Return>', lambda _e: self.search())
        tk.Button(bar, text='검색', command=self.search).pack(side='left', padx=(6, 0))

        self.status = tk.Label(self.top, anchor='w', text=self._idle_status())
        self.status.pack(fill='x', padx=10)

        self.listbox = tk.Listbox(self.top, height=8)
        self.listbox.pack(fill='both', expand=True, padx=10, pady=6)
        self.listbox.bind('<<ListboxSelect>>', lambda _e: self._fill_from_result())

        form = tk.Frame(self.top)
        form.pack(fill='x', padx=10)
        self.title_entry = self._row(form, '제목', 0)
        self.author_entry = self._row(form, '저자', 1)
        self.publisher_entry = self._row(form, '출판사', 2)
        self.isbn_entry = self._row(form, 'ISBN', 3)

        self.status_var = tk.StringVar(value='reading')
        row = tk.Frame(self.top)
        row.pack(fill='x', padx=10, pady=6)
        for label, value in (('읽는 중', 'reading'), ('읽고 싶은', 'wishlist'),
                             ('다 읽음', 'completed')):
            tk.Radiobutton(row, text=label, variable=self.status_var,
                           value=value).pack(side='left')
        tk.Button(row, text='등록', command=self.add).pack(side='right')
        self.query.focus_set()

    def _idle_status(self) -> str:
        if self.source is None:
            return '검색이 꺼져 있습니다. 아래에 직접 입력해 등록하세요.'
        return 'ISBN 또는 제목으로 검색하세요.'

    @staticmethod
    def _row(parent: tk.Frame, label: str, row: int) -> tk.Entry:
        tk.Label(parent, text=label, width=6, anchor='w').grid(row=row, column=0, sticky='w')
        entry = tk.Entry(parent)
        entry.grid(row=row, column=1, sticky='ew', pady=1)
        parent.columnconfigure(1, weight=1)
        return entry

    def search(self) -> None:
        """검색은 네트워크다. 결과가 없어도 수동 입력은 그대로 열려 있다."""
        from ..services.catalog import search_books

        text = self.query.get().strip()
        if not text:
            return
        self.listbox.delete(0, 'end')
        self.results = search_books(self.source, text, limit=20)
        if not self.results:
            self.status.config(
                text='찾지 못했습니다. 아래에 직접 입력해 등록하세요.'
                if self.source else self._idle_status())
            self.title_entry.delete(0, 'end')
            self.title_entry.insert(0, text)
            return
        self.status.config(text=f'{len(self.results)}건. 고르면 아래가 채워집니다.')
        for record in self.results:
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
        # destroy() 뒤에 읽으면 'invalid command name ...' TclError 가 난다.
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
        self.top.destroy()
        # 표지 내려받기는 네트워크다. 호출부가 배경으로 넘긴다.
        if self.on_added is not None:
            self.on_added(book.book_id, cover_url)
