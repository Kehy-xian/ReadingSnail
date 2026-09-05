#!/usr/bin/env python3
"""multilingual-e5-small ONNX 를 INT8 로 줄인다.

왜
    설치본 239MB 의 대부분이 이 모델이다(docs/PORTING_MAP.md). 전작에서 진화·육성
    코드를 전부 걷어내도 용량은 거의 그대로다. 의미 검색을 유지하기로 했으므로
    모델은 남고, 대신 양자화로 줄인다. 목표 60~80MB 대.

무엇을 하는가
    onnxruntime.quantization 의 동적 양자화(QUInt8). 보정 데이터가 필요 없어
    빌드 파이프라인에 넣기 쉽다.

바꾸고 나면 반드시 할 것
    1. **MODEL_ID 를 바꾼다** (nlp/encoder.py). 좌표계가 달라지므로 옛 벡터와
       섞으면 안 된다. 바꾸면 저장소가 알아서 재인코딩 대상으로 잡는다.
    2. 아래 --verify 로 원본과 코사인 유사도를 비교한다. 0.99 아래로 떨어지면
       되살리기 문턱(0.72)도 함께 조정해야 한다.

이 스크립트는 빌드 때만 돈다. 앱은 이걸 부르지 않는다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 원본과 양자화본이 같은 문장에서 이만큼은 닮아야 한다.
MIN_AGREEMENT = 0.99

SAMPLES = [
    '숲으로 간 이유를 오래 생각했다',
    '책은 우리 안의 얼어붙은 바다를 깨는 도끼여야 한다',
    '오늘 점심은 김치찌개였다',
    '이 문장은 다시 읽어도 마음에 남는다',
    '통계와 자료를 직접 확인해보고 싶어졌다',
    'A quiet sentence in English to check multilingual behaviour.',
]


def quantize(src: Path, dst: Path) -> None:
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
    except ImportError:
        sys.exit('onnxruntime 가 필요하다:  pip install onnxruntime')

    if not src.is_file():
        sys.exit(f'원본 모델이 없다: {src}')
    dst.parent.mkdir(parents=True, exist_ok=True)
    quantize_dynamic(model_input=str(src), model_output=str(dst),
                     weight_type=QuantType.QUInt8)

    before = src.stat().st_size / 1e6
    after = dst.stat().st_size / 1e6
    print(f'{src.name}  {before:.1f}MB  →  {dst.name}  {after:.1f}MB '
          f'({100 * (1 - after / before):.0f}% 감소)')


def verify(original_dir: Path, quantized_dir: Path) -> int:
    """같은 문장을 두 모델로 인코딩해 비교한다."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from readingsnail.nlp.encoder import E5Encoder          # noqa: E402
    from readingsnail.nlp.vectors import cosine             # noqa: E402

    a = E5Encoder(original_dir).encode(SAMPLES)
    b = E5Encoder(quantized_dir).encode(SAMPLES)
    if len(a) != len(b):
        print('두 모델의 출력 개수가 다르다', file=sys.stderr)
        return 1

    worst = 1.0
    print(f'{"유사도":>8}  문장')
    for text, va, vb in zip(SAMPLES, a, b):
        score = cosine(va, vb)
        worst = min(worst, score)
        print(f'{score:8.4f}  {text[:44]}')

    # 문장 사이의 순위가 뒤집히지 않는지도 본다. 되살리기는 절대값이 아니라
    # '누가 더 가까운가'로 동작하므로 순위가 더 중요하다.
    def ranking(rows):
        base = rows[0]
        return [i for i, _ in sorted(enumerate(rows[1:]),
                                     key=lambda p: -cosine(base, p[1]))]

    same_order = ranking(a) == ranking(b)
    print(f'\n최저 유사도 {worst:.4f} (기준 {MIN_AGREEMENT})  |  '
          f'근접 순위 유지: {"예" if same_order else "아니오"}')
    if worst < MIN_AGREEMENT or not same_order:
        print('\n⚠ 되살리기 문턱(dialogue.ECHO_MIN_SIMILARITY = 0.72)을 다시 맞출 것.',
              file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='E5 ONNX 모델 INT8 양자화')
    parser.add_argument('model_dir', type=Path,
                        help='원본 모델 폴더 (model.onnx, tokenizer.json)')
    parser.add_argument('-o', '--out', type=Path, default=None,
                        help='결과 폴더 (기본: <model_dir>-int8)')
    parser.add_argument('--verify', action='store_true',
                        help='양자화 후 원본과 비교한다')
    args = parser.parse_args(argv)

    out = args.out or args.model_dir.with_name(args.model_dir.name + '-int8')
    out.mkdir(parents=True, exist_ok=True)
    quantize(args.model_dir / 'model.onnx', out / 'model.onnx')

    # 토크나이저는 그대로 써야 한다. 양자화는 가중치만 건드린다.
    for name in ('tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json'):
        source = args.model_dir / name
        if source.is_file():
            (out / name).write_bytes(source.read_bytes())

    if args.verify:
        return verify(args.model_dir, out)
    print('\n--verify 로 원본과 비교해 볼 것. MODEL_ID 변경도 잊지 말 것.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
