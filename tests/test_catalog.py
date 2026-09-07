"""4단계 — 서지 검색 어댑터와 표지 저장.

진짜 국중 API 는 여기서 부르지 않는다. 인증키가 없고, 네트워크에 기대는
테스트는 서비스가 문을 닫는 순간 같이 죽는다. 대신 응답을 흉내 내
'우리 쪽 처리'가 옳은지 본다.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from readingsnail.services import catalog                              # noqa: E402
from readingsnail.services.catalog import base, nlk, proxy             # noqa: E402
from readingsnail.services.covers import (                             # noqa: E402
    CoverError, attach_cover, download_cover)
from readingsnail.storage.db import Database                           # noqa: E402
from readingsnail.storage.journal import Journal                       # noqa: E402
from readingsnail.storage.settings import Settings                     # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 64
JPEG = b'\xff\xd8\xff' + b'0' * 64


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def responder(payload, *, raises=None):
    """urlopen 을 대신한다. 요청 URL 을 기록해 둔다."""
    seen = []

    def opener(request, timeout=None):
        seen.append(request.full_url if hasattr(request, 'full_url') else str(request))
        if raises is not None:
            raise raises
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return FakeResponse(body)

    opener.seen = seen
    return opener


NLK_DOC = {
    'TITLE': '월든',
    'SERIES_TITLE': '',
    'AUTHOR': '헨리 데이비드 소로 지음 ; 강승영 옮김',
    'PUBLISHER': '은행나무',
    'EA_ISBN': '9788956609959',
    'SET_ISBN': '',
    'PUBLISH_PREDATE': '20110415',
    'TITLE_URL': 'https://example.org/cover.jpg',
}


class NationalLibrary(unittest.TestCase):
    def test_ISBN이면_isbn_파라미터로_보낸다(self):
        opener = responder({'docs': [NLK_DOC]})
        source = nlk.NationalLibrarySource('키', opener=opener)
        source.search('978-89-566-0995-9')
        url = opener.seen[0]
        self.assertIn('isbn=9788956609959', url)
        self.assertNotIn('title=', url)

    def test_제목이면_title_파라미터로_보낸다(self):
        opener = responder({'docs': [NLK_DOC]})
        nlk.NationalLibrarySource('키', opener=opener).search('월든')
        self.assertIn('title=', opener.seen[0])
        self.assertNotIn('isbn=', opener.seen[0])

    def test_응답을_BookRecord로_옮긴다(self):
        opener = responder({'docs': [NLK_DOC]})
        found = nlk.NationalLibrarySource('키', opener=opener).search('월든')
        self.assertEqual(len(found), 1)
        book = found[0]
        self.assertEqual(book.title, '월든')
        self.assertEqual(book.publisher, '은행나무')
        self.assertEqual(book.isbn13, '9788956609959')
        self.assertEqual(book.published, '2011-04-15')
        self.assertEqual(book.source, 'nl')

    def test_필드_이름이_달라도_통째로_죽지_않는다(self):
        """실물 응답으로 필드명을 확인하지 못했다. 하나가 어긋나도
        검색이 멈추면 안 된다."""
        partial = {'TITLE': '제목만 있는 책'}
        opener = responder({'docs': [partial]})
        found = nlk.NationalLibrarySource('키', opener=opener).search('제목')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].title, '제목만 있는 책')
        self.assertIsNone(found[0].isbn13)
        self.assertIsNone(found[0].publisher)

    def test_제목이_없는_항목은_버린다(self):
        opener = responder({'docs': [{'AUTHOR': '저자만 있음'}, NLK_DOC]})
        found = nlk.NationalLibrarySource('키', opener=opener).search('월든')
        self.assertEqual(len(found), 1)

    def test_총서명이_있으면_제목에_붙인다(self):
        doc = dict(NLK_DOC, SERIES_TITLE='세계문학전집')
        opener = responder({'docs': [doc]})
        found = nlk.NationalLibrarySource('키', opener=opener).search('월든')
        self.assertEqual(found[0].title, '월든 (세계문학전집)')

    def test_결과가_없으면_지어내지_않는다(self):
        opener = responder({'docs': []})
        self.assertEqual(nlk.NationalLibrarySource('키', opener=opener).search('없는책'), [])

    def test_인증키가_없으면_알려준다(self):
        source = nlk.NationalLibrarySource('')
        self.assertFalse(source.available)
        with self.assertRaises(base.CatalogUnavailable):
            source.search('월든')

    def test_서버_오류는_CatalogError(self):
        opener = responder(None, raises=URLError('연결 실패'))
        with self.assertRaises(base.CatalogError):
            nlk.NationalLibrarySource('키', opener=opener).search('월든')

    def test_JSON이_아니면_CatalogError(self):
        opener = responder('<html>서비스 점검 중</html>'.encode('utf-8'))
        with self.assertRaises(base.CatalogError):
            nlk.NationalLibrarySource('키', opener=opener).search('월든')

    def test_응답이_너무_크면_거부한다(self):
        opener = responder(b'{' + b'0' * (base.MAX_RESPONSE_BYTES + 10))
        with self.assertRaises(base.CatalogError):
            nlk.NationalLibrarySource('키', opener=opener).search('월든')

    def test_진단_도구가_실제_키를_보여준다(self):
        """필드명이 틀렸을 때 이걸로 맞춘다."""
        opener = responder({'TOTAL_COUNT': '1', 'docs': [NLK_DOC]})
        info = nlk.NationalLibrarySource('키', opener=opener).describe_response('월든')
        self.assertIn('TITLE_URL', info['doc_keys'])
        self.assertIn('TOTAL_COUNT', info['top_level_keys'])
        self.assertEqual(info['docs_found'], 1)


class Proxy(unittest.TestCase):
    def test_HTTPS만_허용한다(self):
        self.assertFalse(proxy.ProxySource('http://example.org').available)
        self.assertTrue(proxy.ProxySource('https://example.org').available)
        # 개발용 localhost 는 예외
        self.assertTrue(proxy.ProxySource('http://localhost:8787').available)

    def test_자격증명이_박힌_주소는_거부한다(self):
        self.assertFalse(proxy.ProxySource('https://user:pw@example.org').available)

    def test_결과를_옮긴다(self):
        opener = responder({'items': [{'title': '월든', 'author': '소로',
                                       'isbn13': '9788956609959',
                                       'cover': 'https://example.org/c.jpg'}]})
        found = proxy.ProxySource('https://example.org', opener=opener).search('월든')
        self.assertEqual(found[0].title, '월든')
        self.assertEqual(found[0].source, 'proxy')
        self.assertIn('/v1/books/search', opener.seen[0])

    def test_서버가_거절하면_CatalogError(self):
        opener = responder({'error': 'invalid_query'})
        with self.assertRaises(base.CatalogError):
            proxy.ProxySource('https://example.org', opener=opener).search('월든')


class SourceSelection(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database(':memory:')
        self.settings = Settings(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_아무것도_없으면_None(self):
        self.assertIsNone(catalog.build_source(self.settings))

    def test_인증키가_있으면_직접_호출(self):
        self.settings.set(catalog.SETTING_CERT_KEY, '내키')
        self.assertIsInstance(catalog.build_source(self.settings),
                              nlk.NationalLibrarySource)

    def test_프록시가_있으면_프록시가_먼저다(self):
        """키를 앱에 두지 않는 쪽을 고른다."""
        self.settings.set(catalog.SETTING_CERT_KEY, '내키')
        self.settings.set(catalog.SETTING_PROXY, 'https://example.org')
        self.assertIsInstance(catalog.build_source(self.settings), proxy.ProxySource)

    def test_검색_실패가_등록_실패가_되지_않는다(self):
        """서지 서비스는 또 문을 닫는다. 예외를 밖으로 흘리지 않는다."""
        opener = responder(None, raises=URLError('죽음'))
        source = nlk.NationalLibrarySource('키', opener=opener)
        self.assertEqual(catalog.search_books(source, '월든'), [])
        self.assertEqual(catalog.search_books(None, '월든'), [])


class NoNotesLeaveTheMachine(unittest.TestCase):
    """기록 본문은 이 계층에 들어오지도 않는다."""

    def test_서지_계층은_저장소를_임포트하지_않는다(self):
        """주석이 아니라 실제 임포트를 본다.

        기록에 닿을 수단이 아예 없어야 '기록이 나가지 않는다'가 구조로 보장된다.
        """
        import ast
        import inspect
        for module in (base, nlk, proxy, catalog):
            tree = ast.parse(inspect.getsource(module))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported.add(node.module or '')
                    imported.update(a.name for a in node.names)
            for forbidden in ('journal', 'Journal', 'storage', 'db', 'Database',
                              'recall', 'speaker'):
                self.assertNotIn(forbidden, imported,
                                 f'{module.__name__} 이 {forbidden} 을 임포트한다')

    def test_서지_계층_함수는_기록을_받지_않는다(self):
        import inspect
        for source in (nlk.NationalLibrarySource, proxy.ProxySource):
            params = set(inspect.signature(source.search).parameters)
            self.assertEqual(params, {'self', 'query', 'limit'},
                             f'{source.__name__}.search 가 예상 밖 인자를 받는다')

    def test_검색어만_나간다(self):
        opener = responder({'docs': []})
        nlk.NationalLibrarySource('키', opener=opener).search('월든')
        self.assertNotIn('note', opener.seen[0].lower())


class Covers(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db = Database(':memory:')
        self.journal = Journal(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_내려받아_로컬에_둔다(self):
        path = download_cover('https://example.org/c.png', self.tmp,
                              opener=responder(PNG))
        self.assertTrue(path.is_file())
        self.assertEqual(path.suffix, '.png')
        self.assertEqual(path.read_bytes(), PNG)

    def test_확장자는_내용으로_정한다(self):
        """Content-Type 을 믿지 않는다. 주소가 .png 여도 내용이 jpeg 면 jpg."""
        path = download_cover('https://example.org/거짓말.png', self.tmp,
                              opener=responder(JPEG))
        self.assertEqual(path.suffix, '.jpg')

    def test_이미지가_아니면_거부한다(self):
        with self.assertRaises(CoverError):
            download_cover('https://example.org/c.png', self.tmp,
                           opener=responder(b'<html>not found</html>'))

    def test_같은_표지를_두_번_받지_않는다(self):
        opener = responder(PNG)
        first = download_cover('https://example.org/c.png', self.tmp, opener=opener)
        second = download_cover('https://example.org/c.png', self.tmp, opener=opener)
        self.assertEqual(first, second)
        self.assertEqual(len(opener.seen), 1)

    def test_파일_이름에_책_제목이_드러나지_않는다(self):
        path = download_cover('https://example.org/월든표지.png', self.tmp,
                              opener=responder(PNG))
        self.assertNotIn('월든', path.name)

    def test_너무_크면_거부한다(self):
        big = PNG + b'0' * (4 * 1024 * 1024)
        with self.assertRaises(CoverError):
            download_cover('https://example.org/c.png', self.tmp, opener=responder(big))

    def test_이상한_주소는_거부한다(self):
        for bad in ('ftp://example.org/c.png', 'file:///etc/passwd',
                    'https://user:pw@example.org/c.png', ''):
            with self.assertRaises(CoverError):
                download_cover(bad, self.tmp, opener=responder(PNG))

    def test_책에_로컬_경로가_붙는다(self):
        book = self.journal.add_book('월든')
        path = attach_cover(self.journal, book.book_id, 'https://example.org/c.png',
                            self.tmp, opener=responder(PNG))
        stored = self.journal.get_book(book.book_id).cover_path
        self.assertEqual(stored, str(path))
        self.assertNotIn('http', stored, 'DB 에 외부 URL 이 들어갔다')

    def test_표지_실패가_책_등록을_무르지_않는다(self):
        book = self.journal.add_book('월든')
        result = attach_cover(self.journal, book.book_id, 'https://example.org/c.png',
                              self.tmp, opener=responder(None, raises=URLError('죽음')))
        self.assertIsNone(result)
        self.assertIsNotNone(self.journal.get_book(book.book_id))
        self.assertIsNone(self.journal.get_book(book.book_id).cover_path)


class ISBN(unittest.TestCase):
    def test_붙임표를_지운다(self):
        self.assertEqual(base.normalize_isbn('978-89-566-0995-9'), '9788956609959')
        self.assertEqual(base.normalize_isbn('89 566 0995 4'), '8956609954')

    def test_ISBN이_아니면_빈_문자열(self):
        for bad in ('월든', '123', '', '12345678901234567'):
            self.assertEqual(base.normalize_isbn(bad), '')

    def test_말단_X를_살린다(self):
        self.assertEqual(base.normalize_isbn('0-8044-2957-X'), '080442957X')


if __name__ == '__main__':
    unittest.main(verbosity=2)


class SecretsDoNotLeak(unittest.TestCase):
    """국중 API 는 인증키를 질의 문자열로 받는다. URL 이 로그나 예외에 섞이면
    키가 그대로 드러난다."""

    def test_오류_메시지에서_키를_가린다(self):
        for text, hidden in (
            ('https://x/api?cert_key=SECRET&a=1', 'SECRET'),
            ('<urlopen error ttbkey=ABC123>', 'ABC123'),
            ('?api_key=zzz&token=qqq', 'zzz'),
        ):
            masked = base.redact(text)
            self.assertNotIn(hidden, masked)
            self.assertIn('***', masked)

    def test_평범한_문장은_건드리지_않는다(self):
        self.assertEqual(base.redact('서지 서버에 닿지 못했다'), '서지 서버에 닿지 못했다')

    def test_네트워크_오류에_키가_묻어나오지_않는다(self):
        opener = responder(None, raises=URLError('failed for cert_key=SECRET-123'))
        with self.assertRaises(base.CatalogError) as caught:
            nlk.NationalLibrarySource('SECRET-123', opener=opener).search('월든')
        self.assertNotIn('SECRET-123', str(caught.exception))

    def test_진단_출력에도_키가_없다(self):
        opener = responder({'docs': [NLK_DOC]})
        info = nlk.NationalLibrarySource('SECRET-123', opener=opener).describe_response('월든')
        self.assertNotIn('SECRET-123', json.dumps(info, default=str))


class ConcurrentCovers(unittest.TestCase):
    """책을 연달아 등록하면 같은 표지를 여러 스레드가 동시에 받는다."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_동시에_받아도_충돌하지_않는다(self):
        import threading
        import time

        def slow(request, timeout=None):
            time.sleep(0.02)
            return FakeResponse(PNG)

        results, errors = [], []

        def worker():
            try:
                results.append(download_cover('https://example.org/same.png',
                                              self.tmp, opener=slow))
            except Exception as exc:                      # noqa: BLE001
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [], f'동시 다운로드가 충돌했다: {errors}')
        self.assertEqual(len(set(results)), 1)
        files = list((self.tmp / 'covers').iterdir())
        self.assertEqual(len(files), 1)
        self.assertFalse([f for f in files if '.part' in f.name], '임시 파일이 남았다')

    def test_받는_중인_임시_파일을_표지라고_돌려주지_않는다(self):
        # 경합 없이 그 상황만 만들어 둔다. `glob(f'{stem}.*')` 로 찾으면
        # 다른 스레드가 쓰는 중인 .part 를 잡아, 곧 사라질 경로가 DB 에 박힌다.
        import hashlib

        from readingsnail.services.covers import covers_dir
        url = 'https://example.org/same.png'
        stem = hashlib.sha256(url.encode('utf-8')).hexdigest()[:24]
        folder = covers_dir(self.tmp)
        (folder / f'{stem}.png.deadbeef.part').write_bytes(PNG[:4])   # 절반만 쓰인 파일

        got = download_cover(url, self.tmp, opener=lambda r, timeout=None:
                             FakeResponse(PNG))
        self.assertNotIn('.part', got.name, f'받는 중인 파일을 돌려줬다: {got.name}')
        self.assertTrue(got.is_file())
        self.assertEqual(got.read_bytes(), PNG)


