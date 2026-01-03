"""
FastAPI server for Pinterest archive viewer.
"""
import re
import sqlite3
import time
import httpx
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from models import get_db_path, Pin, insert_pin, pin_exists

app = FastAPI(title="Pinterest Archive Viewer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://pinterest.com", "https://www.pinterest.com", "https://ru.pinterest.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    limit: int = Query(50, ge=1, le=100, description="Number of pins to return")
):
    """
    Get paginated list of pins, ordered by newest first (by id descending).
    
    Args:
        offset: Number of pins to skip.
        limit: Number of pins to return (max 100).
    
    Returns:
        Dictionary with pins array and total count.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as total FROM pins")
    total = cursor.fetchone()["total"]
    
    cursor.execute("""
        SELECT id, pin_id, file_id, file_extension, pinterest_url, original_url, source_date
        FROM pins
        ORDER BY id DESC
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
    return HTML_TEMPLATE


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pinterest Archive</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background-color: #f0f0f0;
            min-height: 100vh;
        }

        header {
            background: #e60023;
            color: white;
            padding: 16px 24px;
            position: sticky;
            top: 0;
            z-index: 1000;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            transition: transform 0.3s ease;
        }

        header.hidden {
            transform: translateY(-100%);
        }

        header h1 {
            font-size: 24px;
            font-weight: 600;
        }

        .stats {
            font-size: 14px;
            opacity: 0.9;
            margin-top: 4px;
        }

        .container {
            padding: 16px;
            max-width: 2400px;
            margin: 0 auto;
        }

        .masonry {
            position: relative;
            width: 100%;
        }

        .pin-card {
            position: absolute;
            background: white;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 1px 4px rgba(0,0,0,0.1);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
            cursor: pointer;
        }

        .pin-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.15);
        }

        .pin-card a {
            display: block;
            text-decoration: none;
            color: inherit;
        }

        .pin-card img {
            width: 100%;
            display: block;
            background: #e0e0e0;
        }

        .pin-info {
            padding: 8px 12px;
            font-size: 12px;
            color: #666;
            border-top: 1px solid #f0f0f0;
        }

        .pin-info .pin-id {
            font-weight: 500;
            color: #333;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .pin-info .pin-date {
            margin-top: 2px;
            color: #999;
        }

        .pin-card .delete-btn {
            position: absolute;
            top: 8px;
            right: 8px;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background: rgba(0, 0, 0, 0.6);
            color: white;
            border: none;
            cursor: pointer;
            font-size: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0;
            transition: opacity 0.2s, background 0.2s;
            z-index: 10;
        }

        .pin-card:hover .delete-btn {
            opacity: 1;
        }

        .pin-card .delete-btn:hover {
            background: #e60023;
        }

        /* Modal styles */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 2000;
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.2s, visibility 0.2s;
        }

        .modal-overlay.show {
            opacity: 1;
            visibility: visible;
        }

        .modal {
            background: white;
            border-radius: 16px;
            padding: 24px;
            max-width: 400px;
            width: 90%;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
            transform: scale(0.9);
            transition: transform 0.2s;
        }

        .modal-overlay.show .modal {
            transform: scale(1);
        }

        .modal h3 {
            margin-bottom: 12px;
            font-size: 18px;
        }

        .modal p {
            color: #666;
            margin-bottom: 8px;
            font-size: 14px;
        }

        .modal-checkbox {
            display: flex;
            align-items: center;
            gap: 8px;
            margin: 16px 0;
            font-size: 14px;
            color: #333;
        }

        .modal-checkbox input {
            width: 18px;
            height: 18px;
        }

        .modal-buttons {
            display: flex;
            gap: 12px;
            justify-content: flex-end;
            margin-top: 20px;
        }

        .modal-btn {
            padding: 10px 20px;
            border-radius: 24px;
            border: none;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: background 0.2s;
        }

        .modal-btn-cancel {
            background: #e0e0e0;
            color: #333;
        }

        .modal-btn-cancel:hover {
            background: #d0d0d0;
        }

        .modal-btn-delete {
            background: #e60023;
            color: white;
        }

        .modal-btn-delete:hover {
            background: #c4001d;
        }

        .loading {
            text-align: center;
            padding: 40px;
            color: #666;
        }

        .loading-spinner {
            width: 40px;
            height: 40px;
            border: 3px solid #f0f0f0;
            border-top-color: #e60023;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 16px;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .sentinel {
            height: 1px;
            width: 100%;
        }

        /* Responsive column widths */
        @media (max-width: 600px) {
            .container { padding: 8px; }
            header { padding: 12px 16px; }
            header h1 { font-size: 20px; }
        }
    </style>
