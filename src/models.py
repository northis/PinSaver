"""
Database models and schema for Pinterest archive.
"""
import sqlite3
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class Pin:
    """Represents a Pinterest pin with its metadata."""
    pin_id: str
    file_id: str
    file_extension: str
    pinterest_url: str
    original_url: str
    source_date: int
    id: Optional[int] = None
    rating: int = 0


def get_db_path() -> Path:
    """Returns the path to the SQLite database."""
    return Path(__file__).parent.parent / "pinterest_archive.db"


def init_db(db_path: Optional[Path] = None) -> None:
    """
    Initialize the SQLite database with the required schema.
    
    Args:
        db_path: Optional path to the database file. Uses default if not provided.
    """
    if db_path is None:
        db_path = get_db_path()
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pin_id TEXT UNIQUE NOT NULL,
            file_id TEXT NOT NULL,
            file_extension TEXT NOT NULL DEFAULT 'jpg',
            pinterest_url TEXT NOT NULL,
            original_url TEXT NOT NULL,
            source_date INTEGER,
            rating INTEGER NOT NULL DEFAULT 0
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pin_id ON pins(pin_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_id ON pins(file_id)")
    
    # Migration: add rating column if it doesn't exist
    cursor.execute("PRAGMA table_info(pins)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'rating' not in columns:
        cursor.execute("ALTER TABLE pins ADD COLUMN rating INTEGER NOT NULL DEFAULT 0")
    
    conn.commit()
    conn.close()


def pin_exists(conn: sqlite3.Connection, pin_id: str) -> bool:
    """
    Check if a pin already exists in the database.
    
    Args:
        conn: SQLite connection.
        pin_id: The Pinterest pin ID to check.
    
    Returns:
        True if the pin exists, False otherwise.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM pins WHERE pin_id = ?", (pin_id,))
    return cursor.fetchone() is not None


def insert_pin(conn: sqlite3.Connection, pin: Pin) -> bool:
    """
    Insert a pin into the database if it doesn't already exist.
    
    Args:
        conn: SQLite connection.
        pin: The Pin object to insert.
    
    Returns:
        True if inserted, False if already exists.
    """
    if pin_exists(conn, pin.pin_id):
        return False
    
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO pins (pin_id, file_id, file_extension, pinterest_url, original_url, source_date, rating)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (pin.pin_id, pin.file_id, pin.file_extension, pin.pinterest_url, pin.original_url, pin.source_date, pin.rating))
    
    return True


def get_pin_count(conn: sqlite3.Connection) -> int:
    """
    Get the total number of pins in the database.
    
    Args:
        conn: SQLite connection.
    
    Returns:
        The number of pins.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM pins")
    return cursor.fetchone()[0]
