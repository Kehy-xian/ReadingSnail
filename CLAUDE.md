# 책 읽는 달팽이 (ReadingSnail)

## 이 프로젝트가 무엇인가

바탕화면을 돌아다니는 달팽이 위젯. **독서 기록을 쌓고, 그 기록을 다시 꺼내 보여주어
독서를 유도하는 것**이 유일한 목적이다.

전작 `BookEater`(책먹는 몬스터)에서 진화·육성 시스템을 걷어내고 기록에 집중한 재구성판이다.
BookEater 저장소는 개발 중단 상태이며 **절대 수정하지 않는다.** 참조만 한다.

## 판단 기준

기능을 추가할지 고민될 때 이 질문 하나로 결정한다.

> 이 기능이 **기록을 늘리는가**, 아니면 **캐릭터를 키우는가**?

후자면 넣지 않는다. 전작이 무거워진 원인이 그것이다.

## 절대 다시 넣지 않을 것

- 진화, 성장 단계, 스탯, 경험치, 영양, 성장 노선, 도감, 마일스톤
- 돌보기(간식·씻기·놀기), 미니게임
- 기록 텍스트의 성향 분류(사유/탐구/감정/감각 × 상상/모험/자연/사회/어둠)
- 소품·장식의 "해금" 개념 — 소품은 순수 사용자 선택이다

## 지켜야 할 제약

- 기록은 로컬 SQLite에만 저장한다. 기록 본문이 네트워크로 나가지 않는다.
- 기록은 덮어쓰지 않는다. 한 책에 시간순 기록이 무한히 붙는다.
- 저장이 분석보다 먼저다. 임베딩 계산에 실패해도 기록은 이미 저장돼 있어야 한다.
- 설치·업데이트·삭제가 사용자 데이터를 건드리지 않는다.
- 임베딩은 **저장 시점에 한 번만** 계산한다. 상시 추론 금지.

## 스택

Python 3.12 / tkinter (+ ttkbootstrap 또는 CustomTkinter) / Pillow / pystray /
onnxruntime (임베딩 인코딩 전용) / PyInstaller onedir / Inno Setup

**PySide6로 갈아타지 않는다.** 색상 키 투명도의 한계는 선명한 외곽선 그림체로 우회한다.

## 현재 상태

뼈대 단계다. 실행 진입점(`__main__.py`)과 UI는 아직 없다.
`docs/SPEC.md`가 확정 명세, `docs/PORTING_MAP.md`가 전작에서 가져올 것과
버릴 것의 목록이다. 작업 전에 둘 다 읽을 것.

**1·2단계 완료.** `python -m readingsnail` 로 실제로 뜬다. 3단계(임베딩·발화)가 다음이다.

동작이 검증된 것 — `python -m unittest discover -s tests` (107건 통과)
GUI 테스트는 tkinter·디스플레이가 없으면 자동으로 건너뛴다.

| 있는 것 | 파일 |
|---|---|
| SQLite 스키마 (trigram FTS5 포함) | `storage/schema.sql` |
| 연결·스키마 적용 (`Database`) | `storage/db.py` |
| 책·기록 (`Journal`) | `storage/journal.py` |
| 임시저장 / 설정 | `storage/drafts.py`, `storage/settings.py` |
| 전작 기록 이전 | `storage/migrate.py` |
| 한글 검색 라우터 | `storage/search.py` |
| 명언 시드 24건 + 멱등 주입기 | `storage/seeds/quotes_ko.json`, `storage/seed.py` |
| 데이터 폴더 경로 (전작 포함) | `paths.py` |
| 4갈래 발화 가중치 | `services/dialogue.py` |
| 8방향 이동 (순수 로직) | `pet/behavior.py` |
| 달팽이 창 (단일 클래스) | `pet/window.py` |
| 기록·서재 창 (임시) | `pet/panels.py` |
| 실행 진입점 | `__main__.py` |
| 폰트·색 상수 | `theme.py` |

비어 있는 것 — `nlp/`(인코더), 의미 검색·발화 서비스, 스프라이트 파이프라인,
서지 API, 책장 뷰, 빌드 스펙. `docs/PORTING_MAP.md`대로 전작에서 가져와 채운다.

`pet/panels.py`는 **일부러 꾸미지 않았다.** 기능(1~4) → 디자인(5~6) 순서이므로
지금 다듬으면 6단계에서 갈아엎을 화면을 다듬게 된다.

## 저장소 계층 쓰는 법

