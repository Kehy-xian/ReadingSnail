달팽이 스프라이트 위치.

통짜   snail_<state>_<nn>.png
분리   snail_body_<state>_<nn>.png  +  snail_shell.png (고정 한 장)
       껍데기를 고정 레이어로 빼면 walk 12장에서 몸통만 그리면 된다.

190x190, 8-bit RGBA, 투명 배경. 좌향만 그린다(우향은 좌우 반전).
규격은 docs/SPRITE_GUIDE_KO.md 참조.

비어 있어도 벡터 폴백으로 앱이 동작한다. 한 상태씩 채워 나가면 된다.

규격 확인용 자리표시를 만들려면 (원화 아님, 저장소에 커밋하지 않는다)
    python tools/render_placeholder_pack.py

원화를 받으면
    python tools/validate_sprite_pack.py <폴더> --require
    python tools/install_sprite_pack.py <폴더>
