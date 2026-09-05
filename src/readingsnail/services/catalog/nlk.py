"""국립중앙도서관 ISBN 서지정보.

  문서: https://www.nl.go.kr/NL/contents/N31101030500.do
  요청: https://www.nl.go.kr/seoji/SearchApi.do?cert_key=...&result_style=json

⚠ 필드명 확인에 대하여
    이 코드를 쓴 환경에서는 국중 문서와 공공데이터포털이 모두 막혀 있어
    **응답 필드명을 실물로 확인하지 못했다.** 아래 FIELDS 는 널리 통용되는
    이름을 적어 둔 것이다.

    그래서 이렇게 짰다.
      · 필드 이름을 **FIELDS 한 곳에만** 둔다. 틀렸으면 여기만 고치면 된다.
      · 없는 필드는 None 이 된다. 이름이 하나 달라도 검색이 통째로 죽지 않는다.
      · describe_response() 가 실제 응답의 키를 그대로 뱉는다.
        cert_key 를 받으면 이걸 한 번 돌려 FIELDS 를 맞출 것.

cert_key 를 어디에 두는가
    데스크톱 앱에 키를 넣으면 배포하는 순간 공개된다. 그래서 두 갈래를 둔다.
      1. 사용자가 자기 키를 직접 발급받아 설정에 넣는다 (기본)
      2. 프록시(Cloudflare Worker)를 두고 키는 서버에만 둔다 → proxy.py
    둘 다 BookSource 라 나머지 코드는 구분하지 않는다.
"""

from __future__ import annotations

from urllib.parse import urlencode

from .base import (BookRecord, CatalogError, CatalogUnavailable, fetch_json,
                   looks_like_isbn, normalize_isbn, redact)

ENDPOINT = 'https://www.nl.go.kr/seoji/SearchApi.do'
SOURCE_NAME = 'nl'

# ⚠ 실제 응답으로 한 번 검증할 것. 틀렸다면 **여기만** 고치면 된다.
#   describe_response() 로 실물 키를 확인할 수 있다.
FIELDS = {
    'title': ('TITLE',),
    'series': ('SERIES_TITLE',),
    'author': ('AUTHOR',),
    'publisher': ('PUBLISHER',),
    'isbn': ('EA_ISBN', 'SET_ISBN'),
    'published': ('PUBLISH_PREDATE', 'REAL_PUBLISH_DATE'),
    'cover': ('TITLE_URL',),
}
DOCS_KEYS = ('docs', 'DOCS', 'result')
MAX_PAGE_SIZE = 50


def _pick(doc: dict, names: tuple[str, ...]) -> str:
    """여러 후보 이름 중 값이 있는 첫 번째. 없으면 빈 문자열."""
    for name in names:
        value = doc.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ''


def _docs(payload: dict) -> list[dict]:
    for key in DOCS_KEYS:
        rows = payload.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def to_record(doc: dict) -> BookRecord | None:
    """응답 한 건 → BookRecord. 제목이 없으면 버린다."""
    title = _pick(doc, FIELDS['title'])
    if not title:
        return None
    series = _pick(doc, FIELDS['series'])
    if series and series != title:
        title = f'{title} ({series})'

    published = _pick(doc, FIELDS['published'])
    if len(published) == 8 and published.isdigit():        # YYYYMMDD
        published = f'{published[:4]}-{published[4:6]}-{published[6:]}'

    return BookRecord(
        title=title,
        author=_pick(doc, FIELDS['author']),
        publisher=_pick(doc, FIELDS['publisher']) or None,
        isbn13=normalize_isbn(_pick(doc, FIELDS['isbn'])) or None,
        published=published or None,
        cover_url=_pick(doc, FIELDS['cover']) or None,
        source=SOURCE_NAME,
    )


class NationalLibrarySource:
    """국중 ISBN 서지정보. 사용자가 자기 cert_key 를 넣어 쓴다."""

    name = SOURCE_NAME

    def __init__(self, cert_key: str, *, endpoint: str = ENDPOINT, opener=None):
        self.cert_key = str(cert_key or '').strip()
        self.endpoint = endpoint
        self.opener = opener

    @property
    def available(self) -> bool:
        return bool(self.cert_key)

    def _url(self, query: str, *, limit: int) -> str:
        params = {
            'cert_key': self.cert_key,
            'result_style': 'json',
            'page_no': '1',
            'page_size': str(max(1, min(int(limit), MAX_PAGE_SIZE))),
        }
        isbn = normalize_isbn(query)
        if isbn:
            params['isbn'] = isbn
        else:
            # 제목 검색. 저자까지 한 칸에 치는 사람이 많아 title 로만 보낸다.
            params['title'] = query.strip()
        return f'{self.endpoint}?{urlencode(params)}'

    def search(self, query: str, *, limit: int = 10) -> list[BookRecord]:
        if not self.available:
            raise CatalogUnavailable('국립중앙도서관 인증키(cert_key)가 없다')
        text = str(query or '').strip()
        if not text:
            return []
        if len(text) > 200:
            raise CatalogError('검색어가 너무 길다')

        payload = fetch_json(self._url(text, limit=limit), opener=self.opener)
        records = []
        for doc in _docs(payload):
            record = to_record(doc)
            if record is not None:
                records.append(record)
        # ISBN 으로 찾았는데 결과가 없으면 그대로 빈 목록이다. 지어내지 않는다.
        return records[:limit]

    def describe_response(self, query: str) -> dict:
        """실제 응답의 키를 그대로 돌려준다. FIELDS 를 맞출 때 쓴다.

        cert_key 를 받으면 한 번 돌려볼 것:
            python -c "from readingsnail.services.catalog.nlk import *; \\
                       print(NationalLibrarySource('키').describe_response('9788932917245'))"
        """
        payload = fetch_json(self._url(query, limit=1), opener=self.opener)
        docs = _docs(payload)
        return {
            'request': redact(self._url(query, limit=1)),   # 키는 가려서 보여준다
            'top_level_keys': sorted(payload),
            'docs_found': len(docs),
            'doc_keys': sorted(docs[0]) if docs else [],
            'mapped': to_record(docs[0]) if docs else None,
        }


__all__ = ['NationalLibrarySource', 'to_record', 'FIELDS', 'ENDPOINT',
           'SOURCE_NAME', 'looks_like_isbn']
