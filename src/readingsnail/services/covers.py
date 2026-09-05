"""표지 이미지를 내려받아 로컬에 둔다.

제약 (CLAUDE.md / SPEC 2항)
    표지는 내려받아 로컬 저장한다. **외부 URL 을 DB 에 박아두지 않는다.**
    서비스가 문을 닫으면 박아둔 URL 은 전부 깨진 이미지가 된다. 전작이
    books.cover_url 에 알라딘 URL 을 넣어둔 탓에 이전 때 되살릴 수 없었다.

주의
    · 내려받기는 네트워크다. **UI 스레드에서 부르지 말 것.**
    · 이미지가 아닌 응답, 지나치게 큰 파일, 엉뚱한 주소는 받지 않는다.
    · 실패해도 책 등록은 계속된다. 표지는 있으면 좋은 것이지 필수가 아니다.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request

from .catalog.base import TIMEOUT_SEC, USER_AGENT, is_private_host, safe_opener

MAX_COVER_BYTES = 4 * 1024 * 1024

# 확장자는 실제 내용으로 정한다. Content-Type 을 그대로 믿지 않는다.
_MAGIC = (
    (b'\x89PNG\r\n\x1a\n', '.png'),
    (b'\xff\xd8\xff', '.jpg'),
    (b'GIF87a', '.gif'),
    (b'GIF89a', '.gif'),
    (b'RIFF', '.webp'),          # RIFF....WEBP
)


class CoverError(RuntimeError):
    """표지를 가져오지 못했다. 책 등록은 계속된다."""


def _extension(data: bytes) -> str:
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            if ext == '.webp' and data[8:12] != b'WEBP':
                continue
            return ext
    raise CoverError('이미지 파일이 아니다')


def covers_dir(data_dir: str | Path) -> Path:
    path = Path(data_dir) / 'covers'
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_cover(url: str, data_dir: str | Path, *, opener=None) -> Path:
    """표지를 받아 covers/ 에 저장하고 그 경로를 돌려준다.

    파일 이름은 URL 해시다. 같은 표지를 두 번 받지 않고, 파일 이름에
    책 제목이 드러나지 않는다.
    """
    address = str(url or '').strip()
    parsed = urlparse(address)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise CoverError('표지 주소가 올바르지 않다')
    if parsed.username or parsed.password:
        raise CoverError('주소에 자격증명이 들어 있다')
    # 표지 주소는 외부 서비스 응답에서 온다. 내부망을 대신 두드리게 두지 않는다.
    if is_private_host(parsed.hostname or ''):
        raise CoverError('표지 주소가 내부망을 가리킨다')

    folder = covers_dir(data_dir)
    stem = hashlib.sha256(address.encode('utf-8')).hexdigest()[:24]
    for existing in folder.glob(f'{stem}.*'):
        return existing                     # 이미 받아 뒀다

    request = Request(address, headers={'User-Agent': USER_AGENT,
                                        'Accept': 'image/*'})
    try:
        open_url = opener or safe_opener()
        with open_url(request, timeout=TIMEOUT_SEC) as response:
            data = response.read(MAX_COVER_BYTES + 1)
    except HTTPError as exc:
        raise CoverError(f'표지 서버가 {exc.code} 를 돌려줬다') from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise CoverError(f'표지를 받지 못했다: {exc}') from exc

    if not data:
        raise CoverError('표지가 비어 있다')
    if len(data) > MAX_COVER_BYTES:
        raise CoverError('표지가 너무 크다')

    target = folder / f'{stem}{_extension(data)}'
    # 받다 만 파일이 남지 않게 임시 이름으로 쓰고 옮긴다.
    # 임시 이름에 고유값을 넣는다. 같은 표지를 여러 스레드가 동시에 받으면
    # (책을 연달아 등록할 때 실제로 일어난다) 같은 .part 를 서로 지워
    # FileNotFoundError 가 난다.
    tmp = target.with_name(f'{target.name}.{uuid.uuid4().hex[:8]}.part')
    try:
        tmp.write_bytes(data)
        tmp.replace(target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        if target.is_file():
            return target           # 다른 스레드가 먼저 끝냈다
        raise CoverError(f'표지를 저장하지 못했다: {exc}') from exc
    return target


def attach_cover(journal, book_id: str, url: str, data_dir: str | Path,
                 *, opener=None) -> Path | None:
    """표지를 받아 책에 붙인다. 실패하면 조용히 None — 책은 그대로 남는다."""
    try:
        path = download_cover(url, data_dir, opener=opener)
    except (CoverError, OSError):
        # 배경 스레드에서 돈다. 여기서 새면 잡아줄 사람이 없다.
        return None
    try:
        journal.update_book(book_id, cover_path=str(path))
    except KeyError:
        return None
    return path
