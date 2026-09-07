"""데이터·리소스 위치.

기록은 설치 폴더가 아니라 사용자 데이터 폴더에 둔다. 그래야 설치·업데이트·삭제가
기록을 건드리지 않는다(CLAUDE.md 제약).

전작 경로도 여기서 같이 계산한다. 마이그레이션이 옛 DB 를 찾아야 하기 때문이다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = 'ReadingSnail'
DB_FILENAME = 'readingsnail.sqlite3'

# 전작. 읽기 전용으로만 연다.
LEGACY_APP_DIR_NAME = 'BookEater'
LEGACY_DB_FILENAME = 'bookeater.sqlite3'


def _base_dir(
    app_dir_name: str,
    posix_name: str,
    *,
    platform: str | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    platform = platform or sys.platform
    env = dict(os.environ if environ is None else environ)
    home = Path.home() if home is None else Path(home)

    if platform.startswith('win'):
        base = env.get('LOCALAPPDATA') or env.get('APPDATA')
        return (Path(base).expanduser() if base else home / 'AppData' / 'Local') / app_dir_name
    if platform == 'darwin':
        return home / 'Library' / 'Application Support' / app_dir_name
    xdg = env.get('XDG_DATA_HOME')
    return (Path(xdg).expanduser() if xdg else home / '.local' / 'share') / posix_name


def default_data_dir(**kw) -> Path:
    """기록이 사는 곳. READINGSNAIL_DATA_DIR 로 덮어쓸 수 있다(테스트·이식용)."""
    env = dict(os.environ if kw.get('environ') is None else kw['environ'])
    override = env.get('READINGSNAIL_DATA_DIR')
    if override:
        return Path(override).expanduser()
    return _base_dir(APP_DIR_NAME, 'readingsnail', **kw)


def default_db_path(**kw) -> Path:
    return default_data_dir(**kw) / DB_FILENAME


def legacy_data_dir(**kw) -> Path:
    """전작 BookEater 의 데이터 폴더."""
    env = dict(os.environ if kw.get('environ') is None else kw['environ'])
    override = env.get('BOOKEATER_DATA_DIR')
    if override:
        return Path(override).expanduser()
    return _base_dir(LEGACY_APP_DIR_NAME, 'bookeater', **kw)


def legacy_db_path(**kw) -> Path:
    return legacy_data_dir(**kw) / LEGACY_DB_FILENAME


def resource_root(*, environ: dict[str, str] | None = None) -> Path:
    """번들 리소스(스프라이트·모델·폰트) 뿌리.

    PyInstaller onedir 로 묶으면 실행 파일 옆에 놓인다. 개발 중에는 저장소 뿌리다.
    """
    env = dict(os.environ if environ is None else environ)
    override = env.get('READINGSNAIL_RESOURCE_ROOT')
    if override:
        return Path(override).expanduser()
    bundled = getattr(sys, '_MEIPASS', None)
    if bundled:
        return Path(bundled)
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def readonly_uri(path: str | Path) -> str:
    """읽기 전용으로 열 SQLite URI. **문자열을 직접 이어 붙이지 않는다.**

    `f'file:{path}?mode=ro'` 는 경로에 `?` 나 `#` 가 있으면 거기서 잘린다.
    그때 SQLite 는 오류를 내지 않고 **엉뚱한 빈 DB 를 새로 만든다** — 백업이
    멀쩡한 얼굴로 비어 있게 된다는 뜻이다(`백업 #2.sqlite3` 에서 실제로 걸렸다).
    바탕화면에서 고른 파일이 그런 이름일 수 있다.

    `Path.as_uri()` 가 그런 글자를 퍼센트로 감싸고 Windows 드라이브 문자도
    `file:///C:/...` 로 제대로 적는다.
    """
    return Path(path).absolute().as_uri() + '?mode=ro'
