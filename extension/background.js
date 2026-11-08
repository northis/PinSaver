/**
 * Background script for Pinterest Archive Saver.
 * Handles API requests to bypass Private Network Access restrictions.
 */

// The toolbar icon has no popup, so a click opens the settings page
chrome.action.onClicked.addListener(() => {
    chrome.runtime.openOptionsPage();
});

// Right-clicking an image on any site offers to archive it. The context menu already
// carries the image and page links, so that path needs no content script outside Pinterest.
const SAVE_IMAGE_MENU_ID = 'pinsaver-save-image';
const ACTION_TITLE = 'Pinterest Archive Saver - settings';

chrome.runtime.onInstalled.addListener(() => {
    // Re-created rather than updated: a changed title would otherwise stay stale
    chrome.contextMenus.removeAll(() => {
        chrome.contextMenus.create({
            id: SAVE_IMAGE_MENU_ID,
            title: 'Save image to PinSaver',
            contexts: ['image']
        });
    });
});

chrome.contextMenus.onClicked.addListener((info) => {
    if (info.menuItemId === SAVE_IMAGE_MENU_ID && info.srcUrl) {
        saveWebImage(info.srcUrl, info.pageUrl);
    }
});

/**
 * Report the outcome where the user is looking: the badge on the toolbar icon, with the
 * reason in the tooltip. A page that is not Pinterest has no content-script notification.
 * @param {string} text - Badge text: one character, empty clears it
 * @param {string} color - Badge background
 * @param {string} title - Tooltip shown while the badge is up
 */
function showSaveOutcome(text, color, title) {
    chrome.action.setBadgeBackgroundColor({ color });
    chrome.action.setBadgeText({ text });
    chrome.action.setTitle({ title: `PinSaver: ${title}` });
    setTimeout(() => {
        chrome.action.setBadgeText({ text: '' });
        chrome.action.setTitle({ title: ACTION_TITLE });
    }, 5000);
}

/**
 * Save one image from any site through the archive API.
 * @param {string} imageUrl - `info.srcUrl` of the right-clicked image
 * @param {string} pageUrl - `info.pageUrl` of the page it sits on
 */
async function saveWebImage(imageUrl, pageUrl) {
    showSaveOutcome('…', '#5b6770', 'saving the image');

    const result = await handleApiRequest({
        path: '/api/pins/web',
        options: {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image_url: imageUrl, page_url: pageUrl || '' })
        }
    });

    if (!result.success) {
        showSaveOutcome('!', '#c0392b', result.error);
        return;
    }

    const added = result.data.status === 'added';
    showSaveOutcome(
        added ? '✓' : 'i',
        added ? '#1f9d55' : '#5b6770',
        added ? 'image saved to the archive' : 'image is already in the archive'
    );
}

// Where the archive lives when the user has not configured another address
const DEFAULT_SERVER_URL = 'http://localhost:8000';

// Exact `${method} ${path}` pairs the extension may request. Matching the whole
// string, not a prefix, keeps a forged path such as `//evil.example/api/pins`
// from turning into a request to another host.
const ALLOWED_REQUESTS = new Set([
    'GET /api/pins/sync',
    'POST /api/pins',
    'POST /api/pins/check',
    'POST /api/pins/web',
    'GET /health',
    'GET /api/version'
]);

// Handle messages from content script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'API_REQUEST') {
        handleApiRequest(message).then(sendResponse);
        return true; // Keep channel open for async response
    }
});

/**
 * Parse an http(s) URL into its origin.
 * @param {string} url - Value to parse
 * @returns {string|null} Origin, or null when the value is not an http(s) URL
 */
function originOf(url) {
    try {
        const parsed = new URL(url);
        return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.origin : null;
    } catch {
        return null;
    }
}

/**
 * Serve one API_REQUEST message. Never rejects: every refusal is a response object.
 * @param {Object} message - `{type, path, options}` from a content script or the options page
 * @returns {Promise<{success: true, data: Object}|{success: false, code: string, error: string}>}
 */
async function handleApiRequest(message) {
    const options = message.options || {};

    // A message with the old `url` field comes from a stale content script
    if (typeof message.url === 'string') {
        return { success: false, code: 'BAD_REQUEST', error: 'unsupported API request — reload the extension' };
    }

    const path = message.path;
    const method = String(options.method || 'GET').toUpperCase();
    if (typeof path !== 'string' || !ALLOWED_REQUESTS.has(`${method} ${path}`)) {
        return { success: false, code: 'BAD_REQUEST', error: 'request is not allowed' };
    }

    let timeoutId = null;
    try {
        const { serverUrl } = await chrome.storage.sync.get(['serverUrl']);
        const origin = originOf(serverUrl || DEFAULT_SERVER_URL);
        if (!origin) {
            return { success: false, code: 'BAD_REQUEST', error: 'server URL is not a valid http(s) URL' };
        }

        const granted = await chrome.permissions.contains({ origins: [origin + '/*'] });
        if (!granted) {
            return { success: false, code: 'NO_PERMISSION', error: 'access to this origin is not granted' };
        }

        // Guard against a hung request: without it a pin would stay in-flight forever
        const controller = new AbortController();
        timeoutId = setTimeout(() => controller.abort(), 60000);

        // `credentials` and the guard header come after the spread, so the caller
        // cannot drop them or replace the header with its own value
        const response = await fetch(origin + path, {
            ...options,
            credentials: 'include',
            headers: { ...(options.headers || {}), 'X-PinSaver-Request': '1' },
            signal: controller.signal
        });

        // Cloudflare Access answers a missing session either with a redirect off our
        // origin or with an HTML sign-in page under 200: both mean "not signed in",
        // not a server failure.
        const contentType = response.headers.get('content-type') || '';
        if ((response.redirected && originOf(response.url) !== origin) || !contentType.includes('application/json')) {
            return { success: false, code: 'NOT_AUTHENTICATED', error: 'the server answered with a sign-in page' };
        }

        if (!response.ok) {
            const text = await response.text();
            return { success: false, code: 'HTTP', error: `HTTP ${response.status}: ${text}` };
        }

        return { success: true, data: await response.json() };
    } catch (error) {
        return { success: false, code: 'NETWORK', error: error.message };
    } finally {
        clearTimeout(timeoutId);
    }
}
