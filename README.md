# PinSaver - Pinterest Archive Solution

A self-hosted solution for archiving Pinterest pins with original quality images.

## Features

- **Web Interface**: Browse your archived pins with masonry layout, infinite scroll, and fullscreen carousel
- **Chrome Extension**: Save pins directly from Pinterest with one click
- **Manual Add Page**: Add pins by pasting URL - works on Android over HTTP
- **Sorting**: View pins by newest, oldest, or random order
- **Delete Management**: Remove pins from archive with optional file deletion

## Requirements

- Python 3.10+
- Chrome browser (for extension)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/northis/PinSaver.git
cd PinSaver
```

### 2. Install Python dependencies

```bash
pip install -r src/requirements.txt
```

### 3. Configure environment

Copy the example environment file and adjust if needed:

```bash
cp .env.example .env
```

Edit `.env` to configure:

```env
HOST=0.0.0.0
PORT=8000
```

### 4. Initialize the database

```bash
python src/models.py
```

This creates `pins.db` SQLite database and `originals/` folder for images.

### 5. Start the server

```bash
python src/server.py
```

Server runs on `http://localhost:8000` by default.

## Usage

### Web Interface

Open `http://localhost:8000` in your browser to view archived pins.

- **Sort controls**: Switch between Newest, Oldest, and Random order
- **Carousel**: Click any pin to view in fullscreen with navigation
- **Delete**: Hover over a pin and click the X button to delete
- **Add Pin**: Click "+ Add" button to manually add pins by URL

### Chrome Extension

1. Open `chrome://extensions/` in Chrome
2. Enable "Developer mode"
3. Click "Load unpacked" and select the `extension/` folder
4. Configure server URL in extension options (default: `http://localhost:8000`)
5. On any Pinterest pin page, click the "Save" button - the pin will be archived

### PWA (Mobile) - requires HTTPS

1. Open `https://<your-server>:8000` on your mobile device (requires HTTPS)
2. Add to home screen (Chrome menu → "Add to Home screen")
3. From Pinterest app, share any pin → select "PinSaver"
4. Pin will be automatically saved to your archive

**Note**: Share Target requires HTTPS. For local network use, consider ngrok or a reverse proxy with SSL.

### Manual Add (Mobile) - works over HTTP

If you can't use HTTPS, use the manual add page:

1. Open `http://<your-server-ip>:8000/add` on your mobile device
2. In Pinterest app, tap Share → Copy link
3. Go to the Add page - URL will auto-paste from clipboard
4. Tap "Save Pin"

Supported URL formats:
- `https://pin.it/abc123` (short links)
- `https://pinterest.com/pin/123456/`
- `https://www.pinterest.com/pin/123456/`

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/pins` | Get paginated pins list (params: `offset`, `limit`, `sort`) |
| POST | `/api/pins` | Add new pin (body: `pin_id`, `original_url`) |
| POST | `/api/pins/from-url` | Add pin from URL (body: `url`) - resolves short links |
| DELETE | `/api/pins/{pin_id}` | Delete pin (param: `delete_file`) |
| GET | `/images/{filename}` | Serve archived image |
| GET | `/add` | Manual pin add page |

## Project Structure

```
PinSaver/
├── src/
│   ├── server.py          # FastAPI server
│   ├── models.py          # Database models
│   ├── requirements.txt   # Python dependencies
│   └── static/
│       ├── index.html     # Main web interface
│       ├── styles.css     # Styles
│       ├── app.js         # Frontend logic
│       ├── manifest.json  # PWA manifest
│       ├── sw.js          # Service worker
│       └── add.html       # Manual pin add page
├── extension/
│   ├── manifest.json      # Chrome extension manifest
│   ├── content.js         # Content script for Pinterest
│   ├── styles.css         # Notification styles
│   ├── options.html       # Extension options page
│   └── options.js         # Options logic
├── originals/             # Archived images storage
├── pins.db                # SQLite database
├── .env                   # Environment configuration (create from .env.example)
├── .env.example           # Example environment file
└── README.md
```

## Network Access

To access from other devices on your network:

1. Find your computer's local IP address
2. Access `http://<your-ip>:8000` from other devices

## License

MIT
