# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir 빌드.

    pyinstaller ReadingSnail.spec

왜 onedir 인가
    onefile 은 켤 때마다 임시 폴더에 통째로 풀어놓는다. 번들 모델이 60~80MB 라
    시작이 눈에 띄게 느려지고, 백신이 매번 훑는다.

**사용자 데이터는 여기 들어가지 않는다.**
기록은 %LOCALAPPDATA%\\ReadingSnail 에 있고, 설치·업데이트·삭제가 그것을
건드리지 않는다(CLAUDE.md 제약).
"""

from pathlib import Path

APP_NAME = 'ReadingSnail'
ROOT = Path(SPECPATH)

# 번들에 담을 것. 없으면 조용히 건너뛴다 — 원화도 모델도 없이 앱은 돈다.
_CANDIDATES = (
    ('resources/sprites', 'resources/sprites'),
    ('resources/props', 'resources/props'),
    ('resources/shelf', 'resources/shelf'),
    ('resources/fonts', 'resources/fonts'),
    ('resources/models', 'resources/models'),
)
datas = [(str(ROOT / src), dst) for src, dst in _CANDIDATES
         if (ROOT / src).is_dir()]
# 명언 시드는 패키지 안에 있다. 빠지면 첫 실행에 달팽이가 말을 못 한다.
datas.append((str(ROOT / 'src/readingsnail/storage/seeds'),
              'readingsnail/storage/seeds'))

a = Analysis(
    [str(ROOT / 'src/readingsnail/__main__.py')],
    pathex=[str(ROOT / 'src')],
    binaries=[],
    datas=datas,
    hiddenimports=['PIL._tkinter_finder'],
    hookspath=[],
    runtime_hooks=[],
    # 쓰지 않는 무거운 것들을 뺀다. 설치본 크기가 곧 설치 의향이다.
    excludes=['matplotlib', 'scipy', 'pandas', 'pytest', 'setuptools',
              'IPython', 'notebook', 'tkinter.test', 'test'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=False,          # UPX 는 백신 오탐을 부른다
    console=False,      # 바탕화면 위젯이다. 콘솔 창이 뜨면 안 된다
    icon=str(ROOT / 'resources/icon.ico') if (ROOT / 'resources/icon.ico').is_file() else None,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name=APP_NAME,
)
