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
from http.client import HTTPException
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request

from .catalog.base import TIMEOUT_SEC, USER_AGENT, is_private_host, safe_opener

MAX_COVER_BYTES = 4 * 1024 * 1024
# 펼쳤을 때 화소 상한. 4MB PNG 가 1.7GB 로 펼쳐지는 '폭탄'을 막는다 — Pillow 의
# 기본 문턱(1.78억 화소)은 그보다 훨씬 위에 있다. 표지는 커 봐야 수백만 화소다.
MAX_COVER_PIXELS = 25_000_000

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


def _declared_length(response) -> int | None:
    try:
        value = response.headers.get('Content-Length')
    except Exception:
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _extension(data: bytes) -> str:
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            if ext == '.webp' and data[8:12] != b'WEBP':
                continue
            return ext
    raise CoverError('이미지 파일이 아니다')


# 우리가 실제로 저장하는 확장자. 받다 만 파일(.part)과 구분하는 데 쓴다.
_EXTENSIONS = tuple(dict.fromkeys(ext for _magic, ext in _MAGIC))


def _existing_cover(folder: Path, stem: str) -> Path | None:
    """이미 받아 둔 표지. **glob 을 쓰지 않는다.**

    `folder.glob(f'{stem}.*')` 는 다른 스레드가 쓰는 중인
    `<stem>.png.<uuid>.part` 까지 잡는다. 그걸 표지라고 돌려주면 곧 rename 으로
    사라질 경로가 DB 에 박힌다 — 책을 연달아 등록할 때 실제로 일어났다.
    """
    for ext in _EXTENSIONS:
        candidate = folder / f'{stem}{ext}'
        if candidate.is_file():
            return candidate
    return None


def _ascii_url(address: str) -> str:
    """한글·공백이 든 주소를 urllib 이 받는 모양으로. 이미 %-인코딩된 부분은 둔다.

    안 하면 Request 가 UnicodeEncodeError/InvalidURL 을 내는데, 그건 OSError 가
    아니라 attach_cover 를 뚫고 배경 스레드를 죽인다 — 그 표지는 영영 안 받아진다.
    """
    parsed = urlparse(address)
    try:
        host = parsed.hostname.encode('idna').decode('ascii') if parsed.hostname else ''
    except UnicodeError:
        raise CoverError('표지 주소의 호스트 이름이 올바르지 않다')
    netloc = host + (f':{parsed.port}' if parsed.port else '')
    return urlunparse((
        parsed.scheme, netloc,
        quote(parsed.path, safe='/%:@!$&\'()*+,;='),
        quote(parsed.params, safe='%:@!$&\'()*+,;='),
        quote(parsed.query, safe='%=&:@!$\'()*+,;/?'),
        '',
    ))


def _pixel_count(data: bytes) -> int:
    """디코딩하지 않고 헤더만 읽어 화소 수를 잰다."""
    import io

    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
    return int(width) * int(height)


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
    existing = _existing_cover(folder, stem)
    if existing is not None:
        return existing                     # 이미 받아 뒀다

    request = Request(_ascii_url(address), headers={'User-Agent': USER_AGENT,
                                                    'Accept': 'image/*'})
    try:
        open_url = opener or safe_opener()
        with open_url(request, timeout=TIMEOUT_SEC) as response:
            data = response.read(MAX_COVER_BYTES + 1)
            expected = _declared_length(response)
    except HTTPError as exc:
        raise CoverError(f'표지 서버가 {exc.code} 를 돌려줬다') from exc
    except (URLError, OSError, TimeoutError, ValueError, HTTPException) as exc:
        raise CoverError(f'표지를 받지 못했다: {exc}') from exc

    if not data:
        raise CoverError('표지가 비어 있다')
    if len(data) > MAX_COVER_BYTES:
        raise CoverError('표지가 너무 크다')
    if expected is not None and len(data) < expected:
        # 끊긴 표지를 완성본으로 저장하면 해시 캐시 때문에 다시는 안 받는다.
        raise CoverError(f'표지가 도중에 끊겼다 ({len(data)}/{expected} 바이트)')

    extension = _extension(data)
    try:
        pixels = _pixel_count(data)
    except Exception:
        # 헤더를 못 읽는 그림은 펼쳐지지도 않는다 — 폭탄일 수 없다. 확장자 판정은
        # 이미 매직 바이트로 끝났으므로 그대로 둔다.
        pixels = 0
    if pixels > MAX_COVER_PIXELS:
        raise CoverError(f'표지 화소가 너무 많다 ({pixels:,})')

    target = folder / f'{stem}{extension}'
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




