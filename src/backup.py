"""Backups for PinSaver.

`python src/backup.py` creates a zip archive in backups/ containing:
- All original images from originals/ that are newer than the last backup timestamp
- A snapshot of the SQLite database (always included)

Backup state is stored in backups/backup_state.json.

The same functions serve the maintenance page (see server.py): `run_backup()` creates an
incremental archive, `iter_full_backup_zip()` streams the database plus every original, and
`list_backups()` says what is already on disk.
"""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from models import get_base_path, get_db_path, get_originals_path

#: Files are copied into a streamed archive in 1 MiB pieces: a full backup can be gigabytes
#: and must not be held in memory.
COPY_CHUNK = 1024 * 1024

#: Original images are already compressed, so storing them beats deflating them: the archive
#: is a couple of percent larger and a full backup is an order of magnitude faster.
IMAGE_COMPRESSION = zipfile.ZIP_STORED


@dataclass(frozen=True)
class BackupPaths:
    """Represents all paths used by the backup script."""

    base_path: Path
    originals_path: Path
    db_path: Path
    output_dir: Path
    state_path: Path


def get_paths() -> BackupPaths:
    """Build and return backup paths based on the archive data directory."""

    base_path = get_base_path()
    originals_path = get_originals_path()
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


def last_backup_utc(paths: BackupPaths | None = None) -> str | None:
    """Timestamp of the last incremental backup as an ISO string, or None."""

    last_backup_time = load_last_backup_time((paths or get_paths()).state_path)
    return last_backup_time.isoformat() if last_backup_time else None


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


def originals_stats(originals_path: Path) -> dict:
    """Number of images and their total size, for the maintenance page."""

    files = collect_originals_to_backup(originals_path, None)
    return {
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
    }


def ensure_output_dir(output_dir: Path) -> None:
    """Ensure output directory exists."""

    output_dir.mkdir(parents=True, exist_ok=True)


def build_backup_zip_name(now_utc: datetime) -> str:
    """Build a zip filename based on timestamp."""

    return f"backup_{now_utc.strftime('%Y%m%d_%H%M%S')}.zip"


def build_full_backup_name(now_utc: datetime) -> str:
    """Build the filename of the streamed full archive (database plus every image)."""

    return f"pinsaver_full_{now_utc.strftime('%Y%m%d_%H%M%S')}.zip"


def unique_path(path: Path) -> Path:
    """Free name next to `path`: two backups in the same second must not overwrite each other."""

    if not path.exists():
        return path

    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate

    raise OSError(f"cannot find a free backup name next to {path}")