</head>
<body>
    <header>
        <h1>📌 Pinterest Archive</h1>
        <div class="stats" id="stats">Loading...</div>
    </header>

    <div class="container">
        <div class="masonry" id="masonry"></div>
        <div class="sentinel" id="sentinel"></div>
        <div class="loading" id="loading">
            <div class="loading-spinner"></div>
            <div>Loading pins...</div>
        </div>
    </div>

    <script>
        const BATCH_SIZE = 50;
        const GAP = 16;
        const MIN_COL_WIDTH = 236;

        let allPins = [];
        let offset = 0;
        let loading = false;
        let hasMore = true;
        let totalPins = 0;
        let columns = 0;
        let columnHeights = [];
        let renderedCount = 0;
        let imageHeights = new Map();

        const masonry = document.getElementById('masonry');
        const sentinel = document.getElementById('sentinel');
        const loadingEl = document.getElementById('loading');
        const statsEl = document.getElementById('stats');

        function getColumnCount() {
            const containerWidth = masonry.parentElement.clientWidth;
            return Math.max(2, Math.floor((containerWidth + GAP) / (MIN_COL_WIDTH + GAP)));
        }

        function getColumnWidth() {
            const containerWidth = masonry.parentElement.clientWidth;
            const cols = getColumnCount();
            return (containerWidth - (cols - 1) * GAP) / cols;
        }

        function formatDate(timestamp) {
            if (!timestamp) return '';
            const date = new Date(timestamp * 1000);
            return date.toLocaleDateString('en-US', { 
                year: 'numeric', 
                month: 'short', 
                day: 'numeric' 
            });
        }

        function getShortestColumn() {
            let minHeight = Infinity;
            let minIndex = 0;
            for (let i = 0; i < columnHeights.length; i++) {
                if (columnHeights[i] < minHeight) {
                    minHeight = columnHeights[i];
                    minIndex = i;
                }
            }
            return minIndex;
        }

        function createPinCard(pin, colWidth) {
            const card = document.createElement('div');
            card.className = 'pin-card';
            card.dataset.pinId = pin.pin_id;
            card.style.width = colWidth + 'px';

            const link = document.createElement('a');
            link.href = pin.pinterest_url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';

            const img = document.createElement('img');
            img.dataset.src = pin.image_url;
            img.alt = `Pin ${pin.pin_id}`;
            img.loading = 'lazy';

            const info = document.createElement('div');
            info.className = 'pin-info';
            info.innerHTML = `
                <div class="pin-id">${pin.pin_id}</div>
                <div class="pin-date">${formatDate(pin.source_date)}</div>
            `;

            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'delete-btn';
            deleteBtn.innerHTML = '✕';
            deleteBtn.title = 'Delete from archive';
            deleteBtn.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                showDeleteModal(pin.pin_id);
            };

            link.appendChild(img);
            card.appendChild(link);
            card.appendChild(deleteBtn);
            card.appendChild(info);

            return card;
        }

        function layoutPins() {
            const newColCount = getColumnCount();
            const colWidth = getColumnWidth();

            if (newColCount !== columns || renderedCount === 0) {
                columns = newColCount;
                columnHeights = new Array(columns).fill(0);
                renderedCount = 0;
                masonry.innerHTML = '';
            }

            const fragment = document.createDocumentFragment();

            for (let i = renderedCount; i < allPins.length; i++) {
                const pin = allPins[i];
                const card = createPinCard(pin, colWidth);
                
                const colIndex = getShortestColumn();
                const x = colIndex * (colWidth + GAP);
                const y = columnHeights[colIndex];

                card.style.transform = `translate(${x}px, ${y}px)`;
                card.style.opacity = '0';

                fragment.appendChild(card);

                const estimatedHeight = colWidth * 1.3 + 50;
                columnHeights[colIndex] += estimatedHeight + GAP;

                const img = card.querySelector('img');
                const cardRef = card;
                const pinIndex = i;
                
                img.onload = function() {
                    const actualHeight = this.naturalHeight * (colWidth / this.naturalWidth);
                    imageHeights.set(pin.pin_id, actualHeight);
                    relayoutSingleCard(cardRef, pinIndex, actualHeight + 50);
                };
                
                img.src = img.dataset.src;
                
                setTimeout(() => {
                    cardRef.style.transition = 'opacity 0.3s ease';
                    cardRef.style.opacity = '1';
                }, 50 + (i - renderedCount) * 20);
            }

            masonry.appendChild(fragment);
            renderedCount = allPins.length;
            
            const maxHeight = Math.max(...columnHeights);
            masonry.style.height = maxHeight + 'px';
        }

        function relayoutSingleCard(card, index, actualCardHeight) {
            const colWidth = getColumnWidth();
            
            columnHeights = new Array(columns).fill(0);
            
            const cards = masonry.querySelectorAll('.pin-card');
            cards.forEach((c, i) => {
                const pin = allPins[i];
                const height = imageHeights.get(pin.pin_id) || colWidth * 1.3;
                const cardHeight = height + 50;
                
                const colIndex = getShortestColumn();
                const x = colIndex * (colWidth + GAP);
                const y = columnHeights[colIndex];
                
                c.style.transform = `translate(${x}px, ${y}px)`;
                columnHeights[colIndex] += cardHeight + GAP;
            });
            
            const maxHeight = Math.max(...columnHeights);
            masonry.style.height = maxHeight + 'px';
        }

        function fullRelayout() {
            const colWidth = getColumnWidth();
            columns = getColumnCount();
            columnHeights = new Array(columns).fill(0);
            
            const cards = masonry.querySelectorAll('.pin-card');
            cards.forEach((c, i) => {
                const pin = allPins[i];
                const height = imageHeights.get(pin.pin_id) || colWidth * 1.3;
                const cardHeight = height + 50;
                
                c.style.width = colWidth + 'px';
                
                const colIndex = getShortestColumn();
                const x = colIndex * (colWidth + GAP);
                const y = columnHeights[colIndex];
                
                c.style.transform = `translate(${x}px, ${y}px)`;
                columnHeights[colIndex] += cardHeight + GAP;
            });
            
            const maxHeight = Math.max(...columnHeights);
            masonry.style.height = maxHeight + 'px';
        }

        async function loadPins() {
            if (loading || !hasMore) return;
            
            loading = true;
            loadingEl.style.display = 'block';

            try {
                const response = await fetch(`/api/pins?offset=${offset}&limit=${BATCH_SIZE}`);
                const data = await response.json();
                
                totalPins = data.total;
                hasMore = data.has_more;
                offset += data.pins.length;
                
                allPins.push(...data.pins);
                
                statsEl.textContent = `${allPins.length} of ${totalPins} pins loaded`;
                
                layoutPins();
                
            } catch (error) {
                console.error('Error loading pins:', error);
            } finally {
                loading = false;
                loadingEl.style.display = hasMore ? 'none' : 'none';
            }
        }

        const observer = new IntersectionObserver((entries) => {
            if (entries[0].isIntersecting && !loading && hasMore) {
                loadPins();
            }
        }, { rootMargin: '500px' });

        observer.observe(sentinel);

        let resizeTimeout;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(fullRelayout, 150);
        });

        // Header hide/show on scroll
        const header = document.querySelector('header');
        let lastScrollY = window.scrollY;
        let ticking = false;

        function updateHeader() {
            const currentScrollY = window.scrollY;
            
            if (currentScrollY > lastScrollY && currentScrollY > 80) {
                header.classList.add('hidden');
            } else {
                header.classList.remove('hidden');
            }
            
            lastScrollY = currentScrollY;
            ticking = false;
        }

        window.addEventListener('scroll', () => {
            if (!ticking) {
                requestAnimationFrame(updateHeader);
                ticking = true;
            }
        }, { passive: true });

        loadPins();

        // Delete modal functionality
        let pinToDelete = null;

        function showDeleteModal(pinId) {
            pinToDelete = pinId;
            document.getElementById('deletePinId').textContent = pinId;
            document.getElementById('deleteFileCheckbox').checked = false;
            document.getElementById('deleteModal').classList.add('show');
        }

        function hideDeleteModal() {
            document.getElementById('deleteModal').classList.remove('show');
            pinToDelete = null;
        }

        async function confirmDelete() {
            if (!pinToDelete) return;

            const deleteFile = document.getElementById('deleteFileCheckbox').checked;
            const pinId = pinToDelete;

            try {
                const response = await fetch(`/api/pins/${pinId}?delete_file=${deleteFile}`, {
                    method: 'DELETE'
                });

                if (!response.ok) {
                    throw new Error('Failed to delete pin');
                }

                // Remove card from DOM
                const card = document.querySelector(`.pin-card[data-pin-id="${pinId}"]`);
                if (card) {
                    card.style.transition = 'opacity 0.3s, transform 0.3s';
                    card.style.opacity = '0';
                    card.style.transform += ' scale(0.8)';
                    setTimeout(() => {
                        card.remove();
                        // Update allPins array
                        const index = allPins.findIndex(p => p.pin_id === pinId);
                        if (index > -1) {
                            allPins.splice(index, 1);
                            totalPins--;
                            renderedCount--;
                            statsEl.textContent = `${allPins.length} of ${totalPins} pins loaded`;
                        }
                        fullRelayout();
                    }, 300);
                }

                hideDeleteModal();
            } catch (error) {
                console.error('Error deleting pin:', error);
                alert('Failed to delete pin: ' + error.message);
            }
        }

        // Close modal on overlay click
        document.getElementById('deleteModal').addEventListener('click', (e) => {
            if (e.target.id === 'deleteModal') {
                hideDeleteModal();
            }
        });

        // Close modal on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                hideDeleteModal();
            }
        });
    </script>

    <!-- Delete confirmation modal -->
    <div class="modal-overlay" id="deleteModal">
        <div class="modal">
            <h3>Delete Pin?</h3>
            <p>Are you sure you want to delete pin <strong id="deletePinId"></strong> from the archive?</p>
            <label class="modal-checkbox">
                <input type="checkbox" id="deleteFileCheckbox">
                Also delete the image file
            </label>
            <div class="modal-buttons">
                <button class="modal-btn modal-btn-cancel" onclick="hideDeleteModal()">Cancel</button>
                <button class="modal-btn modal-btn-delete" onclick="confirmDelete()">Delete</button>
            </div>
        </div>
    </div>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