# ── 표지에서 색 뽑기 ──────────────────────────────────
# 책등을 tint 할 색이다. 책장이 표지와 이어져 보이게 하는 것이 목적이라
# 정확한 대표색보다 **너무 밝지도 어둡지도 않은 색**이 중요하다.
_TINT_MIN_L = 0.22
_TINT_MAX_L = 0.62
_TINT_MIN_SAT = 0.12


def dominant_color(path: str | Path) -> str | None:
    """표지에서 책등에 쓸 색을 뽑는다. '#RRGGBB' 또는 None.

    Pillow 가 없거나 이미지를 못 열면 None — 그때는 단색 책등으로 간다.
    """
    try:
        import colorsys

        from PIL import Image
    except ImportError:
        return None

    try:
        with Image.open(path) as source:
            width, height = source.size
            if width * height > MAX_COVER_PIXELS:
                # 사용자가 art_overrides 나 백업으로 들여온 표지일 수도 있다.
                # 펼치기 전에 크기부터 본다 — convert 가 메모리를 먹는 순간이다.
                return None
            image = source.convert('RGB')
            # 가장자리는 흰 여백인 경우가 많다. 가운데만 본다.
            w, h = image.size
            image = image.crop((w // 8, h // 8, w - w // 8, h - h // 8))
            image = image.resize((48, 48))
            reduced = image.quantize(colors=8, method=Image.Quantize.FASTOCTREE)
            palette = reduced.getpalette() or []
            counts = sorted(reduced.getcolors() or [], reverse=True)
    except Exception:
        return None

    best = None
    for count, index in counts:
        rgb = palette[index * 3:index * 3 + 3]
        if len(rgb) != 3:
            continue
        r, g, b = (v / 255 for v in rgb)
        hue, light, sat = colorsys.rgb_to_hls(r, g, b)
        if sat < _TINT_MIN_SAT:
            continue                     # 무채색은 책등에서 밋밋하다
        if not (_TINT_MIN_L <= light <= _TINT_MAX_L):
            continue                     # 너무 밝거나 어두우면 제목이 안 읽힌다
        best = (r, g, b)
        break

    if best is None:
        # 조건에 맞는 게 없으면 가장 많은 색을 밝기만 맞춰 쓴다.
        if not counts:
            return None
        rgb = palette[counts[0][1] * 3:counts[0][1] * 3 + 3]
        if len(rgb) != 3:
            return None
        import colorsys as _c
        r, g, b = (v / 255 for v in rgb)
        hue, light, sat = _c.rgb_to_hls(r, g, b)
        light = min(_TINT_MAX_L, max(_TINT_MIN_L, light))
        best = _c.hls_to_rgb(hue, light, max(sat, _TINT_MIN_SAT))

    return '#%02X%02X%02X' % tuple(round(v * 255) for v in best)


def attach_cover(journal, book_id: str, url: str, data_dir: str | Path,
                 *, opener=None) -> Path | None:
    """표지를 받아 책에 붙이고, 책등 색도 함께 정한다.

    실패하면 조용히 None — 책은 그대로 남는다.
    """
    try:
        path = download_cover(url, data_dir, opener=opener)
    except (CoverError, OSError):
        # 배경 스레드에서 돈다. 여기서 새면 잡아줄 사람이 없다.
        return None
    fields: dict = {'cover_path': str(path)}
    tint = dominant_color(path)
    if tint:
        fields['spine_tint'] = tint
    try:
        journal.update_book(book_id, **fields)
    except KeyError:
        return None
    return path