def write_state(state_path: Path, last_backup_time: datetime, zip_path: Path) -> None:
    """Write backup state file."""

    state = {
        "last_backup_utc": last_backup_time.isoformat(),
        "last_backup_zip": zip_path.name,
    }

    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def snapshot_database(db_path: Path, dest_path: Path) -> Path:
    """Copy a live database consistently, through the SQLite online backup API.

    Copying the file byte by byte can catch the server in the middle of a write and put a
    torn database into the archive; the backup API copies it under a read transaction.
    """

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(db_path)
    try:
        target = sqlite3.connect(dest_path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    return dest_path


def create_backup_zip(zip_path: Path, db_path: Path, originals_files: list[Path]) -> Path:
    """Create backup zip file with a database snapshot and provided originals files."""

    # Written next to the final name and renamed at the end: a backup interrupted halfway
    # must not leave a zip that looks complete.
    partial_path = zip_path.with_name(zip_path.name + ".part")
    try:
        with zipfile.ZipFile(partial_path, mode="w", compression=zipfile.ZIP_DEFLATED,
                             allowZip64=True) as zf:
            if db_path.exists():
                with tempfile.TemporaryDirectory() as tmp_dir:
                    snapshot = snapshot_database(db_path, Path(tmp_dir) / db_path.name)
                    zf.write(snapshot, arcname=db_path.name)

            for file_path in originals_files:
                zf.write(file_path, arcname=str(Path("originals") / file_path.name),
                         compress_type=IMAGE_COMPRESSION)

        partial_path.replace(zip_path)
    finally:
        partial_path.unlink(missing_ok=True)

    return zip_path


class _StreamSink(io.RawIOBase):
    """Write-only buffer that hands whatever zipfile writes to the stream generator."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        self._buffer.extend(data)
        return len(data)

    def pop(self) -> bytes:
        """Take the bytes written so far and forget them."""

        data = bytes(self._buffer)
        self._buffer.clear()
        return data


def _flush(sink: _StreamSink) -> Iterator[bytes]:
    """Yield the bytes zipfile has written since the last flush, if any."""

    data = sink.pop()
    if data:
        yield data


def _stream_file(zf: zipfile.ZipFile, sink: _StreamSink, arcname: str, path: Path,
                 compress_type: int) -> Iterator[bytes]:
    """Copy one file into the archive in pieces, yielding bytes as they are written."""

    info = zipfile.ZipInfo.from_file(path, arcname, strict_timestamps=False)
    info.compress_type = compress_type
    with zf.open(info, "w", force_zip64=True) as target, path.open("rb") as source:
        while chunk := source.read(COPY_CHUNK):
            target.write(chunk)
            yield from _flush(sink)


def iter_full_backup_zip(paths: BackupPaths | None = None) -> Iterator[bytes]:
    """Stream the whole archive: a database snapshot plus every original image.

    The zip is built on the fly, so the download starts immediately and the server needs no
    free disk space for it, however large the archive is.
    """

    paths = paths or get_paths()
    sink = _StreamSink()

    with tempfile.TemporaryDirectory() as tmp_dir:
        snapshot = None
        if paths.db_path.exists():
            snapshot = snapshot_database(paths.db_path, Path(tmp_dir) / paths.db_path.name)

        with zipfile.ZipFile(sink, mode="w", allowZip64=True) as zf:
            if snapshot is not None:
                yield from _stream_file(zf, sink, paths.db_path.name, snapshot,
                                        zipfile.ZIP_DEFLATED)
                yield from _flush(sink)

            for file_path in collect_originals_to_backup(paths.originals_path, None):
                yield from _stream_file(zf, sink, str(Path("originals") / file_path.name),
                                        file_path, IMAGE_COMPRESSION)
                yield from _flush(sink)

        # The central directory is written when the archive is closed: send it too.
        yield from _flush(sink)


def backup_item(zip_path: Path, created_utc: datetime | None = None) -> dict:
    """One backup as JSON: file name, size in bytes and creation time."""

    created = created_utc or file_mtime_utc(zip_path)
    return {
        "name": zip_path.name,
        "bytes": zip_path.stat().st_size,
        "created_utc": created.isoformat(),
    }


def list_backups(paths: BackupPaths | None = None) -> list[dict]:
    """List the backup zips on disk, newest first."""

    output_dir = (paths or get_paths()).output_dir
    if not output_dir.is_dir():
        return []

    zip_files = [p for p in output_dir.glob("*.zip") if p.is_file()]
    zip_files.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    return [backup_item(p) for p in zip_files]


def run_backup(paths: BackupPaths | None = None) -> dict:
    """Create one incremental backup and describe it.

    This is what `main()` prints and what the maintenance page runs on demand.
    """

    paths = paths or get_paths()
    ensure_output_dir(paths.output_dir)

    last_backup_time = load_last_backup_time(paths.state_path)
    originals_files = collect_originals_to_backup(paths.originals_path, last_backup_time)

    now = utc_now()
    zip_path = unique_path(paths.output_dir / build_backup_zip_name(now))

    create_backup_zip(zip_path, paths.db_path, originals_files)
    write_state(paths.state_path, now, zip_path)

    return {
        **backup_item(zip_path, created_utc=now),
        "originals": len(originals_files),
        "database": paths.db_path.exists(),
        "previous_backup_utc": last_backup_time.isoformat() if last_backup_time else None,
    }


def main() -> None:
    """Entry point."""

    paths = get_paths()
    result = run_backup(paths)

    print("Backup created")
    print(f"  Zip: {paths.output_dir / result['name']}")
    print(f"  Database: {'included' if result['database'] else 'missing'}")
    print(f"  Originals included: {result['originals']}")
    print(f"  Previous backup time (UTC): {result['previous_backup_utc'] or 'none'}")
    print(f"  New backup time (UTC): {result['created_utc']}")


if __name__ == "__main__":
    main()
