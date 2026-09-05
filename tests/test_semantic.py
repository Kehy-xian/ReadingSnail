"""3단계 — 임베딩 저장, 의미 검색, 발화 엔진.

진짜 모델(onnxruntime + multilingual-e5-small)은 여기서 돌리지 않는다.
번들 모델 없이도 파이프라인 전체가 옳은지 봐야 하므로 가짜 인코더를 쓴다.
가짜는 글자 n-gram 으로 벡터를 만든다 — 비슷한 문장이 가까워지는 성질만
같으면 배관을 검증하는 데는 충분하다.
"""

from __future__ import annotations

import math
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from readingsnail.nlp import vectors                                  # noqa: E402
from readingsnail.nlp.encoder import E5Encoder, EncoderUnavailable    # noqa: E402
from readingsnail.services import dialogue, recall                    # noqa: E402
from readingsnail.services.embedding import EmbeddingWorker           # noqa: E402
from readingsnail.services.speaker import (                           # noqa: E402
    Speaker, prune_utterance_log, recent_refs)
from readingsnail.storage.db import Database                          # noqa: E402
from readingsnail.storage.journal import Journal                      # noqa: E402
from readingsnail.storage.seed import seed_quotes                     # noqa: E402

FAKE_MODEL = 'fake-ngram-v1'


class FakeEncoder:
    """글자 3-gram 해시 벡터. 비슷한 문장이 가까워진다."""

    MODEL_ID = FAKE_MODEL

    def __init__(self, dim: int = 64, fail: bool = False):
        self.dim = dim
        self.fail = fail
        self.calls = 0

    def encode(self, texts, *, kind='passage'):
        self.calls += 1
        if self.fail:
            raise EncoderUnavailable('모델 없음')
        out = []
        for text in texts:
            buckets = [0.0] * self.dim
            body = str(text or '')
            for i in range(max(0, len(body) - 2)):
                buckets[hash(body[i:i + 3]) % self.dim] += 1.0
            out.append(vectors.normalize(buckets))
        return out

    def encode_one(self, text, *, kind='passage'):
        rows = self.encode([text], kind=kind)
        if not rows:
            raise EncoderUnavailable('빈 문장')
        return rows[0]


class Vectors(unittest.TestCase):
    def test_왕복해도_값이_보존된다(self):
        rng = random.Random(3)
        values = vectors.normalize([rng.gauss(0, 1) for _ in range(384)])
        restored = vectors.unpack(vectors.pack(values))
        self.assertEqual(len(restored), 384)
        for a, b in zip(values, restored):
            self.assertAlmostEqual(a, b, places=6)

    def test_자기_자신과의_유사도는_1(self):
        v = vectors.normalize([1.0, 2.0, 3.0])
        self.assertAlmostEqual(vectors.cosine(v, v), 1.0, places=9)

    def test_반대_방향은_음수(self):
        self.assertAlmostEqual(vectors.cosine([1, 0], [-1, 0]), -1.0, places=9)

    def test_길이가_다르면_비교하지_않는다(self):
        self.assertEqual(vectors.cosine([1, 0], [1, 0, 0]), 0.0)

    def test_영벡터는_0(self):
        self.assertEqual(vectors.cosine([0, 0], [1, 1]), 0.0)
        self.assertEqual(vectors.normalize([0.0, 0.0]), [0.0, 0.0])

    def test_빈_값과_깨진_바이트(self):
        self.assertIsNone(vectors.unpack(None))
        self.assertIsNone(vectors.unpack(b''))
        with self.assertRaises(vectors.VectorError):
            vectors.unpack(b'\x00\x00\x00')

    def test_깨진_후보는_건너뛴다(self):
        good = vectors.pack([1.0, 0.0])
        hits = vectors.nearest([1.0, 0.0], [('bad', b'\x01'), ('good', good)])
        self.assertEqual([h[0] for h in hits], ['good'])

    def test_차원이_다른_후보도_건너뛴다(self):
        hits = vectors.nearest([1.0, 0.0], [('wrong', vectors.pack([1.0, 0.0, 0.0]))])
        self.assertEqual(hits, [])

    def test_문턱_아래는_돌려주지_않는다(self):
        far = vectors.pack([0.0, 1.0])
        self.assertEqual(vectors.nearest([1.0, 0.0], [('far', far)], threshold=0.5), [])

    def test_제외_목록(self):
        v = vectors.pack([1.0, 0.0])
        self.assertEqual(vectors.nearest([1.0, 0.0], [('me', v)], exclude=('me',)), [])


