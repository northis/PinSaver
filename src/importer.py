"""
Importer for Pinterest archive data.
Parses HTML files and imports pins into SQLite database.
"""
import sqlite3
from pathlib import Path

from models import Pin, get_db_path, init_db, insert_pin, get_pin_count
from parser import parse_html_file, get_html_files


def get_originals_path(base_path: Path) -> Path:
    """
    Get the path to the originals folder.
    
    Args:
        base_path: The base Pinterest archive directory.
    
    Returns:
        Path to the originals folder.
    """
    return base_path / "originals"


def file_exists_in_originals(originals_path: Path, file_id: str, file_extension: str) -> bool:
    """
    Check if an image file exists in the originals folder.
    
    Args:
        originals_path: Path to the originals folder.
        file_id: The file ID (32-character hex string).
        file_extension: The file extension (jpg, png, webp, etc.).
    
    Returns:
        True if the file exists, False otherwise.
    """
    file_path = originals_path / f"{file_id}.{file_extension}"
    return file_path.exists()


def import_pins(base_path: Path, db_path: Path | None = None) -> dict:
    """
    Import all pins from HTML files into the database.
    
    Processes HTML files in chronological order (oldest first).
    Pins are extracted in reverse order from each HTML (oldest first within file).
    Duplicate pins (by pin_id) are skipped to handle overlapping HTML saves.
    Pins without corresponding files in originals/ are skipped.
    
    Args:
        base_path: The base Pinterest archive directory.
        db_path: Optional path to the database file.
    
    Returns:
        Dictionary with import statistics.
    """
    if db_path is None:
        db_path = get_db_path()
    
    init_db(db_path)
    
    originals_path = get_originals_path(base_path)
    html_files = get_html_files(base_path)
    
    stats = {
        "html_files_processed": 0,
        "pins_found": 0,
        "pins_imported": 0,
        "pins_skipped_duplicate": 0,
        "pins_skipped_no_file": 0,
    }
    
    conn = sqlite3.connect(db_path)
    
    try:
        for html_file in html_files:
            print(f"Processing: {html_file.name}")
            stats["html_files_processed"] += 1
            
            for parsed_pin in parse_html_file(html_file):
                stats["pins_found"] += 1
                
                if not file_exists_in_originals(originals_path, parsed_pin.file_id, parsed_pin.file_extension):
                    stats["pins_skipped_no_file"] += 1
                    continue
                
                pin = Pin(
                    pin_id=parsed_pin.pin_id,
                    file_id=parsed_pin.file_id,
                    file_extension=parsed_pin.file_extension,
                    pinterest_url=parsed_pin.pinterest_url,
                    original_url=parsed_pin.original_url,
                    source_date=parsed_pin.source_date
                )
                
                if insert_pin(conn, pin):
                    stats["pins_imported"] += 1
                else:
                    stats["pins_skipped_duplicate"] += 1
            
            conn.commit()
        
        stats["total_pins_in_db"] = get_pin_count(conn)
        
    finally:
        conn.close()
    
    return stats


def main():
    """Main entry point for the importer."""
    base_path = Path(__file__).parent.parent
    
    print("Pinterest Archive Importer")
    print("=" * 40)
    print(f"Base path: {base_path}")
    print()
    
    stats = import_pins(base_path)
    
    print()
    print("Import complete!")
    print("=" * 40)
    print(f"HTML files processed: {stats['html_files_processed']}")
    print(f"Pins found in HTML: {stats['pins_found']}")
    print(f"Pins imported: {stats['pins_imported']}")
    print(f"Pins skipped (duplicate): {stats['pins_skipped_duplicate']}")
    print(f"Pins skipped (no file): {stats['pins_skipped_no_file']}")
    print(f"Total pins in database: {stats['total_pins_in_db']}")


if __name__ == "__main__":
    main()
