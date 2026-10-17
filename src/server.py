"""
FastAPI server for Pinterest archive viewer.
"""
import os
import re
import sqlite3
from html import escape
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from archive import AddPinError, add_pin_from_url
from buildinfo import build_info
from models import get_db_path, get_originals_path
from pinterest import PinLookupError, extract_pin_id, resolve_pin

load_dotenv(Path(__file__).parent.parent / ".env")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

app = FastAPI(title="Pinterest Archive Viewer")

STATIC_PATH = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")

# CSS and JS links get a ?v=<version> suffix so a new release is not served
# from the browser cache
VERSIONED_ASSET_RE = re.compile(r'(["\'])(/static/[^"\']+\.(?:css|js))\1')


def is_pinterest_origin(origin: str) -> bool:
    """Check if origin is a valid Pinterest domain (any subdomain)."""
    if not origin:
        return False
    import re
    return bool(re.match(r'^https://([a-z0-9-]+\.)?pinterest\.com$', origin))


CSRF_HEADER = "X-PinSaver-Request"
DEFAULT_PORTS = (":80", ":443")


def _strip_default_port(host: str) -> str:
    """Drop a default port so `example.com` and `example.com:443` compare equal."""
    for port in DEFAULT_PORTS:
        if host.endswith(port):
            return host[: -len(port)]
    return host


def _effective_host(request: Request) -> str:
    """Host the request was addressed to: X-Forwarded-Host first (Traefik sets it)."""
    forwarded = request.headers.get("x-forwarded-host")
    host = forwarded.split(",")[0] if forwarded else (request.headers.get("host") or "")
    return _strip_default_port(host.strip().lower())


def _origin_host(origin: str) -> str | None:
    """Host of an Origin header, or None when it is not a usable URL."""
    if not origin or origin == "null":
        return None
    from urllib.parse import urlsplit

    try:
        netloc = urlsplit(origin).netloc
    except ValueError:
        return None
    return _strip_default_port(netloc.lower()) or None


def require_csrf(request: Request) -> None:
    """
    Guard every mutating request: a custom header plus a cross-site check.

    A foreign page cannot set the header (its preflight would be refused), and a
    cross-site web page always sends an http(s) Origin that does not match our host.
    Non-browser clients (curl, the extension, the service worker) send either no Origin
    or a `chrome-extension://` one, so they pass.
    """
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(
            status_code=403,
            detail="missing X-PinSaver-Request header — reload the extension"
        )

    origin = request.headers.get("origin") or ""
    if origin.startswith(("http://", "https://")) and _origin_host(origin) != _effective_host(request):
        raise HTTPException(status_code=403, detail="cross-site request rejected")


@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    """Custom CORS middleware to support all Pinterest subdomains."""
    from fastapi.responses import Response
    
    origin = request.headers.get("origin", "")
    
    # Handle preflight OPTIONS requests
    if request.method == "OPTIONS" and is_pinterest_origin(origin):
        response = Response(status_code=200)
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Access-Control-Request-Private-Network"
        response.headers["Access-Control-Max-Age"] = "86400"
        # Private Network Access (PNA) support for Chrome
        if request.headers.get("Access-Control-Request-Private-Network") == "true":
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response
    
    response = await call_next(request)
    
    if is_pinterest_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Access-Control-Request-Private-Network"
        # Private Network Access (PNA) support for Chrome
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    
    return response

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
    sort: str = Query("newest", description="Sort order: newest, oldest, top, random, or deleted"),
    deleted: bool = Query(False, description="Show only deleted pins")
):
    """
    Get paginated list of pins with configurable sort order.
    
    Args:
        offset: Number of pins to skip.
        limit: Number of pins to return (max 100).
        sort: Sort order - 'newest' (default), 'oldest', 'top', 'random', or 'deleted'.
        deleted: If True, show only deleted pins.
    
    Returns:
        Dictionary with pins array and total count.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Filter by deleted status
    if deleted:
        where_clause = "WHERE is_deleted = 1"
    else:
        where_clause = ""
    
    cursor.execute(f"SELECT COUNT(*) as total FROM pins {where_clause}")
    total = cursor.fetchone()["total"]
    
    if sort == "oldest":
        order_clause = "ORDER BY source_date ASC, id ASC"
    elif sort == "random":
        order_clause = "ORDER BY RANDOM()"
    elif sort == "top":
        order_clause = "ORDER BY rating DESC, source_date DESC, id DESC"
    else:
        order_clause = "ORDER BY source_date DESC, id DESC"
    
    cursor.execute(f"""
        SELECT id, pin_id, file_id, file_extension, pinterest_url, original_url, source_date, rating, is_deleted
        FROM pins
        {where_clause}
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
            "rating": row["rating"] or 0,
            "is_deleted": bool(row["is_deleted"]),
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


