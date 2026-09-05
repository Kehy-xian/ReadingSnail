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

from ..storage.drafts import Drafts
from ..storage.journal import Journal


class WritePanel:
    """기록 한 건을 남긴다. 닫으면 쓰던 글이 초안으로 남는다."""

    def __init__(self, parent: tk.Misc, journal: Journal, drafts: Drafts,
                 *, book_id: str | None = None, owner: object | None = None):
        self.journal = journal
        self.drafts = drafts
        self.book_id = book_id
        self.draft_key = Drafts.key_for_book(book_id)
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