```python
from readingsnail.paths import default_db_path
from readingsnail.storage.db import open_database
from readingsnail.storage.journal import Journal

db = open_database(default_db_path())   # 스키마 적용 + 명언 시드까지
journal = Journal(db)
book = journal.add_book('월든', author='헨리 데이비드 소로')
journal.add_entry('숲으로 간 이유', book_id=book.book_id, kind='quote', page='p.31')
```

전작처럼 저장소마다 `_connect()`를 두지 않는다. `Database` 하나가 연결과 스키마를
맡고 `Journal`·`Drafts`·`Settings`가 그것을 받아 쓴다. 연결은 메서드마다 짧게 열고
닫는데, 이건 전작의 의도적 설계를 그대로 가져온 것이다 — UI 스레드와 임베딩
백그라운드 작업이 같은 DB를 보므로 연결을 물고 있으면 안 된다.

## 창을 늘릴 때

**PetWindow 를 상속하지 말 것.** 전작은 pet_window.py 위에 v2~v11 이 한 겹씩
올라탄 11단계 체인이었다(3,469줄). 메서드 하나를 고치려면 어느 겹에서 덮였는지
열한 파일을 거슬러야 했다. 기능이 늘면 상속이 아니라 **패널을 별도 모듈로** 뗀다.
`pet/panels.py`가 그 본보기다.

## 함정 두 가지

1. **검색은 `storage/search.py`를 거친다.** `entries_fts MATCH`를 직접 부르면
   trigram 특성상 2자 이하 질의('독서', '기록')가 전부 0건이 된다. 조용히 실패한다.
0. **기록 본문을 고치면 임베딩을 반드시 무효화한다.** `Journal.revise_entry()`가
   이미 그렇게 한다. 직접 UPDATE 하면 의미 검색이 옛 문장 기준으로 엉뚱한 기록을
   이어붙인다. FTS 인덱스는 트리거가 알아서 따라오지만 벡터는 아니다.
2. **`-transparentcolor`는 Windows 전용이다.** X11·macOS 에서는 `TclError`가 난다.
   `PetWindow._enable_transparency()`가 알파로 물러나되, 그때는 창이 네모로 보인다.
   개발을 Windows 밖에서 하면 이 차이를 늘 염두에 둘 것.
3. **`enable_dpi_awareness()`는 `tk.Tk()`보다 먼저 부른다.** 안 그러면 고DPI
   화면에서 좌표와 화면 크기가 배율만큼 어긋난다.
4. **`theme.font()`는 tkinter 초기화 이후에만 부른다.** `tkfont.families()`가
   Tk 인스턴스를 요구한다. 반환된 Font 객체는 모듈 전역에 캐시되므로 Tk root를
   새로 만들면 캐시(`theme._resolved`)도 비워야 한다.

## 단계를 넘어가기 전에

**다음 단계로 넘어가기 전에 항상 점검한다.** 테스트가 통과했다는 것은 '내가 상상한
상황에서 안 터진다'는 뜻이지 '안 터진다'는 뜻이 아니다. 매 단계 끝에서

1. 방금 쓴 코드를 적대적으로 읽고, 터질 만한 곳을 **재현 스크립트로 실제로 찔러본다.**
   추론으로 '괜찮을 것 같다'까지만 가고 멈추지 않는다.
2. 오류가 나지 않더라도 **일어날 수 있는 상황**을 따로 세어본다.
   구버전 데이터, 화면 해상도 변경, 창을 다시 만드는 경로, 중간에 닫기,
   동시 접근, 빈 값·아주 긴 값, 다른 플랫폼.
3. 나온 것은 고치고 **회귀 테스트로 못 박는다.** 다음에 같은 자리에서 또 깨지지
   않게 한다.
4. 고칠 것이 없으면 그렇게 보고하고 넘어간다.

지금까지 이 방식으로 잡은 것 — 중첩 `write()` 잠금, 구버전 전작 DB 이전 중단,
붙잡고 있는데도 계속 떨어지던 낙하, Tk root 를 다시 만들면 죽던 폰트 캐시,
패널에 쓰던 글이 종료 시 사라지던 문제. 전부 테스트는 통과하던 상태였다.

## 작업 순서

기능(1~4) → 디자인(5~6) 순서를 지킨다. 디자인부터 손대면 어차피 사라질 화면을 다듬게 된다.
예외는 6-a(폰트·색 정비)로, 이건 언제 해도 되고 빠를수록 좋다.
