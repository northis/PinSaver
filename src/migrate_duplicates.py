"""
Migration script to consolidate duplicate pins by file_id.
Counts duplicates, updates rating on the oldest pin, and removes newer duplicates.
"""
import sqlite3
from pathlib import Path
from models import get_db_path, init_db


def migrate_duplicates():
    """
    Find all duplicate pins by file_id, consolidate them:
    - Keep the oldest pin (by source_date)
    - Set rating = count of duplicates - 1
    - Delete newer duplicates
    """
    # First ensure rating column exists
    init_db()
    
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Find all file_ids that have duplicates
    cursor.execute("""
        SELECT file_id, COUNT(*) as cnt
        FROM pins
        GROUP BY file_id
        HAVING cnt > 1
    """)
    
    duplicates = cursor.fetchall()
    
    if not duplicates:
        print("No duplicates found.")
        conn.close()
        return
    
    print(f"Found {len(duplicates)} file_ids with duplicates")
    
    total_deleted = 0
    total_rating_added = 0
    
    for dup in duplicates:
        file_id = dup['file_id']
        count = dup['cnt']
        
        # Get all pins with this file_id, ordered by source_date (oldest first)
        cursor.execute("""
            SELECT id, pin_id, source_date, rating
            FROM pins
            WHERE file_id = ?
            ORDER BY source_date ASC, id ASC
        """, (file_id,))
        
        pins = cursor.fetchall()
        
        # Keep the first (oldest) pin
        oldest_pin = pins[0]
        duplicates_to_delete = pins[1:]
        
        # Calculate new rating: existing rating + number of duplicates
        new_rating = oldest_pin['rating'] + len(duplicates_to_delete)
        
        # Update rating on oldest pin
        cursor.execute("""
            UPDATE pins SET rating = ? WHERE id = ?
        """, (new_rating, oldest_pin['id']))
        
        # Delete newer duplicates
        for dup_pin in duplicates_to_delete:
            cursor.execute("DELETE FROM pins WHERE id = ?", (dup_pin['id'],))
            print(f"  Deleted duplicate pin {dup_pin['pin_id']} (file_id: {file_id[:8]}...)")
        
        print(f"Consolidated file_id {file_id[:8]}...: kept pin {oldest_pin['pin_id']}, rating={new_rating}, deleted {len(duplicates_to_delete)} duplicates")
        
        total_deleted += len(duplicates_to_delete)
        total_rating_added += len(duplicates_to_delete)
    
    conn.commit()
    conn.close()
    
    print(f"\nMigration complete:")
    print(f"  - Deleted {total_deleted} duplicate pins")
    print(f"  - Added {total_rating_added} total rating points")


if __name__ == "__main__":
    migrate_duplicates()
