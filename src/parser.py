"""
HTML parser for extracting Pinterest pin data from saved HTML files.
"""
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass
class ParsedPin:
    """Represents a parsed pin from HTML."""
    pin_id: str
    file_id: str
    file_extension: str
    pinterest_url: str
    original_url: str
    source_date: int


def extract_file_id_from_url(url: str) -> tuple[str, str] | None:
    """
    Extract file ID and extension from a Pinterest image URL.
    
    Args:
        url: The image URL like https://i.pinimg.com/originals/7d/76/f6/7d76f602472b7acfb27cdbf4dae02489.jpg
    
    Returns:
        Tuple of (file_id, extension) or None if not found.
    """
    match = re.search(r'/originals/[a-f0-9]{2}/[a-f0-9]{2}/[a-f0-9]{2}/([a-f0-9]{32})\.(\w+)', url)
    if match:
        return match.group(1), match.group(2)
    return None


def extract_pin_id_from_url(url: str) -> str | None:
    """
    Extract pin ID from a Pinterest URL.
    
    Args:
        url: The Pinterest URL like https://ru.pinterest.com/pin/732820170659102435/
    
    Returns:
        The pin ID or None if not found.
    """
    match = re.search(r'/pin/(\d+)/?', url)
    if match:
        return match.group(1)
    return None


def date_string_to_timestamp(date_str: str) -> int:
    """
    Convert a date string (YYYYMMDD) to Unix timestamp (UTC).
    
    Args:
        date_str: Date string in format YYYYMMDD (e.g., '20260102').
    
    Returns:
        Unix timestamp as integer.
    """
    dt = datetime.strptime(date_str, '%Y%m%d').replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def parse_html_file(html_path: Path, source_date: int | None = None) -> Generator[ParsedPin, None, None]:
    """
    Parse a Pinterest HTML file and extract all pins with their image data.
    
    Pins are yielded in reverse order (oldest first) to maintain chronological order
    when importing from multiple overlapping HTML saves.
    
    Args:
        html_path: Path to the HTML file.
        source_date: Unix timestamp (UTC). If None, extracted from parent folder name.
    
    Yields:
        ParsedPin objects for each pin found.
    """
    if source_date is None:
        source_date = date_string_to_timestamp(html_path.parent.name)
    
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    soup = BeautifulSoup(content, 'lxml')
    
    pins_data = []
    
    for element in soup.find_all(attrs={'data-test-pin-id': True}):
        pin_id = element.get('data-test-pin-id')
        if not pin_id:
            continue
        
        img = element.find('img', srcset=True)
        if not img:
            continue
        
        srcset = img.get('srcset', '')
        
        file_info = None
        for part in srcset.split(','):
            part = part.strip()
            if '/originals/' in part:
                url = part.split()[0]
                file_info = extract_file_id_from_url(url)
                if file_info:
                    original_url = url
                    break
        
        if not file_info:
            continue
        
        file_id, file_extension = file_info
        pinterest_url = f"https://pinterest.com/pin/{pin_id}/"
        
        pins_data.append(ParsedPin(
            pin_id=pin_id,
            file_id=file_id,
            file_extension=file_extension,
            pinterest_url=pinterest_url,
            original_url=original_url,
            source_date=source_date
        ))
    
    for pin in reversed(pins_data):
        yield pin


def get_html_files(base_path: Path) -> list[Path]:
    """
    Get all HTML files from date folders, sorted by date (oldest first).
    
    Args:
        base_path: The base Pinterest archive directory.
    
    Returns:
        List of HTML file paths sorted by date (oldest first).
    """
    html_files = []
    
    for folder in sorted(base_path.iterdir()):
        if not folder.is_dir():
            continue
        if folder.name == 'originals' or folder.name == 'src':
            continue
        if not re.match(r'^\d{8}$', folder.name):
            continue
        
        for html_file in folder.glob('*.html'):
            html_files.append(html_file)
    
    html_files.sort(key=lambda p: p.parent.name)
    
    return html_files
