"""서지 검색 어댑터의 공통 뼈대.

왜 어댑터인가
    올해만 두 곳이 문을 닫았다(알라딘 OpenAPI 2026-10-30 종료 예정, 카카오는
    DB 영구 저장이 운영정책상 제한). 다음에 또 닫힌다는 전제로 짓는다.
    앱의 나머지는 BookSource 인터페이스만 알고, 어디서 오는지는 모른다.

절대 나가지 않는 것
    **기록 본문은 이 계층에 들어오지도 않는다.** 여기로 넘어가는 것은 사용자가
    직접 친 검색어(제목·저자·ISBN)뿐이다. Journal 을 받는 함수가 여기 없는 것이
    그 보장이다(tests/test_catalog.py 가 확인한다).
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

USER_AGENT = 'ReadingSnail/0.0.1 (+local desktop app)'
TIMEOUT_SEC = 8.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

_ISBN_CHARS = re.compile(r'[^0-9Xx]')

# 국중 API 는 인증키를 질의 문자열로 받는다(GET 파라미터). 그래서 URL 이
# 예외 메시지나 로그에 섞이면 키가 그대로 드러난다. 어디로 흘려보내든
# 반드시 redact() 를 거칠 것. 키를 아예 앱에 두지 않는 길이 proxy.py 다.
_SECRET_PARAMS = ('cert_key', 'apikey', 'api_key', 'key', 'ttbkey', 'token')
_SECRET_RE = re.compile(
    r'(?i)\b(' + '|'.join(_SECRET_PARAMS) + r')=[^&\s]+')


def redact(text: object) -> str:
    """인증키가 섞였을 수 있는 문자열을 가린다."""
    return _SECRET_RE.sub(lambda m: f'{m.group(1)}=***', str(text))


class CatalogError(RuntimeError):
    """서지 조회가 실패했다. 수동 입력으로 물러나면 된다."""


class CatalogUnavailable(CatalogError):
    """설정이 없거나 서비스를 쓸 수 없다."""


@dataclass(frozen=True)
class BookRecord:
    """어느 출처에서 왔든 앱이 보는 모양은 하나다."""

    title: str
    author: str = ''
    publisher: str | None = None
    isbn13: str | None = None
    published: str | None = None      # 'YYYY-MM-DD' 또는 'YYYY'
    cover_url: str | None = None      # **DB 에 넣지 않는다.** 내려받아 로컬 저장한다.
    source: str = 'manual'

    @property
    def display_name(self) -> str:
        return f'{self.title} — {self.author}' if self.author else self.title


class BookSource(Protocol):
    """서지 출처 하나. 이것만 구현하면 갈아끼울 수 있다."""

    name: str

    @property
    def available(self) -> bool:
        ...

    def search(self, query: str, *, limit: int = 10) -> list[BookRecord]:
        ...


# ── 공통 도구 ────────────────────────────────────────
def normalize_isbn(value: str) -> str:
    """붙임표·공백을 지운다. ISBN 이 아니면 빈 문자열."""
    compact = _ISBN_CHARS.sub('', str(value or ''))
    return compact if len(compact) in (10, 13) else ''


def looks_like_isbn(query: str) -> bool:
    return bool(normalize_isbn(query))


def validate_endpoint(url: str) -> str:
    """HTTPS 만 허용한다. 자격증명이 박힌 URL 도 거부한다.

    전작 catalog.py 의 검사를 그대로 가져왔다. 설정 파일 한 줄로 요청이
    엉뚱한 곳으로 새는 것을 막는 장치다.
    """
    value = str(url or '').strip()
    if not value:
        raise CatalogUnavailable('서지 서버 주소가 설정되지 않았다')
    parsed = urlparse(value)
    if parsed.username or parsed.password:
        raise CatalogUnavailable('주소에 자격증명을 넣지 않는다')
    host = (parsed.hostname or '').lower()
    local = host in {'localhost', '127.0.0.1', '::1'}
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and local):
        raise CatalogUnavailable('서지 서버는 HTTPS 여야 한다')
    if not parsed.netloc:
        raise CatalogUnavailable('서지 서버 주소가 올바르지 않다')
    return value.rstrip('/')


class _NoDowngradeRedirect(HTTPRedirectHandler):
    """https → http 강등을 막는다.

    urllib 은 기본적으로 강등을 따라간다. 국중 API 는 인증키를 질의 문자열로
    보내므로, 강등된 리다이렉트 한 번이면 키가 평문으로 나간다.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.full_url.lower().startswith('https://') and \
                not newurl.lower().startswith('https://'):
            raise CatalogError('https 에서 http 로의 리다이렉트는 따르지 않는다')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_opener():
    """강등 리다이렉트를 막는 opener. 기본 urlopen 대신 쓴다."""
    return build_opener(_NoDowngradeRedirect()).open


def is_private_host(host: str) -> bool:
    """내부망·루프백·링크로컬을 가리키는가.

    표지 주소는 외부 서비스 응답에서 온다. 그대로 받아 열면 앱이 사용자
    컴퓨터의 내부 주소를 대신 두드려 주는 통로가 된다(클라우드 메타데이터
    169.254.169.254 가 대표적이다).
    """
    name = str(host or '').strip().strip('[]').lower()
    if not name:
        return True
    if name in {'localhost', 'localhost.localdomain'} or name.endswith('.localhost'):
        return True

    candidates: list[str] = []
    try:
        ipaddress.ip_address(name)
        candidates.append(name)
    except ValueError:
        try:
            infos = socket.getaddrinfo(name, None)
        except (socket.gaierror, UnicodeError, OSError):
            # 이름을 풀지 못했다. 여기서 막으면 정상 주소까지 막힌다.
            return False
        candidates = [info[4][0] for info in infos]

    for raw in candidates:
        try:
            address = ipaddress.ip_address(raw.split('%')[0])
        except ValueError:
            return True
        if (address.is_private or address.is_loopback or address.is_link_local
                or address.is_reserved or address.is_multicast
                or address.is_unspecified):
            return True
    return False


def fetch_json(url: str, *, opener=None) -> dict:
    """JSON 을 받아온다. 응답 크기를 자른다 — 서버가 무엇을 보낼지 모른다."""
    request = Request(url, headers={'User-Agent': USER_AGENT,
                                    'Accept': 'application/json'})
    try:
        open_url = opener or safe_opener()
        with open_url(request, timeout=TIMEOUT_SEC) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise CatalogError(f'서지 서버가 {exc.code} 를 돌려줬다') from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise CatalogError(f'서지 서버에 닿지 못했다: {redact(exc)}') from exc

    if len(raw) > MAX_RESPONSE_BYTES:
        raise CatalogError('응답이 너무 크다')
    try:
        data = json.loads(raw.decode('utf-8', errors='replace'))
    except json.JSONDecodeError as exc:
        raise CatalogError('서지 서버 응답이 JSON 이 아니다') from exc
    if not isinstance(data, dict):
        raise CatalogError('서지 서버 응답 모양이 예상과 다르다')
    return data
