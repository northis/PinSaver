"""
Convert the HEIC/HEIF images already in `originals/` to JPEG.

Chrome, Firefox and Edge cannot decode HEIC, so pins archived before 2.7.3 showed a blank
card while the file itself downloaded fine. New pins are converted when they are saved
(`archive.py`); this script fixes the files that are already on disk. It looks at the
bytes, not at the name, so running it twice is harmless: a file that is not HEIC is left
alone.

    python src/convert_heic.py --dry-run          # show what would change
    python src/convert_heic.py                    # convert and update the database
    python src/convert_heic.py --delete-originals # and remove the HEIC files

The HEIC originals stay next to the JPEGs by default, exactly as a pin saved after 2.7.3
leaves them: the site shows the JPEG, the archive keeps the original.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import images
from models import get_db_path, get_originals_path

#: Extension a converted file is stored under; the database row follows it.
TARGET_EXTENSION = "jpg"


def convert_archive(
    originals_path: Path,
    db_path: Path,
    dry_run: bool = False,
    keep_originals: bool = True,
) -> dict:
    """
    Convert every HEIC/HEIF file in the originals folder to JPEG.

    Each file becomes `<file_id>.jpg` next to it, the `file_extension` of its pins is
    updated, and the HEIC file is removed only with `keep_originals=False`. A pin keeps
    its `original_url`, so the provenance stays as it was.

    Args:
        originals_path: The folder with the archived images.
        db_path: The SQLite database (missing is fine: the files are still converted).
        dry_run: Only report what would be converted.
        keep_originals: Leave the HEIC files next to the JPEGs (the default).

    Returns:
        Counters: `converted`, `skipped` (a JPEG already exists), `failed`,
        `deleted` (converted and the HEIC was removed) and `rows_updated`.
    """
    stats = {
        "converted": 0,
        "skipped": 0,
        "failed": 0,
        "deleted": 0,
        "rows_updated": 0,
    }

    if not originals_path.is_dir():
        print(f"Nothing to do: {originals_path} does not exist")
        return stats

    conn = sqlite3.connect(db_path) if db_path.exists() else None
    try:
        for source in sorted(originals_path.iterdir()):
            if not source.is_file():
                continue

            data = source.read_bytes()
            if images.sniff(data) not in images.CONVERTED_FORMATS:
                continue

            target = source.with_suffix(f".{TARGET_EXTENSION}")
            if target.exists():
                stats["skipped"] += 1
                print(f"  skip {source.name}: {target.name} already exists")
                continue

            if dry_run:
                stats["converted"] += 1
                print(f"  would convert {source.name} -> {target.name}")
                continue

            try:
                jpeg = images.to_jpeg(data)
            except images.ImageConversionError as error:
                stats["failed"] += 1
                print(f"  failed {source.name}: {error}")
                continue

            # Write beside the original and rename, so an interrupted run never leaves a
            # half-written JPEG under the name the database points at.
            temporary = target.with_name(target.name + ".part")
            temporary.write_bytes(jpeg)
            temporary.replace(target)

            if conn is not None:
                cursor = conn.execute(
                    "UPDATE pins SET file_extension = ? WHERE file_id = ? AND file_extension <> ?",
                    (TARGET_EXTENSION, source.stem, TARGET_EXTENSION),
                )
                stats["rows_updated"] += cursor.rowcount
                conn.commit()

            stats["converted"] += 1
            if keep_originals:
                print(f"  converted {source.name} -> {target.name} (original kept)")
            else:
                source.unlink()
                stats["deleted"] += 1
                print(f"  converted {source.name} -> {target.name} (original removed)")
    finally:
        if conn is not None:
            conn.close()

    return stats


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="only report what would change")
    parser.add_argument(
        "--delete-originals",
        action="store_true",
        help="remove the HEIC files after they are converted",
    )
    args = parser.parse_args()

    originals_path = get_originals_path()
    db_path = get_db_path()

    print("HEIC to JPEG conversion")
    print("=" * 40)
    print(f"Originals: {originals_path}")
    print(f"Database: {db_path}")

    stats = convert_archive(
        originals_path,
        db_path,
        dry_run=args.dry_run,
        keep_originals=not args.delete_originals,
    )

    print()
    print("Dry run, nothing changed" if args.dry_run else "Conversion complete")
    print("=" * 40)
    print(f"Converted: {stats['converted']}")
    print(f"Database rows updated: {stats['rows_updated']}")
    print(f"Skipped (JPEG already exists): {stats['skipped']}")
    print(f"Failed: {stats['failed']}")
    if args.delete_originals:
        print(f"Originals removed: {stats['deleted']}")


if __name__ == "__main__":
    main()
