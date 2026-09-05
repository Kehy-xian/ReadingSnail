"""서지 검색. 출처가 바뀌어도 앱의 나머지는 모른다.

고르는 순서
    1. 프록시 주소가 설정돼 있으면 프록시 (키가 앱에 없다)
    2. 사용자가 넣은 국중 cert_key 가 있으면 직접 호출
    3. 둘 다 없으면 None — 수동 입력으로 책을 등록한다

수동 입력은 폴백이 아니라 **언제나 되는 길**이다. 서지 서비스가 또 문을 닫아도
책은 등록할 수 있어야 한다.
"""

from __future__ import annotations

from .base import (BookRecord, BookSource, CatalogError, CatalogUnavailable,
                   looks_like_isbn, normalize_isbn, validate_endpoint)
from .nlk import NationalLibrarySource
from .proxy import ProxySource

SETTING_CERT_KEY = 'catalog.nl_cert_key'
SETTING_PROXY = 'catalog.proxy_endpoint'


def build_source(settings, *, opener=None) -> BookSource | None:
    """설정을 보고 쓸 수 있는 출처 하나를 고른다. 없으면 None."""
    proxy = ProxySource(settings.get(SETTING_PROXY, '') or '', opener=opener)
    if proxy.available:
        return proxy
    direct = NationalLibrarySource(settings.get(SETTING_CERT_KEY, '') or '',
                                   opener=opener)
    if direct.available:
        return direct
    return None


def search_books(source: BookSource | None, query: str, *,
                 limit: int = 10) -> list[BookRecord]:
    """검색한다. 출처가 없거나 실패하면 빈 목록 — 수동 입력이 열려 있다.

    예외를 밖으로 던지지 않는다. 서지 조회 실패로 책 등록 화면이 멈추면 안 된다.
    """
    if source is None:
        return []
    try:
        return source.search(query, limit=limit)
    except CatalogError:
        return []


__all__ = [
    'BookRecord', 'BookSource', 'CatalogError', 'CatalogUnavailable',
    'NationalLibrarySource', 'ProxySource', 'build_source', 'search_books',
    'looks_like_isbn', 'normalize_isbn', 'validate_endpoint',
    'SETTING_CERT_KEY', 'SETTING_PROXY',
]