@app.get("/api/pins/sync")
def get_pins_for_sync():
    """
    Get list of all non-deleted pin IDs for syncing to Pinterest favorites.
    
    Returns:
        Dictionary with pin_ids array and total count.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT pin_id
        FROM pins
        WHERE is_deleted = 0
        ORDER BY source_date DESC, id DESC
    """)
    
    pin_ids = [row["pin_id"] for row in cursor.fetchall()]
    conn.close()
    
    return {
        "pin_ids": pin_ids,
        "total": len(pin_ids)
    }


@app.post("/api/pins")
def add_pin(request: AddPinRequest, _: None = Depends(require_csrf)):
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
    try:
        result = add_pin_from_url(conn, request.pin_id, request.original_url)
    except AddPinError as error:
        status_code = 400 if error.reason == "invalid_url" else 500
        raise HTTPException(status_code=status_code, detail=error.detail or error.reason)
    finally:
        conn.close()

    response = {"status": result.status, "message": result.message}
    if result.status == "added":
        response["pin"] = {
            "pin_id": result.pin_id,
            "file_id": result.file_id,
            "file_extension": result.file_extension
        }
    return response


class ResolvePinRequest(BaseModel):
    """Request model for saving a pin by its link."""
    url: str


#: HTTP status for every way a link can fail to resolve.
LOOKUP_STATUS = {
    "not_a_pin_link": 400,
    "pin_not_found": 404,
    "pinterest_unavailable": 502,
    "image_unavailable": 502,
}


@app.post("/api/pins/resolve")
def resolve_pin_by_link(request: ResolvePinRequest, _: None = Depends(require_csrf)):
    """
    Save a pin by its Pinterest link.

    Does exactly what the phone's share sheet does: turn the link into a pin, download the
    image and add it through the shared code path.

    Args:
        request: ResolvePinRequest with the link the user pasted or shared.

    Returns:
        Dictionary with status, pin_id, file_id, size and message.
    """
    try:
        pin_id = extract_pin_id(request.url)
        pin = resolve_pin(pin_id)
    except PinLookupError as error:
        print(f"resolve: {error.reason} ({error.detail}) for {request.url[:200]!r}", flush=True)
        raise HTTPException(status_code=LOOKUP_STATUS[error.reason], detail=error.reason)

    conn = get_db_connection()
    try:
        result = add_pin_from_url(conn, pin.pin_id, pin.image_url)
    except AddPinError as error:
        print(f"resolve: {error.reason} ({error.detail}) for pin {pin.pin_id}", flush=True)
        raise HTTPException(status_code=502, detail=error.reason)
    finally:
        conn.close()

    return {
        "status": result.status,
        "pin_id": result.pin_id,
        "file_id": result.file_id,
        "size": result.size,
        "message": result.message,
    }


class PinCheckItem(BaseModel):
    """Single pin item for batch check."""
    pin_id: str
    file_id: Optional[str] = None


class CheckPinsRequest(BaseModel):
    """Request model for checking multiple pins."""
    pins: list[PinCheckItem]


@app.post("/api/pins/check")
def check_pins_exist(request: CheckPinsRequest, _: None = Depends(require_csrf)):
    """
    Check which pins from a list already exist in the archive.
    Checks both pin_id and file_id - if either matches, pin is considered existing.
    
    Args:
        request: CheckPinsRequest with list of pins containing pin_id and file_id.
    
    Returns:
        Dictionary with existing pin IDs.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    existing = []
    for pin in request.pins:
        # Check by pin_id
        cursor.execute("SELECT 1 FROM pins WHERE pin_id = ?", (pin.pin_id,))
        if cursor.fetchone():
            existing.append(pin.pin_id)
            continue
        
        # Check by file_id
        if pin.file_id:
            cursor.execute("SELECT 1 FROM pins WHERE file_id = ?", (pin.file_id,))
            if cursor.fetchone():
                existing.append(pin.pin_id)
    
    conn.close()
    return {"existing": existing}


@app.delete("/api/pins/{pin_id}")
def delete_pin(
    pin_id: str,
    delete_file: bool = Query(False, description="Also delete the image file"),
    _: None = Depends(require_csrf)
):
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
        file_path = get_originals_path() / f"{file_id}.{file_extension}"
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

    Only a bare file name is accepted: anything with a path separator (on Windows
    `\\` counts, and `%5c` reaches the handler as an ordinary character) would let a
    request read files outside `originals/`.

    Args:
        filename: The image filename (file_id.extension).

    Returns:
        The image file.
    """
    originals_path = get_originals_path().resolve()
    file_path = (originals_path / filename).resolve()

    if Path(filename).name != filename or not file_path.is_relative_to(originals_path):
        raise HTTPException(status_code=404, detail="image not found")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="image not found")

    return FileResponse(file_path)