class MalformedResponses(unittest.TestCase):
    """서버가 무엇을 보낼지 모른다. 무엇이 와도 검색이 죽지 않아야 한다."""

    def test_이상한_docs를_견딘다(self):
        for payload in ({'docs': 'not a list'}, {'docs': [None, 3, 'x']}, {},
                        {'docs': [{}]}, {'docs': [{'TITLE': None}]},
                        {'docs': [{'TITLE': '   '}]}):
            found = nlk.NationalLibrarySource('키', opener=responder(payload)).search('q')
            self.assertEqual(found, [])

    def test_객체가_아닌_JSON은_거부한다(self):
        for raw in (b'[1,2,3]', b'"string"', b'null', b'42'):
            with self.assertRaises(base.CatalogError):
                nlk.NationalLibrarySource('키', opener=responder(raw)).search('q')

    def test_검색어_특수문자가_질의를_망가뜨리지_않는다(self):
        for query in ('월든 & 소로', '100% 짜리', 'a=b&c=d', '"따옴표"', '../etc/passwd'):
            opener = responder({'docs': []})
            nlk.NationalLibrarySource('키', opener=opener).search(query)
            url = opener.seen[0]
            self.assertTrue(url.startswith(nlk.ENDPOINT + '?'))
            self.assertNotIn(' ', url)
            self.assertNotIn('\n', url)


