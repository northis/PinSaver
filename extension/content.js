/**
 * Pinterest Archive Saver - Content Script
 * Intercepts Save button clicks and saves pins to local archive.
 * Also adds archive status icons to pins on profile/favorites pages.
 */

(function() {
    'use strict';

    const DEFAULT_SERVER_URL = 'http://localhost:8000';
    let serverUrl = DEFAULT_SERVER_URL;
    let archivedPinIds = new Set();
    let pendingPinIds = new Set();
    let checkDebounceTimer = null;

    // Load server URL from storage
    chrome.storage.sync.get(['serverUrl'], (result) => {
        if (result.serverUrl) {
            serverUrl = result.serverUrl;
        }
    });

    /**
     * Extract pin ID from URL
     * @param {string} url - URL to extract pin ID from
     * @returns {string|null} Pin ID or null
     */
    function getPinIdFromUrl(url) {
        const match = url.match(/\/pin\/(\d+)/);
        return match ? match[1] : null;
    }

    /**
     * Build original URL from file ID
     * @param {string} fileId - 32-character file hash
     * @param {string} extension - File extension
     * @returns {string} Original image URL
     */
    function buildOriginalUrl(fileId, extension) {
        return `https://i.pinimg.com/originals/${fileId.slice(0,2)}/${fileId.slice(2,4)}/${fileId.slice(4,6)}/${fileId}.${extension}`;
    }

    /**
     * Extract file ID from image URL or src
     * @param {string} src - Image source URL
     * @returns {{fileId: string, extension: string}|null} File info or null
     */
    function extractFileId(src) {
        const match = src.match(/([a-f0-9]{32})\.(\w+)(?:\?|$)/i);
        if (match) {
            return { fileId: match[1], extension: match[2] };
        }
        return null;
    }

    /**
     * Extract original image URL from the page
     */
    function getOriginalImageUrl() {
        // Priority 1: Find main pin image by elementtiming attribute (Story Pins)
        const mainPinImage = document.querySelector('img[elementtiming="StoryPinImageBlock-MainPinImage"]');
        if (mainPinImage) {
            const src = mainPinImage.src;
            const fileInfo = extractFileId(src);
            if (fileInfo) {
                return buildOriginalUrl(fileInfo.fileId, fileInfo.extension);
            }
        }

        // Priority 2: Find closeup image by data-test-id
        const closeupImage = document.querySelector('[data-test-id="closeup-image"] img, [data-test-id="pin-closeup-image"] img');
        if (closeupImage) {
            const src = closeupImage.src;
            const fileInfo = extractFileId(src);
            if (fileInfo) {
                return buildOriginalUrl(fileInfo.fileId, fileInfo.extension);
            }
        }

        // Priority 3: Find image in srcset with /originals/ (but exclude related pins)
        const mainContainer = document.querySelector('[data-test-id="closeup-container"], [data-test-id="story-pin-image-block"]');
        if (mainContainer) {
            const images = mainContainer.querySelectorAll('img[srcset]');
            for (const img of images) {
                const srcset = img.getAttribute('srcset') || '';
                const match = srcset.match(/(https:\/\/i\.pinimg\.com\/originals\/[^\s,]+)/);
                if (match) {
                    return match[1];
                }
            }
        }

        // Priority 4: Find any image with /originals/ in main container
        if (mainContainer) {
            const images = mainContainer.querySelectorAll('img[src*="pinimg.com"]');
            for (const img of images) {
                const src = img.src;
                if (src.includes('/originals/')) {
                    return src.split('?')[0];
                }
                // Try to construct original URL from any resolution
                const fileInfo = extractFileId(src);
                if (fileInfo) {
                    return buildOriginalUrl(fileInfo.fileId, fileInfo.extension);
                }
            }
        }

        // Fallback: Search all images with srcset containing /originals/
        const allSrcsetImages = document.querySelectorAll('img[srcset]');
        for (const img of allSrcsetImages) {
            const srcset = img.getAttribute('srcset') || '';
            const match = srcset.match(/(https:\/\/i\.pinimg\.com\/originals\/[^\s,]+)/);
            if (match) {
                return match[1];
            }
        }

        // Last resort: Try to construct from any pinimg image
        const allImages = document.querySelectorAll('img[src*="pinimg.com"]');
        for (const img of allImages) {
            const src = img.src;
            if (src.includes('/originals/')) {
                return src.split('?')[0];
            }
        }

        for (const img of allImages) {
            const fileInfo = extractFileId(img.src);
            if (fileInfo) {
                return buildOriginalUrl(fileInfo.fileId, fileInfo.extension);
            }
        }

        return null;
    }

    /**
     * Show notification popup
     */
    function showNotification(message, type = 'success') {
        // Remove existing notification
        const existing = document.getElementById('pinterest-archive-notification');
        if (existing) {
            existing.remove();
        }

        const notification = document.createElement('div');
        notification.id = 'pinterest-archive-notification';
        notification.className = `pa-notification pa-notification-${type}`;
        notification.innerHTML = `
            <div class="pa-notification-icon">${type === 'success' ? '✓' : type === 'error' ? '✗' : type === 'exists' ? 'ℹ' : '⏳'}</div>
            <div class="pa-notification-message">${message}</div>
        `;

        document.body.appendChild(notification);

        // Animate in
        requestAnimationFrame(() => {
            notification.classList.add('pa-notification-show');
        });

        // Auto-hide after 3 seconds
        setTimeout(() => {
            notification.classList.remove('pa-notification-show');
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    /**
     * Save pin to archive
     */
    async function saveToArchive(pinId, originalUrl) {
        showNotification('Saving to archive...', 'loading');

        try {
            const response = await fetch(`${serverUrl}/api/pins`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    pin_id: pinId,
                    original_url: originalUrl
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Server error');
            }

            const result = await response.json();

            if (result.status === 'exists') {
                showNotification('Pin already in archive', 'exists');
            } else {
                showNotification('Pin saved to archive!', 'success');
            }

        } catch (error) {
            console.error('Pinterest Archive Saver error:', error);
            showNotification(`Error: ${error.message}`, 'error');
        }
    }

    /**
     * Handle Save button click
     */
    function handleSaveClick(event) {
        const pinId = getPinIdFromUrl(window.location.href);
        if (!pinId) {
            console.log('Pinterest Archive: No pin ID found in URL');
            return;
        }

        const originalUrl = getOriginalImageUrl();
        if (!originalUrl) {
            showNotification('Could not find original image', 'error');
            return;
        }

        // Save to archive (don't prevent default - let Pinterest save work too)
        saveToArchive(pinId, originalUrl);
    }

    /**
     * Find and attach to Save buttons
     */
    function attachToSaveButtons() {
        // Pinterest uses various selectors for Save button
        const saveButtonSelectors = [
            '[data-test-id="PinBetterSaveButton"]',
            '[data-test-id="save-button"]',
            'button[aria-label*="Save"]',
            'button[aria-label*="Сохранить"]',
            'div[data-test-id="save-button"]'
        ];

        for (const selector of saveButtonSelectors) {
            const buttons = document.querySelectorAll(selector);
            buttons.forEach(button => {
                if (!button.dataset.archiveAttached) {
                    button.dataset.archiveAttached = 'true';
                    button.addEventListener('click', handleSaveClick, true);
                }
            });
        }
    }

    /**
     * Initialize observer for dynamic content
     */
    function initObserver() {
        const observer = new MutationObserver((mutations) => {
            let shouldCheck = false;
            for (const mutation of mutations) {
                if (mutation.addedNodes.length > 0) {
                    shouldCheck = true;
                    break;
                }
            }
            if (shouldCheck) {
                attachToSaveButtons();
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }

    // ==========================================
    // FAVORITES/PROFILE PAGE FUNCTIONALITY
    // ==========================================

    /**
     * Check if current page is a profile/favorites page (grid of pins)
     * @returns {boolean} True if on profile page
     */
    function isProfilePage() {
        const url = window.location.href;
        // Profile pages: pinterest.com/username/ or pinterest.com/username/_saved/
        return url.match(/pinterest\.com\/[^\/]+\/?(_saved|_created)?/i) && !url.includes('/pin/');
    }

    /**
     * Find all pin elements on the page
     * @returns {NodeListOf<Element>} Pin elements
     */
    function findPinElements() {
        // Pinterest uses data-test-id="pin" or links containing /pin/
        return document.querySelectorAll('[data-test-id="pin"], [data-test-id="pinWrapper"], a[href*="/pin/"]');
    }

    /**
     * Extract pin ID from a pin element
     * @param {Element} element - Pin element
     * @returns {string|null} Pin ID or null
     */
    function getPinIdFromElement(element) {
        // Try to find link with pin ID
        const link = element.tagName === 'A' ? element : element.querySelector('a[href*="/pin/"]');
        if (link) {
            const pinId = getPinIdFromUrl(link.href);
            if (pinId) return pinId;
        }
        return null;
    }

    /**
     * Extract original image URL from a pin element on grid
     * @param {Element} element - Pin element
     * @returns {string|null} Original image URL or null
     */
    function getOriginalUrlFromPinElement(element) {
        const img = element.querySelector('img[src*="pinimg.com"]');
        if (img) {
            const fileInfo = extractFileId(img.src);
            if (fileInfo) {
                return buildOriginalUrl(fileInfo.fileId, fileInfo.extension);
            }
        }
        return null;
    }

    /**
     * Check which pins are archived (batch request)
     * @param {string[]} pinIds - Array of pin IDs to check
     */
    async function checkArchivedPins(pinIds) {
        if (pinIds.length === 0) return;
        
        try {
            const response = await fetch(`${serverUrl}/api/pins/check`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pin_ids: pinIds })
            });
            
            if (response.ok) {
                const data = await response.json();
                data.existing.forEach(id => archivedPinIds.add(id));
                updateArchiveIcons();
            }
        } catch (error) {
            console.error('Pinterest Archive: Failed to check pins', error);
        }
    }

    /**
     * Schedule a debounced check for new pins
     */
    function scheduleArchiveCheck() {
        if (checkDebounceTimer) {
            clearTimeout(checkDebounceTimer);
        }
        checkDebounceTimer = setTimeout(() => {
            const newPinIds = Array.from(pendingPinIds);
            pendingPinIds.clear();
            if (newPinIds.length > 0) {
                checkArchivedPins(newPinIds);
            }
        }, 500);
    }

    /**
     * Create archive icon element
     * @param {string} pinId - Pin ID
     * @param {boolean} isArchived - Whether pin is archived
     * @returns {HTMLElement} Icon element
     */
    function createArchiveIcon(pinId, isArchived) {
        const icon = document.createElement('div');
        icon.className = `pa-archive-icon ${isArchived ? 'pa-archived' : 'pa-not-archived'}`;
        icon.dataset.pinId = pinId;
        icon.title = isArchived ? 'In archive' : 'Click to save to archive';
        icon.innerHTML = isArchived ? '✓' : '↓';
        
        if (!isArchived) {
            icon.addEventListener('click', handleArchiveIconClick);
        }
        
        return icon;
    }

    /**
     * Handle click on archive icon
     * @param {Event} event - Click event
     */
    async function handleArchiveIconClick(event) {
        event.preventDefault();
        event.stopPropagation();
        
        const icon = event.currentTarget;
        const pinId = icon.dataset.pinId;
        
        if (!pinId || archivedPinIds.has(pinId)) return;
        
        // Find the pin element and extract image URL
        const pinElement = icon.closest('[data-test-id="pin"], [data-test-id="pinWrapper"]') || 
                          icon.closest('div').parentElement;
        const originalUrl = getOriginalUrlFromPinElement(pinElement);
        
        if (!originalUrl) {
            showNotification('Could not find image URL', 'error');
            return;
        }
        
        // Update icon to loading state
        icon.innerHTML = '⏳';
        icon.classList.remove('pa-not-archived');
        icon.classList.add('pa-loading');
        
        // Save to archive
        try {
            const response = await fetch(`${serverUrl}/api/pins`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    pin_id: pinId,
                    original_url: originalUrl
                })
            });
            
            if (response.ok) {
                const result = await response.json();
                archivedPinIds.add(pinId);
                
                // Update icon to archived state
                icon.innerHTML = '✓';
                icon.classList.remove('pa-loading');
                icon.classList.add('pa-archived');
                icon.title = 'In archive';
                icon.removeEventListener('click', handleArchiveIconClick);
                
                if (result.status === 'exists') {
                    showNotification(`Pin ${pinId} already in archive`, 'exists');
                } else {
                    showNotification(`Pin ${pinId} saved!`, 'success');
                }
            } else {
                throw new Error('Server error');
            }
        } catch (error) {
            // Revert icon state
            icon.innerHTML = '↓';
            icon.classList.remove('pa-loading');
            icon.classList.add('pa-not-archived');
            showNotification(`Failed to save pin ${pinId}`, 'error');
        }
    }

    /**
     * Add archive icons to pin elements
     */
    function addArchiveIcons() {
        const pinElements = findPinElements();
        
        pinElements.forEach(element => {
            // Skip if already processed
            if (element.dataset.paProcessed) return;
            
            const pinId = getPinIdFromElement(element);
            if (!pinId) return;
            
            element.dataset.paProcessed = 'true';
            
            // Find the container to add icon to
            let container = element;
            if (element.tagName === 'A') {
                container = element.parentElement;
            }
            
            // Make container relative for absolute positioning
            if (getComputedStyle(container).position === 'static') {
                container.style.position = 'relative';
            }
            
            // Add to pending check if not already known
            if (!archivedPinIds.has(pinId)) {
                pendingPinIds.add(pinId);
            }
            
            // Create and add icon
            const isArchived = archivedPinIds.has(pinId);
            const icon = createArchiveIcon(pinId, isArchived);
            container.appendChild(icon);
        });
        
        // Schedule check for new pins
        if (pendingPinIds.size > 0) {
            scheduleArchiveCheck();
        }
    }

    /**
     * Update archive icons based on current archivedPinIds set
     */
    function updateArchiveIcons() {
        document.querySelectorAll('.pa-archive-icon').forEach(icon => {
            const pinId = icon.dataset.pinId;
            if (archivedPinIds.has(pinId) && !icon.classList.contains('pa-archived')) {
                icon.innerHTML = '✓';
                icon.classList.remove('pa-not-archived', 'pa-loading');
                icon.classList.add('pa-archived');
                icon.title = 'In archive';
                icon.removeEventListener('click', handleArchiveIconClick);
            }
        });
    }

    // ==========================================
    // INITIALIZATION
    // ==========================================

    /**
     * Initialize observer for dynamic content
     */
    function initObserver() {
        const observer = new MutationObserver((mutations) => {
            let shouldCheck = false;
            for (const mutation of mutations) {
                if (mutation.addedNodes.length > 0) {
                    shouldCheck = true;
                    break;
                }
            }
            if (shouldCheck) {
                attachToSaveButtons();
                if (isProfilePage()) {
                    addArchiveIcons();
                }
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }

    /**
     * Initialize the extension
     */
    function init() {
        attachToSaveButtons();
        initObserver();
        
        // If on profile page, add archive icons
        if (isProfilePage()) {
            addArchiveIcons();
        }
        
        console.log('Pinterest Archive Saver initialized');
    }

    // Wait for DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
