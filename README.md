# PinSaver - Pinterest Archive Solution

A self-hosted solution for archiving Pinterest pins with original quality images.

## Features

- **Web Interface**: Browse your archived pins with masonry layout, infinite scroll, and fullscreen carousel
- **Chrome Extension**: Save pins directly from Pinterest with one click
- **Favorites Import**: Browse your Pinterest favorites and save pins with one click via archive status icons
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

### Chrome Extension

1. Open `chrome://extensions/` in Chrome
2. Enable "Developer mode"
3. Click "Load unpacked" and select the `extension/` folder
4. Configure server URL in extension options (default: `http://localhost:8000`)
5. On any Pinterest pin page, click the "Save" button - the pin will be archived

### Saving from Favorites

1. Go to your Pinterest profile or any user's saved pins page
2. Each pin will show an archive status icon in the top-left corner:
   - **✓ (green)**: Pin is already in your archive
   - **↓ (gray)**: Pin is not archived - click to save
3. Click the icon on any unarchived pin to save it to your archive
4. The icon turns green when the pin is successfully saved

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/pins` | Get paginated pins list (params: `offset`, `limit`, `sort`) |
| POST | `/api/pins` | Add new pin (body: `pin_id`, `original_url`) |
| POST | `/api/pins/check` | Check if pins exist in archive (body: `pin_ids[]`) |
| DELETE | `/api/pins/{pin_id}` | Delete pin (param: `delete_file`) |
| GET | `/images/{filename}` | Serve archived image |

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
│       └── sw.js          # Service worker
├── extension/
│   ├── manifest.json      # Chrome extension manifest
│   ├── content.js         # Content script for Pinterest (pin pages + favorites)
│   ├── styles.css         # Notification and archive icon styles
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
