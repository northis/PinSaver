"""
Script to check Pinterest pin URLs and mark deleted ones.
Uses headless Chromium via Playwright to get real page status.
"""
import sqlite3
import asyncio
from playwright.async_api import async_playwright
from models import get_db_path, init_db


async def check_pin_deleted(page, pinterest_url: str) -> bool:
    """
    Check if a pin is deleted by navigating to it with headless browser.
    
    Args:
        page: Playwright page instance.
        pinterest_url: Pinterest URL to check.
    
    Returns:
        True if pin is deleted (page shows error or redirect), False otherwise.
    """
    try:
        response = await page.goto(pinterest_url, wait_until='networkidle', timeout=30000)
        
        # Check for 404 or error status
        if response and response.status >= 400:
            return True
        
        # Wait for any remaining redirects to complete
        await page.wait_for_load_state('networkidle')
        
        # Check if redirected away from pin page (deleted pins redirect to home)
        current_url = page.url
        if '/pin/' not in current_url:
            return True
        
        # Check for "Pin not found" or similar error messages on page
        content = await page.content()
        if 'Sorry! This Pin was deleted' in content or 'This Pin has been removed' in content:
            return True
        
        return False
    except Exception as e:
        print(f"  Error checking {pinterest_url}: {e}")
        return False


async def update_deleted_pins():
    """
    Check all pins that are not marked as deleted and update their status.
    """
    init_db()
    
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all pins not yet marked as deleted
    cursor.execute("""
        SELECT id, pin_id, pinterest_url
        FROM pins
        WHERE is_deleted = 0
        ORDER BY id
    """)
    
    pins = cursor.fetchall()
    
    if not pins:
        print("No pins to check.")
        conn.close()
        return
    
    print(f"Checking {len(pins)} pins...")
    
    deleted_count = 0
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()
        
        for i, pin in enumerate(pins):                
            is_deleted = await check_pin_deleted(page, pin['pinterest_url'])
            
            if is_deleted:
                cursor.execute(
                    "UPDATE pins SET is_deleted = 1 WHERE id = ?",
                    (pin['id'],)
                )
                deleted_count += 1
                print(f"[{i+1}/{len(pins)}] Pin {pin['pin_id']} - DELETED")
            else:
                print(f"[{i+1}/{len(pins)}] Pin {pin['pin_id']} - OK")
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.1)
        
        await browser.close()
    
    conn.commit()
    conn.close()
    
    print(f"\nCheck complete:")
    print(f"  - Checked: {len(pins)} pins")
    print(f"  - Marked as deleted: {deleted_count}")


if __name__ == "__main__":
    asyncio.run(update_deleted_pins())
