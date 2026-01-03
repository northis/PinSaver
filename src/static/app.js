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
let currentSort = 'newest';

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

// Carousel functionality (defined early for use in createPinCard)
let carouselIndex = 0;
let carouselLoading = false;

function openCarousel(index) {
    carouselIndex = index;
    document.getElementById('carouselOverlay').classList.add('show');
    document.body.style.overflow = 'hidden';
    updateCarousel();
}

function hideCarousel() {
    document.getElementById('carouselOverlay').classList.remove('show');
    document.body.style.overflow = '';
}

function updateCarousel() {
    const pin = allPins[carouselIndex];
    if (!pin) return;

    const img = document.getElementById('carouselImage');
    const counter = document.getElementById('carouselCounter');
    const link = document.getElementById('carouselLink');
    const prevBtn = document.getElementById('carouselPrev');
    const nextBtn = document.getElementById('carouselNext');

    img.classList.remove('loaded');
    img.src = pin.image_url;
    img.onload = () => img.classList.add('loaded');

    counter.textContent = `${carouselIndex + 1} / ${totalPins}`;
    link.href = pin.pinterest_url;

    prevBtn.disabled = carouselIndex === 0;
    nextBtn.disabled = false;

    // Preload next image
    if (carouselIndex < allPins.length - 1) {
        const nextImg = new Image();
        nextImg.src = allPins[carouselIndex + 1].image_url;
    }

    // Load more pins if near the end
    if (carouselIndex >= allPins.length - 3 && hasMore && !carouselLoading) {
        loadMoreForCarousel();
    }
}

async function loadMoreForCarousel() {
    if (carouselLoading || !hasMore) return;
    carouselLoading = true;

    try {
        const response = await fetch(`/api/pins?offset=${offset}&limit=${BATCH_SIZE}&sort=${currentSort}`);
        const data = await response.json();

        totalPins = data.total;
        hasMore = data.has_more;
        offset += data.pins.length;

        allPins.push(...data.pins);
        statsEl.textContent = `${allPins.length} of ${totalPins} pins loaded`;

        // Update counter
        document.getElementById('carouselCounter').textContent = `${carouselIndex + 1} / ${totalPins}`;

        // Also render new pins in masonry
        layoutPins();
    } catch (error) {
        console.error('Error loading more pins:', error);
    } finally {
        carouselLoading = false;
    }
}

function carouselPrev() {
    if (carouselIndex > 0) {
        carouselIndex--;
        updateCarousel();
    }
}

function carouselNext() {
    if (carouselIndex < allPins.length - 1) {
        carouselIndex++;
        updateCarousel();
    } else if (hasMore) {
        loadMoreForCarousel().then(() => {
            if (carouselIndex < allPins.length - 1) {
                carouselIndex++;
                updateCarousel();
            }
        });
    }
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

    const viewBtn = document.createElement('button');
    viewBtn.className = 'view-btn';
    viewBtn.innerHTML = '⛶';
    viewBtn.title = 'View fullscreen';
    viewBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const index = allPins.findIndex(p => p.pin_id === pin.pin_id);
        if (index > -1) openCarousel(index);
    };

    link.appendChild(img);
    card.appendChild(link);
    card.appendChild(deleteBtn);
    card.appendChild(viewBtn);
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
        const response = await fetch(`/api/pins?offset=${offset}&limit=${BATCH_SIZE}&sort=${currentSort}`);
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
        hideCarousel();
    }
});

// Carousel keyboard navigation
document.addEventListener('keydown', (e) => {
    if (!document.getElementById('carouselOverlay').classList.contains('show')) return;
    
    if (e.key === 'ArrowLeft') {
        carouselPrev();
    } else if (e.key === 'ArrowRight') {
        carouselNext();
    }
});

// Close carousel on overlay click (not on image)
document.getElementById('carouselOverlay').addEventListener('click', (e) => {
    if (e.target.id === 'carouselOverlay' || e.target.classList.contains('carousel-container')) {
        hideCarousel();
    }
});

// Register service worker for PWA
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js')
        .then(reg => console.log('Service Worker registered'))
        .catch(err => console.log('Service Worker registration failed:', err));
}

// Sort controls
function changeSort(newSort) {
    if (newSort === currentSort) return;
    
    currentSort = newSort;
    
    // Update button states
    document.querySelectorAll('.sort-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.sort === newSort);
    });
    
    // Reset and reload
    allPins = [];
    offset = 0;
    hasMore = true;
    renderedCount = 0;
    columns = 0;
    columnHeights = [];
    imageHeights.clear();
    masonry.innerHTML = '';
    
    loadPins();
}

document.querySelectorAll('.sort-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        changeSort(btn.dataset.sort);
    });
});
