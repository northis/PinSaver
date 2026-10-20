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
let showDeleted = false;

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
let swipeStartX = 0;
let swipeStartY = 0;
let swipeTracking = false;

function openCarousel(index) {
    carouselIndex = index;
    document.getElementById('carouselOverlay').classList.add('show');
    document.body.style.overflow = 'hidden';
    updateCarousel();
}

function hideCarousel() {
    document.getElementById('carouselOverlay').classList.remove('show');
    document.body.style.overflow = '';
    swipeTracking = false;
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
        const response = await fetch(`/api/pins?offset=${offset}&limit=${BATCH_SIZE}&sort=${currentSort}&deleted=${showDeleted}`);
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

    // The image opens the gallery; the pin itself is a separate link on the card
    const openBtn = document.createElement('button');
    openBtn.type = 'button';
    openBtn.className = 'pin-open';
    openBtn.title = 'View in gallery';

    const img = document.createElement('img');
    img.dataset.src = pin.image_url;
    img.alt = `Pin ${pin.pin_id}`;
    img.loading = 'lazy';

    openBtn.appendChild(img);
    openBtn.onclick = () => {
        const index = allPins.findIndex(p => p.pin_id === pin.pin_id);
        if (index > -1) openCarousel(index);
    };

    const info = document.createElement('div');
    info.className = 'pin-info';
    info.innerHTML = `
        <div class="pin-id">${pin.pin_id}</div>
        <div class="pin-date">${formatDate(pin.source_date)}</div>
    `;

    const rating = parseInt(pin.rating) || 0;
    const isDeleted = pin.is_deleted;
    const ratingBadge = document.createElement('div');
    ratingBadge.className = 'rating-badge' + (isDeleted ? ' deleted' : '');
    
    let badgeContent = rating > 0 ? `❤️ ${rating}` : '🤍';
    if (isDeleted) {
        badgeContent += ' 🚫';
    }
    ratingBadge.innerHTML = badgeContent;
    ratingBadge.title = (rating > 0 ? `Saved ${rating + 1} times` : 'Saved once') + (isDeleted ? ' • Deleted from Pinterest' : '');

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'delete-btn';
    deleteBtn.innerHTML = '✕';
    deleteBtn.title = 'Delete from archive';
    deleteBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        showDeleteModal(pin.pin_id);
    };

    const pinLink = document.createElement('a');
    pinLink.className = 'pin-link';
    pinLink.href = pin.pinterest_url;
    pinLink.target = '_blank';
    pinLink.rel = 'noopener noreferrer';
    pinLink.title = 'Open on Pinterest';
    pinLink.innerHTML = '↗';

    card.appendChild(openBtn);
    card.appendChild(ratingBadge);
    card.appendChild(deleteBtn);
    card.appendChild(pinLink);
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
        const response = await fetch(`/api/pins?offset=${offset}&limit=${BATCH_SIZE}&sort=${currentSort}&deleted=${showDeleted}`);
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
            method: 'DELETE',
            headers: { 'X-PinSaver-Request': '1' }
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

// Swipe navigation for touch screens: a horizontal drag over the image moves to the
// previous or next pin. The arrows are hidden there, so the image keeps the whole window.
const SWIPE_THRESHOLD = 60;
const SWIPE_SLOP = 12;

function swipeStart(e) {
    if (e.touches.length !== 1 || e.target.closest('button, a')) {
        swipeTracking = false;
        return;
    }
    swipeStartX = e.touches[0].clientX;
    swipeStartY = e.touches[0].clientY;
    swipeTracking = true;
}

function swipeMove(e) {
    if (!swipeTracking || e.touches.length !== 1) return;

    const dx = e.touches[0].clientX - swipeStartX;
    const dy = e.touches[0].clientY - swipeStartY;

    // A mostly horizontal drag belongs to the carousel, not to the browser's
    // back/forward gesture
    if (Math.abs(dx) > SWIPE_SLOP && Math.abs(dx) > Math.abs(dy)) {
        e.preventDefault();
    }
}

function swipeEnd(e) {
    if (!swipeTracking) return;
    swipeTracking = false;

    const touch = e.changedTouches[0];
    if (!touch) return;

    const dx = touch.clientX - swipeStartX;
    const dy = touch.clientY - swipeStartY;

    if (Math.abs(dx) < SWIPE_THRESHOLD || Math.abs(dx) <= Math.abs(dy)) return;
    if (dx < 0) {
        carouselNext();
    } else {
        carouselPrev();
    }
}

const carouselOverlay = document.getElementById('carouselOverlay');
carouselOverlay.addEventListener('touchstart', swipeStart, { passive: true });
carouselOverlay.addEventListener('touchmove', swipeMove, { passive: false });
carouselOverlay.addEventListener('touchend', swipeEnd);
carouselOverlay.addEventListener('touchcancel', () => { swipeTracking = false; });

// Close carousel on overlay click (not on the image)
carouselOverlay.addEventListener('click', (e) => {
    if (e.target.id === 'carouselOverlay' ||
        e.target.classList.contains('carousel-container') ||
        e.target.classList.contains('carousel-image-wrapper')) {
        hideCarousel();
    }
});

