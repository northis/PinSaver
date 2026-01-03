/**
 * Pinterest Archive Saver - Content Script
 * Intercepts Save button clicks and saves pins to local archive
 */

(function() {
    'use strict';

    const DEFAULT_SERVER_URL = 'http://localhost:8000';
    let serverUrl = DEFAULT_SERVER_URL;

    // Load server URL from storage
    chrome.storage.sync.get(['serverUrl'], (result) => {
        if (result.serverUrl) {
            serverUrl = result.serverUrl;
        }
    });

    /**
     * Extract pin ID from current URL or element
     */
    function getPinIdFromUrl(url) {
        const match = url.match(/\/pin\/(\d+)/);
        return match ? match[1] : null;
    }

    /**
     * Build original URL from file ID
     */
    function buildOriginalUrl(fileId, extension) {
        return `https://i.pinimg.com/originals/${fileId.slice(0,2)}/${fileId.slice(2,4)}/${fileId.slice(4,6)}/${fileId}.${extension}`;
    }

    /**
     * Extract file ID from image URL or src
     */
    function extractFileId(src) {
        // Match pattern: /XX/YY/ZZ/HASH.ext or just HASH.ext
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

    // Initialize
    function init() {
        attachToSaveButtons();
        initObserver();
        console.log('Pinterest Archive Saver initialized');
    }

    // Wait for DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
