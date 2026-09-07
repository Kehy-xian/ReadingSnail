"""백업과 복원. 기록을 지키는 마지막 그물이다.

두 가지 일을 한다
    1. **버전 전환 백업** — 새 버전이 처음 켜질 때, 스키마를 손대기 **전에**
       DB 를 통째로 복사해 둔다. 마이그레이션이 잘못돼도 어제로 돌아갈 수 있다.
       전작 version_backup.py 의 태도를 그대로 가져왔다.
    2. **수동 백업·복원** — 사용자가 원할 때, 또는 다른 컴퓨터로 옮길 때.

복사하는 방법
    파일을 그냥 복사하지 않는다. WAL 모드라 -wal 파일에 아직 반영 안 된 내용이
    있을 수 있다. SQLite 의 backup API 를 쓰면 그 시점의 일관된 사본이 나온다.

복원은 되돌릴 수 있어야 한다
    덮어쓰기 전에 현재 DB 를 먼저 백업한다. 잘못 복원했다고 오늘 쓴 기록을
    잃으면 안 된다.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..paths import readonly_uri

BACKUP_DIRNAME = 'backups'
BACKUP_SUFFIX = '.sqlite3'
VERSION_MARKER = 'app_version'
# 자동 백업을 이만큼만 남긴다. 무한히 쌓으면 디스크를 먹는다.
KEEP_AUTOMATIC = 8
# 우리가 붙이는 이름. 사용자가 넣어 둔 파일과 구분한다.
_AUTO_NAME = re.compile(r'^\d{8}-\d{6}-')


class BackupError(RuntimeError):
    """백업하거나 복원하지 못했다."""


@dataclass(frozen=True)
class BackupFile:
    path: Path
    made_at: datetime
    reason: str
    size: int

    @property
    def label(self) -> str:
        return f'{self.made_at:%Y-%m-%d %H:%M} · {self.reason} · {self.size / 1024:.0f}KB'


def backup_dir(data_dir: str | Path) -> Path:
    folder = Path(data_dir) / BACKUP_DIRNAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _unique_path(folder: Path, reason: str) -> Path:
    """겹치지 않는 백업 파일 경로.

    이름이 초 단위라 같은 초에 두 번 백업하면 앞의 것을 덮어쓴다.
    백업이 조용히 사라지는 것은 백업이 없는 것보다 나쁘다.
    """
    safe = ''.join(c for c in reason if c.isalnum() or c in '-_') or 'backup'
    stem = f'{datetime.now():%Y%m%d-%H%M%S}-{safe}'
    candidate = folder / f'{stem}{BACKUP_SUFFIX}'
    counter = 2
    while candidate.exists():
        candidate = folder / f'{stem}-{counter}{BACKUP_SUFFIX}'
        counter += 1
    return candidate


def _table_count(con: sqlite3.Connection) -> int:
    """사본이 실제로 담겼는지 확인할 때만 쓴다."""
    row = con.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()
    return int(row[0]) if row else 0


def copy_database(source: str | Path, target: str | Path) -> Path:
    """SQLite backup API 로 일관된 사본을 만든다.

    파일을 그냥 복사하면 WAL 에 남은 내용을 놓친다.
    """
    src_path, dst_path = Path(source), Path(target)
    if not src_path.is_file():
        raise BackupError(f'복사할 DB 가 없다: {src_path}')
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    # 받다 만 파일이 백업 목록에 남지 않게 임시 이름으로 쓰고 옮긴다.
    tmp = dst_path.with_name(dst_path.name + '.part')
    try:
        source_con = sqlite3.connect(readonly_uri(src_path), uri=True, timeout=10)
        try:
            expected = _table_count(source_con)
            target_con = sqlite3.connect(tmp)
            try:
                source_con.backup(target_con)
                copied = _table_count(target_con)
            finally:
                target_con.close()
        finally:
            source_con.close()
        if copied < expected:
            # 여기까지 왔는데 표가 모자라면 사본이 잘못된 것이다. 비어 있는 백업을
            # 멀쩡한 얼굴로 남기지 않는다 — 백업이 없는 것보다 나쁘다.
            raise BackupError(f'사본이 온전하지 않다: 표 {expected}개 중 {copied}개')
        tmp.replace(dst_path)
    except BackupError:
        tmp.unlink(missing_ok=True)     # 반쪽짜리 사본을 남기지 않는다
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise BackupError(f'백업하지 못했다: {exc}') from exc
    return dst_path


def make_backup(db_path: str | Path, data_dir: str | Path, *,
                reason: str = 'manual') -> Path:
    return copy_database(db_path, _unique_path(backup_dir(data_dir), reason))


def list_backups(data_dir: str | Path) -> list[BackupFile]:
    """최근 것부터."""
    folder = Path(data_dir) / BACKUP_DIRNAME
    if not folder.is_dir():
        return []
    found: list[BackupFile] = []
    for path in folder.glob(f'*{BACKUP_SUFFIX}'):
        try:
            stat = path.stat()
        except OSError:
            continue
        # 20260907-093658-manual 또는 ...-manual-2
        parts = path.stem.split('-')
        reason = 'backup'
        for part in reversed(parts):
            if not part.isdigit():
                reason = part
                break
        found.append(BackupFile(path=path,
                                made_at=datetime.fromtimestamp(stat.st_mtime),
                                reason=reason, size=stat.st_size))
    return sorted(found, key=lambda b: b.made_at, reverse=True)


def prune_backups(data_dir: str | Path, *, reason: str = 'version',
                  keep: int = KEEP_AUTOMATIC) -> int:
    """자동 백업만 솎아낸다. **손으로 만든 백업은 건드리지 않는다.**

    이름이 우리가 붙인 모양(`20260907-093658-version`)인 것만 센다. 사용자가
    백업 폴더에 넣어 둔 파일이 어쩌다 같은 꼬리표를 달았다고 지우면 안 된다.
    """
    automatic = [b for b in list_backups(data_dir)
                 if b.reason == reason and _AUTO_NAME.match(b.path.stem)]
    removed = 0
    for old in automatic[keep:]:
        try:
            old.path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def restore_backup(backup_path: str | Path, db_path: str | Path,
                   data_dir: str | Path) -> Path:
    """백업으로 되돌린다. **덮어쓰기 전에 지금 것을 먼저 백업한다.**

    잘못 복원했다고 오늘 쓴 기록을 잃으면 안 된다.
    돌려주는 값은 되돌리기용으로 만든 백업의 경로.
    """
    source, target = Path(backup_path), Path(db_path)
    if not source.is_file():
        raise BackupError(f'백업 파일이 없다: {source}')
    try:
        probe = sqlite3.connect(readonly_uri(source), uri=True)
        try:
            probe.execute('SELECT count(*) FROM entries').fetchone()
        finally:
            probe.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f'백업 파일이 온전하지 않다: {exc}') from exc

    undo = (make_backup(target, data_dir, reason='prerestore')
            if target.is_file() else None)
    try:
        copy_database(source, target)
    except BackupError:
        raise
    # WAL 잔재가 남아 옛 내용이 되살아나지 않게 함께 지운다.
    # **못 지워도 넘어간다.** 배경 작업자가 연결을 쥐고 있으면 Windows 는 열린
    # -shm 을 지우지 못하고 PermissionError 를 낸다. 본체는 이미 바뀌었으므로
    # 여기서 예외를 올리면 '되돌렸는데 실패했다'고 말하는 꼴이 된다.
    for extra in (target.with_name(target.name + '-wal'),
                  target.with_name(target.name + '-shm')):
        try:
            extra.unlink(missing_ok=True)
        except OSError:
            pass
    return undo if undo is not None else target


def backup_for_version(db_path: str | Path, data_dir: str | Path,
                       current_version: str, *,
                       stored_version: str | None) -> Path | None:
    """새 버전이 처음 켜질 때 한 번만. 스키마를 손대기 **전에** 부를 것.

    stored_version 은 settings 등에 적어 둔 지난 버전. 같으면 아무 일도 안 한다.
    """
    if stored_version == current_version:
        return None
    if not Path(db_path).is_file():
        return None                      # 새 설치. 지킬 기록이 없다.
    made = make_backup(db_path, data_dir, reason='version')
    prune_backups(data_dir, reason='version')
    return made


def export_bundle(db_path: str | Path, target: str | Path,
                  data_dir: str | Path | None = None) -> Path:
    """다른 컴퓨터로 옮길 때. DB 한 벌을 통째로 내보낸다.

    표지 이미지까지 담지는 않는다 — 표지는 다시 받을 수 있고, 기록이 본체다.
    """
    return copy_database(db_path, target)


def import_bundle(bundle: str | Path, db_path: str | Path,
                  data_dir: str | Path) -> Path:
    """다른 컴퓨터에서 가져온 DB 로 바꾼다. 되돌리기용 백업 경로를 돌려준다."""
    return restore_backup(bundle, db_path, data_dir)


def copy_tree_size(path: str | Path) -> int:
    total = 0
    for item in Path(path).rglob('*'):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total