@app.get("/favicon.ico")
def favicon():
    """Serve the favicon."""
    return FileResponse(STATIC_PATH / "favicon.ico", media_type="image/x-icon")


@app.get("/health")
def health():
    """Health check endpoint used by the browser extension and uptime checks."""
    return {"status": "ok"}


@app.get("/api/version")
def version():
    """
    Version, commit and repository links of the running checkout.

    Shown as a badge in the site header and on the extension options page.
    """
    return build_info()


#: Copy for every outcome the share page can show. The keys are the `status` and `error`
#: parameters the service worker puts into the URL.
SHARE_STATES = {
    "not_a_pin_link": (
        "Not a pin link",
        "Share a link to a pin, for example https://www.pinterest.com/pin/<id>/."
    ),
    "pin_not_found": ("Pin not found", "Pinterest does not serve this pin anymore."),
    "pinterest_unavailable": ("Pinterest is not answering", "Try again in a minute."),
    "image_unavailable": ("Image unavailable", "Pinterest did not return an image for this pin."),
    "empty": ("Nothing to save", "The share did not contain a link."),
    "sw": ("The app has not updated", "Close and reopen the app, then share again."),
}
SHARE_START = ("PinSaver", "Share a pin from Pinterest to save it.")
SHARE_UNKNOWN_ERROR = ("Something went wrong", "Try sharing the pin again.")
SIZE_LABELS = {"local": "already on disk"}


def clean_parameter(value: Optional[str], limit: int = 64) -> str:
    """Flatten a URL parameter: no newlines, no walls of text, safe to put into the page."""
    return " ".join((value or "").split())[:limit]


def share_text(params: Mapping[str, str]) -> tuple[str, str]:
    """Heading and message for the share page, from the URL parameters alone."""
    status = clean_parameter(params.get("status"))
    error = clean_parameter(params.get("error"))
    pin = clean_parameter(params.get("pin"), 32)
    size = clean_parameter(params.get("size"), 16)

    if status == "added":
        label = SIZE_LABELS.get(size, size)
        suffix = f" ({label})" if label else ""
        return "Saved", f"Pin {pin} saved{suffix}."
    if status == "exists":
        return "Already in the archive", "Rating is now one higher."
    if status == "restored":
        return "Restored", f"Pin {pin} was deleted from Pinterest and is back in the archive."
    if error:
        return SHARE_STATES.get(error, SHARE_UNKNOWN_ERROR)
    return SHARE_START


def render_share_page(params: Mapping[str, str]) -> str:
    """
    Fill the share page template from the URL parameters.

    Every value is escaped: anyone who knows the URL can open this page with any parameters,
    and it has to stay a page that only displays text.
    """
    heading, message = share_text(params)
    html = (STATIC_PATH / "share.html").read_text(encoding="utf-8")
    return html.replace("{{heading}}", escape(heading)).replace("{{message}}", escape(message))


@app.get("/share", response_class=HTMLResponse)
def share_result(request: Request):
    """
    The share outcome page.

    Everything it shows comes from the URL, so it can be reloaded or forged without any
    effect; only the service worker produces those parameters (see `POST /share`).
    """
    return HTMLResponse(
        render_share_page(request.query_params),
        headers={"Cache-Control": "no-store"}
    )


@app.post("/share")
def share_fallback() -> RedirectResponse:
    """
    Safety net for an install whose service worker is not active yet.

    The body is never read: only the worker turns a share into an archive entry, so a plain
    POST says so and sends the browser to the outcome page.
    """
    return RedirectResponse("/share?error=sw", status_code=303)


@app.get("/sw.js")
def service_worker() -> FileResponse:
    """
    Service worker served from the root.

    An explicit route rather than `/static/sw.js`: a worker under `/static/` could only
    control `/static/`, while the share target posts to `/share`.
    """
    return FileResponse(
        STATIC_PATH / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"}
    )


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the main HTML page with cache-busted static asset URLs."""
    html = (STATIC_PATH / "index.html").read_text(encoding="utf-8")
    html = VERSIONED_ASSET_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}?v={build_info()['version']}{match.group(1)}",
        html
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
