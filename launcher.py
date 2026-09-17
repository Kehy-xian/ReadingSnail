"""PyInstaller 진입점.

패키지의 ``__main__.py`` 를 진입 스크립트로 주면 안 된다. PyInstaller 는 그 파일을
최상위 스크립트로 돌리므로 ``from .nlp ...`` 같은 상대 import 가
``ImportError: attempted relative import with no known parent package`` 로 죽는다.
개발 중 ``python -m readingsnail`` 은 패키지로 돌아서 이 문제가 안 보인다.

여기서 패키지를 절대 경로로 import 해 넘긴다. 로직은 전부 ``readingsnail.__main__`` 에 있다.
"""

from readingsnail.__main__ import main

raise SystemExit(main())
