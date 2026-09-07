"""달팽이를 두 마리 띄우지 않는다.

자동 시작과 바로가기가 겹치면 같은 기록 파일을 두 프로세스가 본다.
SQLite 는 그걸 견디지만(WAL), 달팽이가 두 마리 돌아다니고 임베딩이 중복 계산된다.

Windows 는 이름 있는 뮤텍스로 막는다. 그 밖의 플랫폼(개발 중)은 막지 않는다.
전작 single_instance.py 를 그대로 가져왔다 — 이름과 환경 변수만 바꿨다.
"""

from __future__ import annotations

import ctypes
import getpass
import hashlib
import os
import sys
from dataclasses import dataclass
from typing import Any

ERROR_ALREADY_EXISTS = 183
MUTEX_PREFIX = 'Local\\ReadingSnail-'


def instance_name(*, user_hint: str | None = None,
                  data_dir_hint: str | None = None) -> str:
    """로그온 세션(Local\\)과 데이터 폴더 단위로 묶는다.

    해시를 쓰는 이유는 사용자 이름과 경로가 커널 객체 이름으로 드러나지 않게
    하기 위해서다. 데이터 폴더가 다르면 다른 프로필이므로 함께 떠도 된다.
    """
    user = str(user_hint if user_hint is not None else getpass.getuser())
    data = str(data_dir_hint if data_dir_hint is not None
               else os.environ.get('READINGSNAIL_DATA_DIR', 'default'))
    digest = hashlib.sha256(f'{user}\0{data}'.encode('utf-8', 'replace')).hexdigest()[:24]
    return MUTEX_PREFIX + digest


@dataclass
class Guard:
    acquired: bool
    handle: int | None = None
    kernel32: Any | None = None

    def close(self) -> None:
        if self.handle and self.kernel32 is not None:
            try:
                self.kernel32.CloseHandle(self.handle)
            finally:
                self.handle = None

    def __enter__(self) -> 'Guard':
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def acquire(*, name: str | None = None, platform: str | None = None) -> Guard:
    """이미 떠 있으면 acquired=False. 프로그램이 조용히 물러나면 된다."""
    platform = sys.platform if platform is None else platform
    if not str(platform).startswith('win'):
        return Guard(True)

    mutex_name = name or instance_name()
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    except (AttributeError, OSError):
        return Guard(True)          # 못 막으면 막지 않는다. 앱은 떠야 한다.

    create = kernel32.CreateMutexW
    create.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    create.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool

    ctypes.set_last_error(0)
    handle = create(None, False, mutex_name)
    if not handle:
        return Guard(True)          # 만들지 못했다. 막지 않는다.
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return Guard(False)
    return Guard(True, int(handle), kernel32)
