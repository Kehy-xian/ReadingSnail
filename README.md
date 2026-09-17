# 책 읽는 달팽이

바탕화면을 천천히 돌아다니는 달팽이가 내가 기록한 문장과 감상을 가끔 꺼내 보여줍니다.
다 읽은 책은 달팽이가 꿀꺽 삼켜 책장에 꽂힙니다.

Windows 데스크톱 위젯. 모든 기록은 내 PC에만 저장됩니다.

- 기능 명세: [docs/SPEC.md](docs/SPEC.md)
- 전작에서 무엇을 가져오는가: [docs/PORTING_MAP.md](docs/PORTING_MAP.md)
- 달팽이 그림 규격: [docs/SPRITE_GUIDE_KO.md](docs/SPRITE_GUIDE_KO.md)

## 상태

기능은 1~7단계까지 갖춰져 `python -m readingsnail` 로 돌아갑니다. 원화(그림)는 아직 없고
자리표시 그림으로 동작합니다. Windows 설치본은 `docs/BUILD_KO.md` 대로 만들 수 있으나
실기 검증 전입니다.

## 테스트앱 받기

Python 을 설치하지 않고 바로 써 보려면:

1. 이 저장소의 **Actions** 탭 → **테스트앱 (Windows)** → 가장 최근 실행
2. 아래 **Artifacts** 의 `책읽는달팽이-테스트앱-…` zip 을 내려받기
3. 압축을 풀고 `ReadingSnail.exe` 더블클릭 (설치 과정 없음)

새로 만들고 싶으면 그 화면의 **Run workflow** 단추를 누르면 됩니다.
기록은 앱 폴더가 아니라 `%LOCALAPPDATA%\ReadingSnail` 에 쌓이므로,
앱 폴더를 지우거나 새 zip 으로 바꿔도 기록은 그대로 남습니다.

자세한 안내는 zip 안의 `읽어보세요.txt`(원본 [docs/readme_for_testers_ko.txt](docs/readme_for_testers_ko.txt)).

소스에서 직접 돌리려면 Python 3.12 에서:

```
pip install -r requirements.txt
python tools/render_placeholder_pack.py     # 원화가 없어 자리표시 그림을 만든다
python -m readingsnail
```

## 전작

[BookEater](https://github.com/Kehy-xian/BookEater) (책먹는 몬스터) — 개발 중단.
이 프로젝트는 그 구조를 참조하되 별도 저장소로 진행합니다.
