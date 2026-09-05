"""앱 설정. 기록과 같은 파일에 산다.

기록이 아니므로 백업·내보내기에서 빠져도 되고, 초기화해도 글은 그대로다.
"""

from __future__ import annotations

from .db import Database

TRUE_WORDS = frozenset({'1', 'true', 'yes', 'on', 'y'})


class Settings:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str, default: str | None = None) -> str | None:
        with self.db.connect() as con:
            row = con.execute('SELECT value FROM settings WHERE key=?', (str(key),)).fetchone()
            return str(row['value']) if row else default

    def set(self, key: str, value: str) -> None:
        with self.db.write() as con:
            con.execute(
                'INSERT INTO settings(key, value) VALUES (?,?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                (str(key), str(value)),
            )

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self.get(key)
        return bool(default) if raw is None else raw.strip().lower() in TRUE_WORDS

    def set_bool(self, key: str, value: bool) -> None:
        self.set(key, '1' if value else '0')

    def get_int(self, key: str, default: int = 0) -> int:
        raw = self.get(key)
        if raw is None:
            return int(default)
        try:
            return int(raw.strip())
        except ValueError:
            return int(default)

    def all(self) -> dict[str, str]:
        with self.db.connect() as con:
            return {str(r['key']): str(r['value'])
                    for r in con.execute('SELECT key, value FROM settings').fetchall()}

    def clear(self) -> None:
        """설정만 기본값으로 되돌린다. 기록은 건드리지 않는다."""
        with self.db.write() as con:
            con.execute('DELETE FROM settings')