class Encoder(unittest.TestCase):
    def test_모델이_없으면_알려준다(self):
        enc = E5Encoder(ROOT / '없는폴더')
        self.assertFalse(enc.available)
        self.assertEqual(sorted(enc.missing_files()), ['model.onnx', 'tokenizer.json'])
        with self.assertRaises(EncoderUnavailable):
            enc.encode(['본문'])

    def test_한_번_실패하면_계속_찾지_않는다(self):
        """없는 모델을 매번 찾으러 가면 그게 곧 상시 추론이다."""
        enc = E5Encoder(ROOT / '없는폴더')
        with self.assertRaises(EncoderUnavailable):
            enc.encode(['본문'])
        self.assertIsNotNone(enc._failure)
        enc.reset_failure()
        self.assertIsNone(enc._failure)

    def test_kind_는_둘_중_하나(self):
        with self.assertRaises(ValueError):
            E5Encoder(ROOT).encode(['본문'], kind='엉뚱')


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database(':memory:')
        self.journal = Journal(self.db)
        self.encoder = FakeEncoder()
        self.worker = EmbeddingWorker(self.journal, self.encoder, model=FAKE_MODEL)

    def tearDown(self) -> None:
        self.worker.stop()
        self.db.close()

    def drain(self) -> None:
        while self.worker.drain_once():
            pass


class Worker(Base):
    def test_저장이_분석보다_먼저다(self):
        entry = self.journal.add_entry('벡터 없이도 이미 저장돼 있다')
        self.assertFalse(entry.has_embedding)
        self.assertEqual(self.worker.pending, 1)

    def test_뒤에서_벡터가_채워진다(self):
        for i in range(20):
            self.journal.add_entry(f'기록 {i}번')
        self.drain()
        self.assertEqual(self.worker.pending, 0)
        self.assertEqual(self.worker.encoded, 20)
        self.assertTrue(all(e.has_embedding for e in self.journal.recent_entries(limit=50)))

    def test_모델이_없으면_조용히_멈춘다(self):
        broken = EmbeddingWorker(self.journal, FakeEncoder(fail=True), model=FAKE_MODEL)
        self.journal.add_entry('기록은 남는다')
        self.assertFalse(broken.drain_once())
        self.assertFalse(broken.drain_once())
        self.assertEqual(broken.encoder.calls, 1, '없는 모델을 반복해서 찾았다')
        self.assertEqual(self.journal.count_entries(), 1)

    def test_모델을_바꾸면_다시_인코딩한다(self):
        self.journal.add_entry('옛 모델로 만든 기록')
        self.drain()
        self.assertEqual(self.worker.pending, 0)
        newer = EmbeddingWorker(self.journal, FakeEncoder(), model='fake-int8-v2')
        self.assertEqual(newer.pending, 1, '좌표계가 다른 벡터를 그대로 뒀다')
        while newer.drain_once():
            pass
        self.assertEqual(newer.pending, 0)

    def test_본문을_고치면_다시_대기열에_들어간다(self):
        entry = self.journal.add_entry('원래 문장')
        self.drain()
        self.assertEqual(self.worker.pending, 0)
        self.journal.revise_entry(entry.entry_id, '고친 문장')
        self.assertEqual(self.worker.pending, 1)

    def test_스레드로_돌려도_동작한다(self):
        import time
        done = []
        worker = EmbeddingWorker(self.journal, FakeEncoder(), model=FAKE_MODEL,
                                 on_done=done.append)
        worker.start()
        for i in range(12):
            self.journal.add_entry(f'스레드 기록 {i}')
        worker.wake()
        # 부하가 걸린 기계에서도 흔들리지 않게 넉넉히 기다린다.
        deadline = time.time() + 10
        while time.time() < deadline and worker.pending:
            time.sleep(0.01)
        worker.stop()
        self.assertEqual(worker.pending, 0)
        self.assertEqual(len(done), 12)


