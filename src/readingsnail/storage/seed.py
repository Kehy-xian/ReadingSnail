"""독서 명언 시드 주입.

달팽이는 기록이 0건일 때 명언 갈래만 사용한다(services/dialogue.py).
시드가 비어 있으면 pick_channel 이 None 을 반환해 달팽이가 아무 말도 못 한다.
첫 실행 사용자가 마주치는 화면이므로, DB 를 여는 시점에 반드시 한 번 돌린다.

되살아남 방지
    사용자가 지운 명언을 다음 실행에서 되돌려 넣지 않는다. 판단 근거는
    quote_seed_log 다. 한 번 넣은 id 는 여기 남고, 다시는 넣지 않는다.
    quotes 테이블만 보고 판단하면 '지운 것'과 '아직 안 넣은 것'을 구분할 수 없다.

명언 추가
    seeds/quotes_ko.json 뒤에 새 id 로 붙이면 다음 실행에서 그것만 들어온다.
    기존 항목의 문구를 고쳐도 이미 설치된 DB 는 건드리지 않는다. 사용자가
    직접 손본 명언을 덮어쓰지 않기 위해서다.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SEED_DIR = Path(__file__).parent / 'seeds'
DEFAULT_SEED = SEED_DIR / 'quotes_ko.json'


def load_seed_file(path: Path | None = None) -> list[dict[str, str]]:
    """시드 파일을 읽어 검증한다. 형식이 깨졌으면 여기서 죽는다."""
    path = path or DEFAULT_SEED
    data = json.loads(path.read_text(encoding='utf-8'))
    quotes = data['quotes']

    seen: set[str] = set()
    for q in quotes:
        qid, body, source = q.get('id'), q.get('body'), q.get('source')
        if not qid or not body:
            raise ValueError(f'시드 항목에 id 또는 body 가 없다: {q!r}')
        if not (source or '').strip():
            # 스키마 주석대로 출처 없는 명언은 넣지 않는다.
            raise ValueError(f'출처가 비어 있다: {qid}')
        if qid in seen:
            raise ValueError(f'시드 id 가 중복이다: {qid}')
        seen.add(qid)
    return quotes


def seed_quotes(conn: sqlite3.Connection, path: Path | None = None,
                *, strict: bool = False) -> int:
    """아직 넣은 적 없는 명언만 넣는다. 넣은 건수를 돌려준다.

    여러 번 불러도 안전하다(멱등).

    **시드 파일이 깨져도 앱은 켜져야 한다.** 명언은 장식이고 기록이 본체다.
    설치가 덜 끝났거나 파일이 손상됐다고 앱 전체가 안 열리면 사용자는 자기
    기록에 접근할 길이 없어진다. 그때는 달팽이의 말수가 줄 뿐이다.

    strict=True 는 도구·테스트용이다. 시드를 고칠 때 실수를 잡으려면 이쪽을 쓴다.
    """
    try:
        quotes = load_seed_file(path)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        if strict:
            raise
        return 0
    applied = {row[0] for row in conn.execute('SELECT quote_id FROM quote_seed_log')}
    fresh = [q for q in quotes if q['id'] not in applied]
    if not fresh:
        return 0

    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO quotes(quote_id, body, source, origin)"
            " VALUES (?, ?, ?, 'seed')",
            [(q['id'], q['body'], q['source']) for q in fresh],
        )
        conn.executemany(
            'INSERT OR IGNORE INTO quote_seed_log(quote_id, applied_at) VALUES (?, ?)',
            [(q['id'], now) for q in fresh],
        )
    return len(fresh)


def add_user_quote(conn: sqlite3.Connection, quote_id: str, body: str, source: str) -> None:
    """사용자가 직접 넣는 명언. origin='user' 라 시드 갱신에 휘둘리지 않는다."""
    if not source.strip():
        raise ValueError('출처를 비워둘 수 없다')
    with conn:
        conn.execute(
            "INSERT INTO quotes(quote_id, body, source, origin) VALUES (?, ?, ?, 'user')",
            (quote_id, body, source),
        )