// The worker lives at the root: one under /static/ could only control /static/, while the
// share target posts to /share
if ('serviceWorker' in navigator) {
    const scriptOf = registration =>
        (registration.active || registration.installing || registration.waiting || {}).scriptURL || '';

    // Drop the old /static/sw.js registration: it still controls /static/* and would keep
    // serving its own cached copies of the site's files. Unregistering does not clear its
    // cache, so the entries go too.
    navigator.serviceWorker.getRegistrations().then(registrations => {
        registrations
            .filter(registration => scriptOf(registration).endsWith('/static/sw.js'))
            .forEach(registration => registration.unregister());
    }).catch(err => console.log('Service Worker cleanup failed:', err));

    if (window.caches) {
        caches.keys()
            .then(names => names.filter(name => name.startsWith('pinsaver-'))
                .forEach(name => caches.delete(name)))
            .catch(err => console.log('Cache cleanup failed:', err));
    }

    navigator.serviceWorker.register('/sw.js')
        .then(reg => console.log('Service Worker registered'))
        .catch(err => console.log('Service Worker registration failed:', err));
}

// Build badge in the header: version links to the release tag, commit to the commit
async function loadBuildInfo() {
    try {
        const response = await fetch('/api/version');
        if (!response.ok) return;
        renderBuildInfo(await response.json());
    } catch (error) {
        console.log('Build info unavailable:', error);
    }
}

function renderBuildInfo(info) {
    const badge = document.getElementById('buildBadge');
    const versionLink = document.getElementById('buildVersion');
    const commitLink = document.getElementById('buildCommit');
    const commitSep = document.getElementById('buildCommitSep');
    if (!badge || !info || !info.version) return;

    versionLink.textContent = 'v' + info.version;
    versionLink.href = info.tag_url || `${info.repo_url}/releases/tag/v${info.version}`;
    versionLink.title = `Release ${info.tag || 'v' + info.version}`;

    if (info.commit) {
        commitLink.textContent = info.short + (info.dirty ? '*' : '');
        commitLink.href = info.commit_url;
        commitLink.title = [
            `commit ${info.short}`,
            info.commit_date ? info.commit_date.slice(0, 10) : null,
            info.dirty ? 'uncommitted changes' : null
        ].filter(Boolean).join(', ');
        commitLink.hidden = false;
        commitSep.hidden = false;
    }

    badge.hidden = false;
}

loadBuildInfo();

// Sort controls
function resetGallery() {
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

function changeSort(newSort) {
    // Handle "deleted" as a filter toggle, not a sort
    if (newSort === 'deleted') {
        showDeleted = !showDeleted;
        document.querySelector('.deleted-btn').classList.toggle('active', showDeleted);
    } else {
        if (newSort === currentSort && !showDeleted) return;
        currentSort = newSort;
        showDeleted = false;
        
        // Update button states
        document.querySelectorAll('.sort-btn:not(.deleted-btn)').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.sort === newSort);
        });
        document.querySelector('.deleted-btn').classList.remove('active');
    }
    
    resetGallery();
}

document.querySelectorAll('.sort-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        changeSort(btn.dataset.sort);
    });
});

// Save a pin by pasting its link: the same resolver the phone's share sheet uses
const SAVE_LINK_MESSAGES = {
    not_a_pin_link: 'Not a pin link — paste something like https://www.pinterest.com/pin/<id>/ or https://pin.it/AbCdEf.',
    pin_not_found: 'Pinterest does not serve this pin anymore.',
    pinterest_unavailable: 'Pinterest is not answering — try again in a minute.',
    image_unavailable: 'Pinterest did not return an image for this pin.'
};

function setSaveLinkStatus(text, isError) {
    const status = document.getElementById('saveLinkStatus');
    if (!status) return;
    status.textContent = text || '';
    status.hidden = !text;
    status.classList.toggle('error', Boolean(isError));
}

async function saveLinkByUrl(event) {
    event.preventDefault();

    const input = document.getElementById('saveLinkInput');
    const button = document.getElementById('saveLinkButton');
    const url = input.value.trim();
    if (!url) return;

    button.disabled = true;
    setSaveLinkStatus('Saving…', false);

    try {
        const response = await fetch('/api/pins/resolve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-PinSaver-Request': '1' },
            body: JSON.stringify({ url })
        });
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            setSaveLinkStatus(SAVE_LINK_MESSAGES[data.detail] || 'Could not save this link.', true);
            return;
        }

        const size = data.size && data.size !== 'local' ? ` (${data.size})` : '';
        if (data.status === 'exists') {
            setSaveLinkStatus(`Already in the archive: pin ${data.pin_id}`, false);
        } else if (data.status === 'restored') {
            setSaveLinkStatus(`Restored pin ${data.pin_id} — it was marked deleted`, false);
        } else {
            setSaveLinkStatus(`Saved pin ${data.pin_id}${size}`, false);
            input.value = '';
        }

        // A new pin belongs at the top of "Newest"; other orders keep what the reader chose.
        if (currentSort === 'newest' && !showDeleted) {
            resetGallery();
        }
    } catch (error) {
        setSaveLinkStatus('Could not reach the server.', true);
    } finally {
        button.disabled = false;
    }
}

const saveLinkForm = document.getElementById('saveLinkForm');
if (saveLinkForm) {
    saveLinkForm.addEventListener('submit', saveLinkByUrl);
}