class Recall(Base):
    def setUp(self) -> None:
        super().setUp()
        self.book = self.journal.add_book('월든', author='헨리 데이비드 소로')

    def test_비슷한_과거_기록을_찾는다(self):
        old = self.journal.add_entry('숲으로 간 이유를 오래 생각했다', book_id=self.book.book_id)
        self.journal.add_entry('오늘 점심은 김치찌개였다')
        new = self.journal.add_entry('숲으로 간 이유를 다시 생각했다')
        self.drain()
        found = recall.similar_entry(self.journal, source_entry_id=new.entry_id,
                                     model=FAKE_MODEL, threshold=0.3)
        self.assertIsNotNone(found)
        self.assertEqual(found.entry.entry_id, old.entry_id)
        self.assertEqual(found.book_title, '월든')

    def test_억지로_이어붙이지_않는다(self):
        self.journal.add_entry('전혀 관계없는 요리 이야기')
        new = self.journal.add_entry('숲으로 간 이유를 오래 생각했다')
        self.drain()
        found = recall.similar_entry(self.journal, source_entry_id=new.entry_id,
                                     model=FAKE_MODEL, threshold=0.9)
        self.assertIsNone(found, '유사도가 낮은데도 이어붙였다')

    def test_자기_자신을_돌려주지_않는다(self):
        only = self.journal.add_entry('혼자 있는 기록')
        self.drain()
        found = recall.similar_entry(self.journal, source_entry_id=only.entry_id,
                                     model=FAKE_MODEL, threshold=0.0)
        self.assertIsNone(found)

    def test_벡터가_없으면_아무것도_안_한다(self):
        entry = self.journal.add_entry('아직 인코딩 안 된 기록')
        self.assertIsNone(recall.similar_entry(
            self.journal, source_entry_id=entry.entry_id, model=FAKE_MODEL))

    def test_다른_모델의_벡터와_섞지_않는다(self):
        """좌표계가 다르면 유사도는 숫자일 뿐이다."""
        self.journal.add_entry('숲으로 간 이유를 오래 생각했다')
        new = self.journal.add_entry('숲으로 간 이유를 다시 생각했다')
        self.drain()
        found = recall.similar_entry(self.journal, source_entry_id=new.entry_id,
                                     model='다른모델', threshold=0.0)
        self.assertIsNone(found)

    def test_문장으로_과거를_찾는다(self):
        self.journal.add_entry('숲으로 간 이유를 오래 생각했다', book_id=self.book.book_id)
        self.journal.add_entry('오늘 점심은 김치찌개였다')
        self.drain()
        hits = recall.similar_to_text(self.journal, self.encoder, '숲으로 간 이유',
                                      model=FAKE_MODEL, threshold=0.2)
        self.assertTrue(hits)
        self.assertIn('숲으로', hits[0].entry.body)

    def test_모델이_없으면_빈_목록(self):
        self.journal.add_entry('기록')
        self.drain()
        hits = recall.similar_to_text(self.journal, FakeEncoder(fail=True), '질의',
                                      model=FAKE_MODEL)
        self.assertEqual(hits, [])


