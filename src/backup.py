"""Incremental backup script for PinSaver.

Creates a zip archive in testPages/ containing:
- All original images from originals/ that are newer than the last backup timestamp
- The SQLite database file (always included)

Backup state is stored in testPages/backup_state.json.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from models import get_db_path


@dataclass(frozen=True)
class BackupPaths:
    """Represents all paths used by the backup script."""

    base_path: Path
    originals_path: Path
    db_path: Path
    output_dir: Path
    state_path: Path


def get_paths() -> BackupPaths:
    """Build and return backup paths based on repository structure."""

    base_path = Path(__file__).parent.parent
    originals_path = base_path / "originals"
    db_path = get_db_path()
    output_dir = base_path / "backups"
    state_path = output_dir / "backup_state.json"

    return BackupPaths(
        base_path=base_path,
        originals_path=originals_path,
        db_path=db_path,
        output_dir=output_dir,
        state_path=state_path,
    )


def utc_now() -> datetime:
    """Return the current time in UTC."""

    return datetime.now(timezone.utc)


def parse_utc_iso(value: str) -> datetime:
    """Parse an ISO8601 timestamp and return an aware datetime in UTC."""

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def load_last_backup_time(state_path: Path) -> datetime | None:
    """Load last backup timestamp from state file."""

    if not state_path.exists():
        return None

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    last_backup_utc = state.get("last_backup_utc")
    if not isinstance(last_backup_utc, str) or not last_backup_utc.strip():
        return None

    try:
        return parse_utc_iso(last_backup_utc)
    except Exception:
        return None


def file_mtime_utc(path: Path) -> datetime:
    """Get file mtime as an aware UTC datetime."""

    mtime_seconds = path.stat().st_mtime
    return datetime.fromtimestamp(mtime_seconds, tz=timezone.utc)


def collect_originals_to_backup(originals_path: Path, last_backup_time: datetime | None) -> list[Path]:
    """Collect originals files to include in backup based on last backup time."""

    if not originals_path.exists():
        return []

    files = [p for p in originals_path.iterdir() if p.is_file()]

    if last_backup_time is None:
        return sorted(files)

    return sorted([p for p in files if file_mtime_utc(p) > last_backup_time])


def ensure_output_dir(output_dir: Path) -> None:
    """Ensure output directory exists."""

    output_dir.mkdir(parents=True, exist_ok=True)


def build_backup_zip_name(now_utc: datetime) -> str:
    """Build a zip filename based on timestamp."""

    return f"backup_{now_utc.strftime('%Y%m%d_%H%M%S')}.zip"


def write_state(state_path: Path, last_backup_time: datetime, zip_path: Path) -> None:
    """Write backup state file."""

    state = {
        "last_backup_utc": last_backup_time.isoformat(),
        "last_backup_zip": zip_path.name,
    }

    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def create_backup_zip(zip_path: Path, db_path: Path, originals_files: list[Path]) -> None:
    """Create backup zip file with database and provided originals files."""

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        if db_path.exists():
            zf.write(db_path, arcname=db_path.name)

        for file_path in originals_files:
            zf.write(file_path, arcname=str(Path("originals") / file_path.name))


def main() -> None:
    """Entry point."""

    paths = get_paths()
    ensure_output_dir(paths.output_dir)

    last_backup_time = load_last_backup_time(paths.state_path)
    originals_files = collect_originals_to_backup(paths.originals_path, last_backup_time)

    now = utc_now()
    zip_name = build_backup_zip_name(now)
    zip_path = paths.output_dir / zip_name

    create_backup_zip(zip_path, paths.db_path, originals_files)
    write_state(paths.state_path, now, zip_path)

    last_backup_text = last_backup_time.isoformat() if last_backup_time else "none"
    print("Backup created")
    print(f"  Zip: {zip_path}")
    print(f"  Database: {'included' if paths.db_path.exists() else 'missing'}")
    print(f"  Originals included: {len(originals_files)}")
    print(f"  Previous backup time (UTC): {last_backup_text}")
    print(f"  New backup time (UTC): {now.isoformat()}")


if __name__ == "__main__":
    main()
