"""
FastAPI server for Pinterest archive viewer.
"""
import os
import re
import sqlite3
import time
import httpx
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from models import get_db_path, Pin, insert_pin, pin_exists

load_dotenv(Path(__file__).parent.parent / ".env")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

app = FastAPI(title="Pinterest Archive Viewer")

STATIC_PATH = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")


def is_pinterest_origin(origin: str) -> bool:
    """Check if origin is a valid Pinterest domain (any subdomain)."""
    if not origin:
        return False
    import re
    return bool(re.match(r'^https://([a-z0-9-]+\.)?pinterest\.com$', origin))


@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    """Custom CORS middleware to support all Pinterest subdomains."""
    origin = request.headers.get("origin", "")
    
    response = await call_next(request)
    
    if is_pinterest_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
    
    return response

BASE_PATH = Path(__file__).parent.parent
ORIGINALS_PATH = BASE_PATH / "originals"


class AddPinRequest(BaseModel):
    """Request model for adding a new pin."""
    pin_id: str
    original_url: str


def get_db_connection() -> sqlite3.Connection:
    """Create a database connection with row factory."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/pins")
def get_pins(
    offset: int = Query(0, ge=0, description="Number of pins to skip"),
    limit: int = Query(50, ge=1, le=100, description="Number of pins to return"),
    sort: str = Query("newest", description="Sort order: newest, oldest, or random")
):
    """
    Get paginated list of pins with configurable sort order.
    
    Args:
        offset: Number of pins to skip.
        limit: Number of pins to return (max 100).
        sort: Sort order - 'newest' (default), 'oldest', or 'random'.
    
    Returns:
        Dictionary with pins array and total count.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as total FROM pins")
    total = cursor.fetchone()["total"]
    
    if sort == "oldest":
        order_clause = "ORDER BY source_date ASC, id ASC"
    elif sort == "random":
        order_clause = "ORDER BY RANDOM()"
    else:
        order_clause = "ORDER BY source_date DESC, id DESC"
    
    cursor.execute(f"""
        SELECT id, pin_id, file_id, file_extension, pinterest_url, original_url, source_date
        FROM pins
        {order_clause}
        LIMIT ? OFFSET ?
    """, (limit, offset))
    
    pins = []
    for row in cursor.fetchall():
        pins.append({
            "id": row["id"],
            "pin_id": row["pin_id"],
            "file_id": row["file_id"],
            "file_extension": row["file_extension"],
            "pinterest_url": row["pinterest_url"],
            "original_url": row["original_url"],
            "source_date": row["source_date"],
            "image_url": f"/images/{row['file_id']}.{row['file_extension']}"
        })
    
    conn.close()
    
    return {
        "pins": pins,
        "total": total,
        "offset": offset,
        "limit": limit,
        "sort": sort,
        "has_more": offset + len(pins) < total
    }


@app.post("/api/pins")
async def add_pin(request: AddPinRequest):
    """
    Add a new pin to the archive.
    
    Downloads the original image and saves it to the originals folder,
    then adds the pin metadata to the database.
    
    Args:
        request: AddPinRequest with pin_id and original_url.
    
    Returns:
        Dictionary with status and pin info.
    """
    conn = get_db_connection()
    
    if pin_exists(conn, request.pin_id):
        conn.close()
        return {
            "status": "exists",
            "message": f"Pin {request.pin_id} already exists in archive"
        }
    
    match = re.search(r'/([a-f0-9]{32})\.(\w+)(?:\?|$)', request.original_url)
    if not match:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid original_url format")
    
    file_id = match.group(1)
    file_extension = match.group(2)
    
    file_path = ORIGINALS_PATH / f"{file_id}.{file_extension}"
    
    if not file_path.exists():
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(request.original_url)
                response.raise_for_status()
                
                file_path.write_bytes(response.content)
        except Exception as e:
            conn.close()
            raise HTTPException(status_code=500, detail=f"Failed to download image: {str(e)}")
    
    pin = Pin(
        pin_id=request.pin_id,
        file_id=file_id,
        file_extension=file_extension,
        pinterest_url=f"https://pinterest.com/pin/{request.pin_id}/",
        original_url=request.original_url,
        source_date=int(time.time())
    )
    
    insert_pin(conn, pin)
    conn.commit()
    conn.close()
    
    return {
        "status": "added",
        "message": f"Pin {request.pin_id} added to archive",
        "pin": {
            "pin_id": pin.pin_id,
            "file_id": pin.file_id,
            "file_extension": pin.file_extension
        }
    }


@app.delete("/api/pins/{pin_id}")
def delete_pin(pin_id: str, delete_file: bool = Query(False, description="Also delete the image file")):
    """
    Delete a pin from the archive.
    
    Args:
        pin_id: The Pinterest pin ID to delete.
        delete_file: If True, also delete the image file from originals folder.
    
    Returns:
        Dictionary with status and message.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT file_id, file_extension FROM pins WHERE pin_id = ?", (pin_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Pin {pin_id} not found")
    
    file_id = row["file_id"]
    file_extension = row["file_extension"]
    
    cursor.execute("DELETE FROM pins WHERE pin_id = ?", (pin_id,))
    conn.commit()
    conn.close()
    
    file_deleted = False
    if delete_file:
        file_path = ORIGINALS_PATH / f"{file_id}.{file_extension}"
        if file_path.exists():
            file_path.unlink()
            file_deleted = True
    
    return {
        "status": "deleted",
        "message": f"Pin {pin_id} deleted from archive",
        "file_deleted": file_deleted
    }


@app.get("/images/{filename}")
def get_image(filename: str):
    """
    Serve an image from the originals folder.
    
    Args:
        filename: The image filename (file_id.extension).
    
    Returns:
        The image file.
    """
    file_path = ORIGINALS_PATH / filename
    if not file_path.exists():
        return {"error": "Image not found"}, 404
    
    return FileResponse(file_path)


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the main HTML page."""
    return (STATIC_PATH / "index.html").read_text(encoding="utf-8")


@app.get("/share-handler", response_class=HTMLResponse)
def share_handler():
    """Serve the share handler page for PWA Share Target."""
    return (STATIC_PATH / "share-handler.html").read_text(encoding="utf-8")


@app.post("/share")
async def share_target(title: str = "", text: str = "", url: str = ""):
    """
    Handle PWA Share Target POST requests.
    Redirects to share-handler page with query params.
    """
    from fastapi.responses import RedirectResponse
    params = f"?title={title}&text={text}&url={url}"
    return RedirectResponse(url=f"/share-handler{params}", status_code=303)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