class SpeakerEngine(Base):
    def setUp(self) -> None:
        super().setUp()
        with self.db.connect() as con:
            seed_quotes(con)
        self.speaker = Speaker(self.journal, rng=random.Random(5))

    def speak(self):
        with self.db.write() as con:
            return self.speaker.speak(con)

    def test_기록이_없으면_명언을_꺼낸다(self):
        spoken = self.speak()
        self.assertIsNotNone(spoken)
        self.assertIs(spoken.utterance.channel, dialogue.Channel.QUOTE)

    def test_명언도_없으면_조용히_있는다(self):
        with self.db.write() as con:
            con.execute('DELETE FROM quotes')
        self.assertIsNone(self.speak())

    def test_같은_말을_연속으로_하지_않는다(self):
        for i in range(30):
            self.journal.add_entry(f'서로 다른 기록 {i}')
        said = [self.speak() for _ in range(dialogue.RECENT_BLOCK)]
        refs = [s.utterance.ref_id for s in said if s]
        self.assertEqual(len(refs), len(set(refs)), f'같은 항목을 다시 꺼냈다: {refs}')

    def test_발화_이력이_남는다(self):
        self.journal.add_entry('기록')
        self.speak()
        with self.db.connect() as con:
            self.assertEqual(len(recent_refs(con)), 1)

    def test_모두_막히면_제외를_풀고_말한다(self):
        """후보가 최근 발화보다 적으면 영영 침묵할 수 있다."""
        self.journal.add_entry('단 하나뿐인 기록')
        with self.db.write() as con:
            con.execute('DELETE FROM quotes')
        first = self.speak()
        self.assertIsNotNone(first)
        for _ in range(5):
            self.assertIsNotNone(self.speak(), '후보가 하나뿐일 때 침묵했다')

    def test_필사와_생각을_구분해_말한다(self):
        book = self.journal.add_book('월든')
        for i in range(10):
            self.journal.add_entry(f'필사 {i}', book_id=book.book_id, kind='quote')
        seen = set()
        for _ in range(40):
            spoken = self.speak()
            if spoken:
                seen.add(spoken.utterance.channel)
        self.assertIn(dialogue.Channel.BOOK_QUOTE, seen)

    def test_위시리스트와_정체된_책도_말한다(self):
        self.journal.add_book('언젠가 읽을 책', status='wishlist')
        self.journal.add_book('방치된 책', added_at='2020-01-01 00:00:00')
        for i in range(5):
            self.journal.add_entry(f'기록 {i}')
        seen = set()
        for _ in range(120):
            spoken = self.speak()
            if spoken:
                seen.add(spoken.utterance.channel)
        self.assertIn(dialogue.Channel.WISHLIST, seen)
        self.assertIn(dialogue.Channel.STALLED, seen)

    def test_죄책감을_주지_않는다(self):
        self.journal.add_book('방치된 책', added_at='2020-01-01 00:00:00')
        for i in range(3):
            self.journal.add_entry(f'기록 {i}')
        texts = [s.utterance.text for s in (self.speak() for _ in range(80)) if s]
        for bad in ('일째', '안 읽', '며칠', '벌써', '아직도 안'):
            self.assertFalse(any(bad in t for t in texts),
                             f'재촉하는 표현이 섞였다: {bad}')

    def test_되살리기_한마디(self):
        book = self.journal.add_book('월든')
        old = self.journal.add_entry('숲으로 간 이유를 오래 생각했다', book_id=book.book_id)
        new = self.journal.add_entry('숲으로 간 이유를 다시 생각했다')
        self.drain()
        found = recall.similar_entry(self.journal, source_entry_id=new.entry_id,
                                     model=FAKE_MODEL, threshold=0.3)
        self.assertIsNotNone(found)
        with self.db.write() as con:
            spoken = self.speaker.echo(con, found)
        self.assertIn(old.body, spoken.utterance.text)
        self.assertEqual(spoken.entry_id, old.entry_id)

    def test_발화_이력이_무한히_쌓이지_않는다(self):
        for i in range(60):
            self.journal.add_entry(f'기록 {i}')
        for _ in range(40):
            self.speak()
        with self.db.write() as con:
            prune_utterance_log(con, keep=10)
            n = con.execute('SELECT count(*) AS n FROM utterance_log').fetchone()['n']
        self.assertEqual(n, 10)


class ColdStartWeights(unittest.TestCase):
    def test_기록이_쌓이면_명언에서_내_기록으로(self):
        few = dialogue.effective_weights(3)
        many = dialogue.effective_weights(50)
        self.assertGreater(few[dialogue.Channel.QUOTE], few[dialogue.Channel.MY_NOTE])
        self.assertGreater(many[dialogue.Channel.MY_NOTE], many[dialogue.Channel.QUOTE])

    def test_문턱값은_명세대로다(self):
        self.assertEqual(dialogue.ECHO_MIN_SIMILARITY, 0.72)
        self.assertEqual(dialogue.ECHO_DELAY_SEC, (90, 300))


