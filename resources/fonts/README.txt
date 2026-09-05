동봉 폰트를 여기에 둔다.

이 폴더의 폰트 파일은 .gitignore 로 막혀 있다. 라이선스를 확인하기 전에
커밋되면 곤란하기 때문이다. 확인한 뒤 개별 예외 처리할 것.

──────────────────────────────────────────────────────
쓰기로 한 폰트와 라이선스 (2026-09 확인)

  NanumSquareRound   제목·말풍선
    © NAVER Corporation
    SIL Open Font License 1.1
    https://hangeul.naver.com/font

  Pretendard         본문
    © Kil Hyung-jin
    SIL Open Font License 1.1
    https://github.com/orioncactus/pretendard

OFL 1.1 이 허용하는 것
  · 앱에 묶어 배포 (번들)
  · 문서·이미지에 임베딩
  · 개인·상업적 사용

OFL 1.1 이 요구하는 것
  · **라이선스 전문(OFL.txt)을 함께 배포할 것.** 이게 빠지면 위반이다.
  · 글꼴 파일 자체를 유료로 되팔지 말 것
  · 수정본에 예약 글꼴 이름(NanumSquareRound 등)을 쓰지 말 것

따라서 배포본에 넣어야 하는 것
  resources/fonts/NanumSquareRoundR.ttf
  resources/fonts/NanumSquareRoundB.ttf
  resources/fonts/Pretendard-Regular.ttf
  resources/fonts/Pretendard-SemiBold.ttf
  resources/fonts/OFL-NanumSquareRound.txt   ← 라이선스 전문
  resources/fonts/OFL-Pretendard.txt         ← 라이선스 전문

──────────────────────────────────────────────────────
설치하지 않고 쓴다

theme.load_bundled_fonts() 가 Windows 에서 AddFontResourceExW(FR_PRIVATE)로
이 프로세스에만 등록한다. 사용자 컴퓨터에 폰트를 설치하지 않는다 —
설치·삭제가 사용자 환경을 건드리지 않아야 한다는 제약과 같은 태도다.

폰트가 없으면 theme.py 의 스택에서 다음 후보(맑은 고딕 등)로 내려간다.
없다고 앱이 멈추지 않는다.
