"""Generate simple PNG icons for the extension."""
from PIL import Image, ImageDraw

def create_icon(size, filename):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Red circle
    margin = size // 10
    draw.ellipse([margin, margin, size - margin, size - margin], fill='#e60023')
    
    # White "P" shape (simplified)
    center = size // 2
    r = size // 3
    draw.ellipse([center - r//2, center - r, center + r, center], fill='white')
    draw.rectangle([center - r//2, center - r//2, center, center + r], fill='white')
    draw.ellipse([center - r//4, center - r//2, center + r//2, center - r//4], fill='#e60023')
    
    img.save(filename, 'PNG')

create_icon(48, 'icon48.png')
create_icon(128, 'icon128.png')
print('Icons created!')
