"""프록시(Cloudflare Worker) 경유 서지 검색.

데스크톱 앱에 인증키를 넣으면 배포하는 순간 공개된다. 키를 서버에만 두고
앱은 결과만 받아오는 길이 이것이다.

전작 cloudflare/src/index.ts 의 `/v1/books/search` 를 그대로 쓰되, Worker 안에서
알라딘 호출을 국중으로 바꾸면 된다(docs/PORTING_MAP.md). 앱 쪽 계약은 그대로다.

    GET {endpoint}/v1/books/search?q=...&max_results=...
    → {"items": [{"title","author","publisher","isbn13","published","cover"}...]}
"""

from __future__ import annotations

from urllib.parse import urlencode

from .base import (BookRecord, CatalogError, CatalogUnavailable, fetch_json,
                   normalize_isbn, validate_endpoint)

SOURCE_NAME = 'proxy'
ITEM_KEYS = ('items', 'books', 'docs')


def _items(payload: dict) -> list[dict]:
    for key in ITEM_KEYS:
        rows = payload.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def to_record(item: dict) -> BookRecord | None:
    title = str(item.get('title') or '').strip()
    if not title:
        return None
    return BookRecord(
        title=title,
        author=str(item.get('author') or '').strip(),
        publisher=str(item.get('publisher') or '').strip() or None,
        isbn13=normalize_isbn(str(item.get('isbn13') or item.get('isbn') or '')) or None,
        published=str(item.get('published') or '').strip() or None,
        cover_url=str(item.get('cover') or item.get('cover_url') or '').strip() or None,
        source=SOURCE_NAME,
    )


class ProxySource:
    """인증키를 들고 있지 않은 쪽. 앱이 배포돼도 새어 나갈 키가 없다."""

    name = SOURCE_NAME

    def __init__(self, endpoint: str, *, opener=None):
        self._raw_endpoint = str(endpoint or '').strip()
        self.opener = opener

    @property
    def available(self) -> bool:
        try:
            validate_endpoint(self._raw_endpoint)
        except CatalogUnavailable:
            return False
        return True

    def search(self, query: str, *, limit: int = 10) -> list[BookRecord]:
        endpoint = validate_endpoint(self._raw_endpoint)
        text = str(query or '').strip()
        if not text:
            return []
        if len(text) > 200:
            raise CatalogError('검색어가 너무 길다')

        url = (f'{endpoint}/v1/books/search?'
               + urlencode({'q': text, 'max_results': str(max(1, min(int(limit), 50)))}))
        payload = fetch_json(url, opener=self.opener)
        if payload.get('error'):
            raise CatalogError(f'서지 서버가 거절했다: {payload["error"]}')
        records = [r for r in (to_record(i) for i in _items(payload)) if r is not None]
        return records[:limit]