class NetworkHardening(unittest.TestCase):
    """서지·표지 응답은 외부에서 온다. 그대로 믿지 않는다."""

    def test_https에서_http로의_리다이렉트를_따르지_않는다(self):
        """국중 API 는 인증키를 질의 문자열로 보낸다.
        강등된 리다이렉트 한 번이면 키가 평문으로 나간다."""
        handler = base._NoDowngradeRedirect()
        from urllib.request import Request
        secure = Request('https://nl.go.kr/x?cert_key=SECRET')
        with self.assertRaises(base.CatalogError):
            handler.redirect_request(secure, None, 302, 'Found', {},
                                     'http://evil.example/x?cert_key=SECRET')

    def test_https끼리는_따라간다(self):
        from urllib.request import Request
        handler = base._NoDowngradeRedirect()
        secure = Request('https://nl.go.kr/x')
        result = handler.redirect_request(secure, None, 302, 'Found', {},
                                          'https://nl.go.kr/y')
        self.assertIsNotNone(result)

    def test_내부망_주소를_알아본다(self):
        for private in ('127.0.0.1', 'localhost', '169.254.169.254',
                        '10.0.0.5', '192.168.1.1', '::1', ''):
            self.assertTrue(base.is_private_host(private), private)
        for public in ('8.8.8.8', 'www.nl.go.kr', '1.1.1.1'):
            self.assertFalse(base.is_private_host(public), public)

    def test_표지가_내부망을_두드리지_못한다(self):
        """표지 주소는 외부 서비스 응답에서 온다. 클라우드 메타데이터 주소가
        섞여 오면 앱이 대신 두드려 주는 통로가 된다."""
        with TemporaryDirectory() as tmp:
            for bad in ('http://127.0.0.1/c.png',
                        'http://169.254.169.254/latest/meta-data/',
                        'http://localhost:8080/c.png',
                        'http://10.0.0.5/c.png'):
                with self.assertRaises(CoverError, msg=bad):
                    download_cover(bad, Path(tmp), opener=responder(PNG))

    def test_정상_외부_주소는_통과한다(self):
        with TemporaryDirectory() as tmp:
            path = download_cover('https://images.example.org/c.png', Path(tmp),
                                  opener=responder(PNG))
            self.assertTrue(path.is_file())
