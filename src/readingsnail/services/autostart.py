"""로그인할 때 자동으로 켜기. **기본은 꺼짐**(SPEC 7항).

사용자가 켜기 전에는 아무것도 하지 않는다. 바탕화면 위젯이 묻지도 않고
자동 시작에 등록되면 그 순간 성가신 프로그램이 된다.

HKCU 의 Run 키만 쓴다. 관리자 권한이 필요 없고, 지울 때도 그 값 하나만 지운다.
"""

from __future__ import annotations

import os
import sys

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'ReadingSnail'
DEV_OVERRIDE = 'READINGSNAIL_ALLOW_DEV_AUTOSTART'


def supported(platform: str | None = None) -> bool:
    return str(sys.platform if platform is None else platform).startswith('win')


def can_enable(*, platform: str | None = None, frozen: bool | None = None,
               environ: dict[str, str] | None = None) -> bool:
    """포장된 실행 파일에서만 켤 수 있다.

    개발 중에 켜면 python.exe 가 등록돼 엉뚱한 것이 뜬다.
    시험이 필요하면 환경 변수로 연다.
    """
    if not supported(platform):
        return False
    env = dict(os.environ if environ is None else environ)
    is_frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    return bool(is_frozen) or env.get(DEV_OVERRIDE) == '1'


def startup_command(executable: str | None = None) -> str:
    exe = str(executable or sys.executable).strip().strip('"')
    if not exe:
        raise ValueError('실행 파일 경로가 필요하다')
    return f'"{exe}"'


def is_enabled() -> bool:
    if not supported():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_QUERY_VALUE) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value).strip() == startup_command()
    except (FileNotFoundError, OSError):
        return False


def set_enabled(enabled: bool) -> None:
    if not supported():
        raise RuntimeError('자동 시작은 Windows 에서만 됩니다')
    if enabled and not can_enable():
        raise RuntimeError('포장된 실행 파일에서만 켤 수 있습니다')

    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                        winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