if __name__ == '__main__':
    unittest.main(verbosity=2)


class QuoteRepetition(Base):
    """명언도 반복을 막아야 한다. ref_id 가 아니라 entry_id 로 이력을 남기면
    명언은 둘 다 None 이라 이력에서 빠지고, 같은 명언이 계속 나온다."""

    def setUp(self) -> None:
        super().setUp()
        with self.db.connect() as con:
            seed_quotes(con)
        self.speaker = Speaker(self.journal, rng=random.Random(9))

    def test_명언도_이력에_남는다(self):
        with self.db.write() as con:
            spoken = self.speaker.speak(con)
        self.assertIs(spoken.utterance.channel, dialogue.Channel.QUOTE)
        with self.db.connect() as con:
            self.assertIn(spoken.utterance.ref_id, recent_refs(con))

    def test_명언이_연달아_반복되지_않는다(self):
        said = []
        for _ in range(dialogue.RECENT_BLOCK):
            with self.db.write() as con:
                spoken = self.speaker.speak(con)
            if spoken:
                said.append(spoken.utterance.ref_id)
        self.assertEqual(len(said), len(set(said)), f'같은 명언을 다시 꺼냈다: {said}')


class WorkerTermination(Base):
    """진전이 없으면 멈춰야 한다.

    drain_once 가 아무것도 못 썼는데 True 를 돌려주면 같은 배치를 영원히 다시
    집어와 CPU 를 태운다(실측 2초에 26만 회).
    """

    def test_인코더가_이상한_값을_주면_멈춘다(self):
        class BadEncoder:
            MODEL_ID = 'bad'

            def encode(self, texts, *, kind='passage'):
                return [['숫자가 아님'] * 8 for _ in texts]

        worker = EmbeddingWorker(self.journal, BadEncoder(), model='bad')
        self.journal.add_entry('기록 하나')
        rounds = 0
        while worker.drain_once() and rounds < 100:
            rounds += 1
        self.assertLess(rounds, 5, '진전 없이 계속 돌았다')
        self.assertEqual(self.journal.count_entries(), 1, '기록이 사라졌다')
        self.assertGreater(worker.failed, 0)
        self.assertEqual(worker.pending, 1, '대기열에는 남아 다음에 다시 시도한다')

    def test_스레드로_돌려도_CPU를_태우지_않는다(self):
        import time

        class BadEncoder:
            MODEL_ID = 'bad'
            calls = 0

            def encode(self, texts, *, kind='passage'):
                BadEncoder.calls += 1
                return [['숫자가 아님'] * 8 for _ in texts]

        worker = EmbeddingWorker(self.journal, BadEncoder(), model='bad')
        self.journal.add_entry('기록')
        worker.start()
        time.sleep(0.3)
        worker.stop()
        # 진전이 없으면 멈추므로 몇 번 돌지 않아야 한다. 넉넉히 잡아도
        # 무한 루프(2초에 26만 회)와는 자릿수가 다르다.
        self.assertLess(BadEncoder.calls, 50, f'0.3초에 {BadEncoder.calls}회 돌았다')

    def test_일부만_실패해도_나머지는_들어간다(self):
        class Flaky:
            MODEL_ID = FAKE_MODEL

            def encode(self, texts, *, kind='passage'):
                good = FakeEncoder().encode(texts, kind=kind)
                return [(['숫자가 아님'] * 8) if '불량' in t else v
                        for t, v in zip(texts, good)]

        for i in range(4):
            self.journal.add_entry(f'정상 기록 {i}')
        self.journal.add_entry('불량 기록')
        worker = EmbeddingWorker(self.journal, Flaky(), model=FAKE_MODEL)
        rounds = 0
        while worker.drain_once() and rounds < 20:
            rounds += 1
        self.assertEqual(worker.encoded, 4)
        self.assertEqual(worker.pending, 1)
        self.assertLess(rounds, 20)
