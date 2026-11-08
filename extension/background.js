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
 * @param {boolean} keep - Leave it until the next save: a refusal must not vanish unseen
 */
function showSaveOutcome(text, color, title, keep = false) {
    chrome.action.setBadgeBackgroundColor({ color });
    chrome.action.setBadgeText({ text });
    chrome.action.setTitle({ title: `PinSaver: ${title}` });
    if (keep) return;
    setTimeout(() => {
        chrome.action.setBadgeText({ text: '' });
        chrome.action.setTitle({ title: ACTION_TITLE });
    }, 5000);
}

/**
 * Remember one save attempt. The badge is gone in seconds, so the reason for a refusal has
 * to stay readable: the options page shows the last few.
 * @param {Object} entry - `{status, detail, via, image, page}`
 */
async function logSaveAttempt(entry) {
    const key = 'saveLog';
    const stored = await chrome.storage.local.get([key]);
    const list = Array.isArray(stored[key]) ? stored[key] : [];
    list.unshift({ at: Date.now(), ...entry });
    await chrome.storage.local.set({ [key]: list.slice(0, 10) });
}

/**
 * Read the image in the browser.
 *
 * The archive downloads most pictures itself; this path covers the sites that refuse an
 * anonymous download (a bot wall, a host on the user's own network) and `data:` links.
 * Chrome asks once for access to the image's site, and the answer sticks.
 *
 * @param {string} url - Image link from the context menu
 * @returns {Promise<Blob|null>} The image, or null when the browser cannot get it
 */
async function fetchImageBlob(url) {
    try {
        if (!url.startsWith('data:')) {
            const origin = originOf(url);
            if (!origin) return null;
            const pattern = origin + '/*';
            const granted = await chrome.permissions.contains({ origins: [pattern] });
            if (!granted && !(await chrome.permissions.request({ origins: [pattern] }))) {
                return null;
            }
        }

        const response = await fetch(url, { credentials: 'omit', cache: 'no-store' });
        if (!response.ok) return null;
        const blob = await response.blob();
        return blob.size ? blob : null;
    } catch {
        return null;
    }
}

/**
 * Send a picture the browser already downloaded.
 * @param {Blob} blob - The image itself
 * @param {string} imageUrl - Where it came from, empty for a `data:` link
 * @param {string} pageUrl - Page it was right-clicked on
 * @returns {Promise<Object>} API response
 */
function uploadImageBlob(blob, imageUrl, pageUrl) {
    return handleApiRequest({
        path: '/api/pins/web/upload',
        options: {
            method: 'POST',
            headers: {
                'Content-Type': blob.type || 'application/octet-stream',
                'X-PinSaver-Page-Url': encodeURIComponent(pageUrl || ''),
                'X-PinSaver-Image-Url': encodeURIComponent(
                    imageUrl.startsWith('data:') ? '' : imageUrl
                )
            },
            body: blob
        }
    });
}

/**
 * Send one image to the archive and report the path it took.
 *
 * The server downloads the picture first, which keeps the browser away from the image
 * sites; when that fails the browser hands the bytes over instead.
 *
 * @param {string} imageUrl - `info.srcUrl` of the right-clicked image
 * @param {string} pageUrl - `info.pageUrl` of the page it sits on
 * @returns {Promise<{result: Object, via: string}>} API response and `server`, `browser` or `none`
 */
async function sendImage(imageUrl, pageUrl) {
    if (imageUrl.startsWith('blob:')) {
        // The link points into the page's memory: neither side can read it afterwards
        return {
            result: { success: false, error: 'the image exists only inside the page (blob: link)' },
            via: 'none'
        };
    }

    if (imageUrl.startsWith('data:')) {
        const blob = await fetchImageBlob(imageUrl);
        if (!blob) {
            return { result: { success: false, error: 'cannot read the data: image' }, via: 'none' };
        }
        return { result: await uploadImageBlob(blob, imageUrl, pageUrl), via: 'browser' };
    }

    const result = await handleApiRequest({
        path: '/api/pins/web',
        options: {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image_url: imageUrl, page_url: pageUrl || '' })
        }
    });
    if (result.success) return { result, via: 'server' };

    const blob = await fetchImageBlob(imageUrl);
    if (!blob) {
        // No access to the image's site is something a second click can fix; anything else
        // was already tried, so the server's reason is the answer
        const origin = originOf(imageUrl);
        const granted = origin && await chrome.permissions.contains({ origins: [origin + '/*'] });
        if (!granted) {
            return {
                result: {
                    success: false,
                    error: `${result.error} — allow access to ${origin} and try again`
                },
                via: 'server'
            };
        }
        return { result, via: 'server' };
    }

    return { result: await uploadImageBlob(blob, imageUrl, pageUrl), via: 'browser' };
}

/**
 * Save one image from any site and show how it went.
 * @param {string} imageUrl - `info.srcUrl` of the right-clicked image
 * @param {string} pageUrl - `info.pageUrl` of the page it sits on
 */
async function saveWebImage(imageUrl, pageUrl) {
    showSaveOutcome('…', '#5b6770', 'saving the image');

    const { result, via } = await sendImage(imageUrl, pageUrl);
    const status = result.success ? result.data.status : 'error';
    const detail = String(result.success ? result.data.message : result.error).slice(0, 500);

    await logSaveAttempt({
        status,
        detail,
        via,
        image: String(imageUrl).slice(0, 200),
        page: String(pageUrl || '').slice(0, 200)
    });

    if (!result.success) {
        console.error('PinSaver: image not saved:', detail);
        showSaveOutcome('!', '#c0392b', detail.slice(0, 300), true);
        return;
    }

    const added = status === 'added';
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
    'POST /api/pins/web/upload',
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
