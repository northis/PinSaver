# PinSaver - Pinterest Archive Solution

A self-hosted solution for archiving Pinterest pins with original quality images.

## Features

- **Web Interface**: Browse your archived pins with masonry layout, infinite scroll, and fullscreen carousel
- **Chrome Extension**: Save pins directly from Pinterest with one click
- **PWA with Share Target**: Share pins from mobile Pinterest app to save them
- **Sorting**: View pins by newest, oldest, or random order
- **Delete Management**: Remove pins from archive with optional file deletion

## Requirements

- Python 3.8+
- Chrome browser (for extension)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/northis/PinSaver.git
cd PinSaver
```

### 2. Install Python dependencies

```bash
pip install fastapi uvicorn httpx pillow
```

### 3. Initialize the database

```bash
python src/models.py
```

This creates `pins.db` SQLite database and `originals/` folder for images.

### 4. Start the server

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

### Chrome Extension

1. Open `chrome://extensions/` in Chrome
2. Enable "Developer mode"
3. Click "Load unpacked" and select the `extension/` folder
4. Configure server URL in extension options (default: `http://localhost:8000`)
5. On any Pinterest pin page, click the "Save" button - the pin will be archived

### PWA (Mobile)

1. Open `http://<your-server-ip>:8000` on your mobile device
2. Add to home screen (Chrome menu → "Add to Home screen")
3. From Pinterest app, share any pin → select "PinSaver"
4. Pin will be automatically saved to your archive

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/pins` | Get paginated pins list (params: `offset`, `limit`, `sort`) |
| POST | `/api/pins` | Add new pin (body: `pin_id`, `original_url`) |
| DELETE | `/api/pins/{pin_id}` | Delete pin (param: `delete_file`) |
| GET | `/images/{filename}` | Serve archived image |

## Project Structure

```
PinSaver/
├── src/
│   ├── server.py          # FastAPI server
│   ├── models.py          # Database models
│   └── static/
│       ├── index.html     # Main web interface
│       ├── styles.css     # Styles
│       ├── app.js         # Frontend logic
│       ├── manifest.json  # PWA manifest
│       ├── sw.js          # Service worker
│       └── share-handler.html  # PWA share target handler
├── extension/
│   ├── manifest.json      # Chrome extension manifest
│   ├── content.js         # Content script for Pinterest
│   ├── styles.css         # Notification styles
│   ├── options.html       # Extension options page
│   └── options.js         # Options logic
├── originals/             # Archived images storage
├── pins.db                # SQLite database
└── README.md
```

## Network Access

To access from other devices on your network:

1. Find your computer's local IP address
2. Access `http://<your-ip>:8000` from other devices
3. For PWA Share Target to work on Android, you may need HTTPS (use a reverse proxy like nginx)

## License

MIT
