"""
Restore image files that are missing from `originals/`.

A row is only half a pin: the site serves `originals/<file_id>.<file_extension>`, so a file
deleted by hand or lost in a copy leaves a card that cannot load. This script walks the
database and downloads every missing file again from the link in `original_url`, through the
same candidates as a save (`archive.download_image`: the stored URL first, then the sizes
Pinterest still serves) and the same format rules (`images.prepare`: HEIC becomes JPEG).

A restored file is written now, so its mtime is newer than the last backup watermark and the
next `python src/backup.py` picks it up: no separate full backup is needed.

    python src/repair_images.py --dry-run   # only list what is missing
    python src/repair_images.py             # download and write the files
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import archive
import images
from models import get_db_path, get_originals_path


def repair_archive(
    originals_path: Path,
    db_path: Path,
    dry_run: bool = False,
    client=None,
) -> dict:
    """
    Find every pin whose image file is not on disk and download it again.

    Args:
        originals_path: The folder with the archived images.
        db_path: The SQLite database.
        dry_run: Only report what is missing.
        client: Optional download client (tests inject one with a mock transport).

    Returns:
        Counters: `pins` (rows looked at), `missing`, `repaired`, `failed` and
        `rows_updated` (rows whose `file_extension` followed the downloaded format).
    """
    stats = {"pins": 0, "missing": 0, "repaired": 0, "failed": 0, "rows_updated": 0}

    if not db_path.exists():
        print(f"Nothing to do: {db_path} does not exist")
        return stats

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    own_client = None
    seen: set[str] = set()

    try:
        rows = conn.execute(
            "SELECT file_id, file_extension, original_url FROM pins ORDER BY id"
        ).fetchall()

        for row in rows:
            stats["pins"] += 1
            file_id = row["file_id"]
            if file_id in seen:
                # Duplicates share one file: check it once, not once per pin
                continue
            seen.add(file_id)

            image_path = originals_path / f"{file_id}.{row['file_extension']}"
            if image_path.is_file() and image_path.stat().st_size:
                continue

            stats["missing"] += 1
            print(f"  missing {image_path.name}")
            if dry_run:
                continue

            if not row["original_url"]:
                stats["failed"] += 1
                print(f"  failed {image_path.name}: no original_url in the database")
                continue

            if client is None:
                if own_client is None:
                    own_client = archive.new_client()
                client = own_client

            try:
                downloaded = archive.download_image(
                    client, file_id, row["file_extension"], row["original_url"]
                )
            except archive.AddPinError as error:
                stats["failed"] += 1
                print(f"  failed {image_path.name}: {error.detail}")
                continue

            try:
                prepared = images.prepare(downloaded.content, downloaded.extension)
            except images.ImageConversionError:
                # Same rule as a save: an undecodable HEIC is stored as it came
                prepared = images.PreparedImage(downloaded.content, downloaded.extension)

            originals_path.mkdir(parents=True, exist_ok=True)
            target = originals_path / f"{file_id}.{prepared.extension}"
            target.write_bytes(prepared.content)
            if prepared.original:
                original_path = originals_path / f"{file_id}.{prepared.original_extension}"
                original_path.write_bytes(prepared.original)

            stats["repaired"] += 1
            print(f"  restored {target.name} from {downloaded.url} ({downloaded.size})")

            if prepared.extension != row["file_extension"]:
                # The bytes decide the format, not the row: keep `/images/` able to find it
                cursor = conn.execute(
                    "UPDATE pins SET file_extension = ? WHERE file_id = ?",
                    (prepared.extension, file_id),
                )
                stats["rows_updated"] += cursor.rowcount
                conn.commit()
    finally:
        if own_client is not None:
            own_client.close()
        conn.close()

    return stats


def main() -> None:
    """Entry point."""

    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="only report what is missing")
    args = parser.parse_args()

    originals_path = get_originals_path()
    db_path = get_db_path()

    print("Missing image check")
    print("=" * 40)
    print(f"Originals: {originals_path}")
    print(f"Database: {db_path}")

    stats = repair_archive(originals_path, db_path, dry_run=args.dry_run)

    print()
    print("Dry run, nothing changed" if args.dry_run else "Repair complete")
    print("=" * 40)
    print(f"Pins checked: {stats['pins']}")
    print(f"Missing files: {stats['missing']}")
    if not args.dry_run:
        print(f"Restored: {stats['repaired']}")
        print(f"Failed: {stats['failed']}")
        print(f"Database rows updated: {stats['rows_updated']}")
        if stats["repaired"]:
            print("Run `python src/backup.py` to put the new files into the next backup")


if __name__ == "__main__":
    main()
