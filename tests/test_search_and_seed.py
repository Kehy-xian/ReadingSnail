"""한글 검색과 명언 시드가 실제로 동작하는지 확인한다.

여기 있는 것은 전부 회귀 방지용이다. 특히 2자 검색 테스트는
누군가 search.py 를 우회해 MATCH 를 직접 쓰면 바로 깨진다.
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from readingsnail.services import dialogue                     # noqa: E402
from readingsnail.storage import search, seed                  # noqa: E402

SCHEMA = ROOT / 'src' / 'readingsnail' / 'storage' / 'schema.sql'


def fresh_db() -> sqlite3.Connection:
    conn = sqlite3.connect(':memory:')
    conn.executescript(SCHEMA.read_text(encoding='utf-8'))
    return conn


def add_entry(conn: sqlite3.Connection, body: str, kind: str = 'note') -> str:
    entry_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with conn:
        conn.execute(
            'INSERT INTO entries(entry_id, kind, body, created_at) VALUES (?,?,?,?)',
            (entry_id, kind, body, now),
        )
    return entry_id


class KoreanSearch(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = fresh_db()
        for body in (
            '책 읽는 달팽이는 느리게 간다',
            '나는 달팽이를 좋아한다',
            '독서는 앉아서 하는 여행이다',
            '기록을 남기는 일에 대하여',
        ):
            add_entry(self.conn, body)

    def bodies(self, q: str, **kw) -> list[str]:
        return [h.body for h in search.search_entries(self.conn, q, **kw)]

    def test_어절_중간_단어가_잡힌다(self):
        # unicode61 토크나이저에서는 0건이던 검색이다.
        self.assertEqual(len(self.bodies('달팽이')), 2)

    def test_조사가_붙어도_잡힌다(self):
        # '독서는'으로 저장돼 있어도 '독서'로 찾아야 한다.
        self.assertEqual(len(self.bodies('독서')), 1)

    def test_두_글자_검색이_죽지_않는다(self):
        # trigram MATCH 로는 원리상 0건. 라우터가 LIKE 로 보내야 통과한다.
        self.assertEqual(len(self.bodies('기록')), 1)
        raw = self.conn.execute(
            'SELECT count(*) FROM entries_fts WHERE entries_fts MATCH ?', ('기록',)
        ).fetchone()[0]
        self.assertEqual(raw, 0, 'MATCH 직접 호출은 여전히 0건이어야 한다')

    def test_한_글자_검색(self):
        self.assertEqual(len(self.bodies('책')), 1)

    def test_빈_질의는_빈_결과(self):
        self.assertEqual(self.bodies(''), [])
        self.assertEqual(self.bodies('   '), [])

    def test_kind_필터(self):
        add_entry(self.conn, '달팽이 껍데기에 관한 문장', kind='quote')
        self.assertEqual(len(self.bodies('달팽이', kind='quote')), 1)
        self.assertEqual(len(self.bodies('달팽이', kind='note')), 2)

    def test_특수문자가_질의문법으로_새지_않는다(self):
        add_entry(self.conn, 'AND OR NOT 은 그냥 글자다')
        for q in ('AND OR', '"따옴표"', 'a*b', '-빼기'):
            self.bodies(q)  # 예외 없이 돌기만 하면 된다

    def test_수정_삭제가_인덱스에_반영된다(self):
        eid = add_entry(self.conn, '지워질 문장 달팽이')
        self.assertEqual(len(self.bodies('달팽이')), 3)
        with self.conn:
            self.conn.execute('UPDATE entries SET body=? WHERE entry_id=?', ('바뀐 문장', eid))
        self.assertEqual(len(self.bodies('달팽이')), 2)
        with self.conn:
            self.conn.execute('DELETE FROM entries WHERE entry_id=?', (eid,))
        self.assertEqual(len(self.bodies('바뀐')), 0)
        self.assertTrue(search.check_index(self.conn))


class QuoteSeed(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = fresh_db()

    def count(self) -> int:
        return self.conn.execute('SELECT count(*) FROM quotes').fetchone()[0]

    def test_시드가_들어간다(self):
        n = seed.seed_quotes(self.conn)
        self.assertGreater(n, 0)
        self.assertEqual(self.count(), n)

    def test_두_번_불러도_늘지_않는다(self):
        seed.seed_quotes(self.conn)
        before = self.count()
        self.assertEqual(seed.seed_quotes(self.conn), 0)
        self.assertEqual(self.count(), before)

    def test_지운_명언은_되살아나지_않는다(self):
        seed.seed_quotes(self.conn)
        with self.conn:
            self.conn.execute("DELETE FROM quotes WHERE quote_id='ko-0001'")
        seed.seed_quotes(self.conn)
        gone = self.conn.execute(
            "SELECT count(*) FROM quotes WHERE quote_id='ko-0001'").fetchone()[0]
        self.assertEqual(gone, 0)

    def test_출처가_모두_채워져_있다(self):
        seed.seed_quotes(self.conn)
        empty = self.conn.execute(
            "SELECT count(*) FROM quotes WHERE trim(source) = ''").fetchone()[0]
        self.assertEqual(empty, 0)

    def test_사용자_명언은_origin이_다르다(self):
        seed.seed_quotes(self.conn)
        seed.add_user_quote(self.conn, 'user-1', '내가 고른 문장', '내 메모')
        origin = self.conn.execute(
            "SELECT origin FROM quotes WHERE quote_id='user-1'").fetchone()[0]
        self.assertEqual(origin, 'user')

    def test_출처_없는_사용자_명언은_거부된다(self):
        with self.assertRaises(ValueError):
            seed.add_user_quote(self.conn, 'user-2', '출처 없음', '  ')


class ColdStart(unittest.TestCase):
    """기록 0건일 때 달팽이가 벙어리가 되지 않아야 한다."""

    def test_시드가_있으면_말할_수_있다(self):
        conn = fresh_db()
        seed.seed_quotes(conn)
        available = {dialogue.Channel.QUOTE} if conn.execute(
            'SELECT count(*) FROM quotes').fetchone()[0] else set()
        self.assertEqual(dialogue.pick_channel(0, available), dialogue.Channel.QUOTE)

    def test_시드가_없으면_침묵한다(self):
        # 이게 시드를 넣기 전의 상태였다. 기록도 명언도 없으면 할 말이 없다.
        self.assertIsNone(dialogue.pick_channel(0, set()))

    def test_기록이_쌓이면_내_기록으로_무게가_옮겨간다(self):
        few = dialogue.effective_weights(3)
        many = dialogue.effective_weights(50)
        self.assertGreater(few[dialogue.Channel.QUOTE], few[dialogue.Channel.MY_NOTE])
        self.assertGreater(many[dialogue.Channel.MY_NOTE], many[dialogue.Channel.QUOTE])


if __name__ == '__main__':
    unittest.main(verbosity=2)
