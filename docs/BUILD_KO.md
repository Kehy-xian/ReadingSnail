# 설치본 만들기

## 준비

```
pip install -r requirements-build.txt
```

번들에 담을 것을 먼저 채운다. **없어도 빌드는 되고 앱도 돈다** — 그 기능만 쉰다.

| 넣을 것 | 위치 | 없으면 |
|---|---|---|
| 달팽이 원화 | `resources/sprites/` | 벡터 폴백으로 그린다 |
| 소품 | `resources/props/` | 소품 없이 |
| 책등 템플릿 | `resources/shelf/` | 단색 책등 |
| 폰트 + OFL 전문 | `resources/fonts/` | 시스템 폰트(맑은 고딕) |
| E5 ONNX 모델 | `resources/models/multilingual-e5-small-onnx/` | 되살리기가 쉰다 |
| 아이콘 | `resources/icon.ico` | 기본 아이콘 |

폰트를 넣을 때는 **OFL 전문을 함께** 넣는다. 빠뜨리면 라이선스 위반이다.
`resources/fonts/README.txt` 참조.

모델은 INT8 로 줄여 넣는다.

```
python tools/quantize_model.py resources/models/multilingual-e5-small-onnx --verify
```

## 빌드

```
pyinstaller ReadingSnail.spec
ISCC installer\ReadingSnail.iss
```

결과는 `dist/ReadingSnail/`(폴더)과 `dist/installer/`(설치 파일)에 나온다.

## 확인할 것

설치본을 처음 켤 때 반드시 눈으로 볼 것.

- [ ] 콘솔 창이 뜨지 않는다 (`console=False`)
- [ ] 달팽이가 투명 배경으로 뜬다 (`-transparentcolor` 는 Windows 전용이라
      개발 환경에서는 확인할 수 없다)
- [ ] 고DPI 화면에서 좌표가 어긋나지 않는다
- [ ] 동봉 폰트가 실제로 적용된다 (`theme.load_bundled_fonts()`)
- [ ] 기록이 `%LOCALAPPDATA%\ReadingSnail` 에 생긴다
- [ ] **삭제해도 그 폴더가 남는다**
- [ ] 다시 설치하면 기록이 그대로 이어진다
- [ ] 자동 시작을 켜면 재부팅 후에 뜬다 (기본은 꺼짐)
- [ ] 트레이로 보냈다가 돌아온다
- [ ] 두 번 실행하면 두 번째가 조용히 물러난다

## 자동 업데이트에 대하여

**아직 넣지 않았다.** 업데이트 서버(또는 GitHub Releases)와 서명 정책이
정해져야 만들 수 있다. 그때까지는 새 설치본을 받아 덮어 설치하면 된다 —
기록은 별도 폴더라 그대로 남고, 새 버전이 처음 켜질 때 자동으로 백업된다.
