/**
 * Pinterest Archive Saver - Options Page Script
 */

const DEFAULT_SERVER_URL = 'http://localhost:8000';
const REPO_URL = 'https://github.com/northis/PinSaver';

// Origins the manifest grants on its own: Chrome never asks for them, so they
// must never be given up when the address changes
const REQUIRED_ORIGINS = ['http://localhost:8000', 'http://127.0.0.1:8000'];

// The archive keeps its last save attempts in local storage, newest first
const SAVE_LOG_KEY = 'saveLog';
const SAVE_LOG_LIMIT = 10;
//: The first archive version that accepts an image from another site
const MIN_WEB_PINS_VERSION = '2.8.0';
const SAVE_LABELS = { added: 'saved', exists: 'already in the archive', error: 'error' };
const VIA_LABELS = { server: 'server', browser: 'browser', none: 'not sent' };

// Origin of the address in storage, so a save to another address can drop the
// permission the previous address was granted
let previousOrigin = null;

/**
 * Strip trailing slashes so paths can be appended safely.
 * @param {string} url - Raw URL from the input field.
 * @returns {string} URL without trailing slashes.
 */
function normalizeUrl(url) {
    return (url || '').trim().replace(/\/+$/, '');
}

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
 * Make an API request through the background script, the only holder of the
 * server address and of the permission for it.
 * @param {string} path - API path, must be one of the allowlisted routes
 * @param {Object} options - Fetch options
 * @returns {Promise<Object>} Response data
 */
async function apiRequest(path, options = {}) {
    return new Promise((resolve, reject) => {
        chrome.runtime.sendMessage(
            { type: 'API_REQUEST', path, options },
            (response) => {
                if (chrome.runtime.lastError) {
                    reject(new Error(chrome.runtime.lastError.message));
                } else if (response.success) {
                    resolve(response.data);
                } else {
                    const error = new Error(response.error);
                    error.code = response.code;
                    reject(error);
                }
            }
        );
    });
}

/**
 * Write one line into the status area under the Save button.
 * @param {string} text - Message to show
 * @param {'info'|'success'|'error'} kind - `info` is the transient progress line
 */
function showStatus(text, kind) {
    const statusEl = document.getElementById('status');

    // Only the progress line has no class of its own, so it carries its colours
    // inline; the other kinds must clear them or the inline values would win
    const info = kind === 'info';
    statusEl.className = info ? 'status' : `status ${kind}`;
    statusEl.textContent = text;
    statusEl.style.display = 'block';
    statusEl.style.background = info ? '#fff3e0' : '';
    statusEl.style.color = info ? '#e65100' : '';
}

/**
 * Compare two dotted versions.
 * @param {string} version - Version reported by the archive
 * @param {string} minimum - Version a feature needs
 * @returns {boolean} True when `version` is at least `minimum`
 */
function versionAtLeast(version, minimum) {
    const have = String(version).split('.').map(Number);
    const need = minimum.split('.').map(Number);
    for (let i = 0; i < need.length; i++) {
        if ((have[i] || 0) !== need[i]) return (have[i] || 0) > need[i];
    }
    return true;
}

/**
 * Shorten a stored link for one line: the host and path say more than the whole URL.
 * @param {string} url - Page or image link
 * @returns {string} Something readable, at most 90 characters
 */
function shortUrl(url) {
    if (!url) return '';
    if (url.startsWith('data:')) return 'data: image';
    let text = url;
    try {
        const parsed = new URL(url);
        text = parsed.hostname.replace(/^www\./, '') + (parsed.pathname === '/' ? '' : parsed.pathname);
    } catch {
        // A stored value that no longer parses is still worth showing as it is
    }
    return text.length > 90 ? text.slice(0, 90) + '…' : text;
}

/**
 * Draw the last save attempts: the badge disappears in seconds, so a refusal has to stay
 * readable somewhere.
 */
async function renderSaveLog() {
    const list = document.getElementById('saveLog');
    const stored = await chrome.storage.local.get([SAVE_LOG_KEY]);
    const entries = Array.isArray(stored[SAVE_LOG_KEY])
        ? stored[SAVE_LOG_KEY].slice(0, SAVE_LOG_LIMIT)
        : [];

    if (!entries.length) {
        list.textContent =
            'Nothing yet: right-click an image in Chrome and choose “Save image to PinSaver”.';
        return;
    }

    list.replaceChildren(...entries.map(entry => {
        const row = document.createElement('div');
        row.className = 'save-entry';

        const what = document.createElement('div');
        what.className = entry.status === 'error' ? 'what error' : 'what';
        what.textContent = [
            new Date(entry.at).toLocaleString(),
            SAVE_LABELS[entry.status] || entry.status,
            VIA_LABELS[entry.via] || entry.via
        ].filter(Boolean).join(' · ');

        const where = document.createElement('div');
        where.className = 'where';
        where.textContent = `${shortUrl(entry.page) || '—'} ← ${shortUrl(entry.image) || '—'}`;

        row.append(what, where);

        if (entry.detail) {
            const detail = document.createElement('div');
            detail.className = entry.status === 'error' ? 'detail error' : 'detail';
            detail.textContent = entry.detail;
            row.appendChild(detail);
        }

        return row;
    }));
}

/**
 * Ask the archive server for the version and commit of its checkout.
 * The extension and the server share one repository, so the commit served
 * here is the revision the extension was loaded from.
 */
async function loadBuildInfo() {
    const commitLink = document.getElementById('buildCommit');
    const noteEl = document.getElementById('buildNote');
    const serverUrlInput = document.getElementById('serverUrl');

    commitLink.hidden = true;
    noteEl.hidden = false;
    noteEl.textContent = 'checking server...';
    noteEl.title = '';

    try {
        const info = await apiRequest('/api/version');
        if (!info.commit) {
            throw new Error('server has no commit info');
        }

        commitLink.textContent = info.short + (info.dirty ? '*' : '');
        commitLink.href = info.commit_url || `${info.repo_url}/commit/${info.commit}`;
        commitLink.title = [
            `PinSaver ${info.version}`,
            `commit ${info.short}`,
            info.commit_date ? info.commit_date.slice(0, 10) : null,
            info.dirty ? 'uncommitted changes' : null
        ].filter(Boolean).join(', ');
        commitLink.hidden = false;
        noteEl.hidden = true;

        // An older archive answers the image routes with 404: say so instead of letting a
        // save fail silently
        if (!versionAtLeast(info.version, MIN_WEB_PINS_VERSION)) {
            showStatus(
                `The archive runs ${info.version}: saving images from other sites needs ` +
                `${MIN_WEB_PINS_VERSION} or newer. Update the server.`,
                'error'
            );
        }
    } catch (error) {
        noteEl.textContent = 'server unavailable';
        noteEl.title = `${serverUrlInput.value}: ${error.message || error}`;

        // Neither code means a broken server: say which one was reported
        if (error.code === 'NOT_AUTHENTICATED') {
            showStatus('Cloudflare Access needs a sign-in — open the archive in this browser first.', 'error');
        } else if (error.code === 'NO_PERMISSION') {
            showStatus('Access to this server is not granted — press Save to allow it.', 'error');
        }
    }
}

/**
 * Show whether the extension may already call the address in the field.
 */
async function refreshAccessState() {
    const stateEl = document.getElementById('accessState');
    const grantBtn = document.getElementById('grantBtn');

    const origin = originOf(document.getElementById('serverUrl').value);
    const granted = origin ? await chrome.permissions.contains({ origins: [origin + '/*'] }) : false;

    stateEl.textContent = granted ? 'Access to server: granted' : 'Access to server: not granted';
    grantBtn.disabled = granted;
}

/**
 * Ask Chrome for access to the origin in the field.
 * Parses the field and calls Chrome synchronously, so a click handler that
 * awaits this still holds its user gesture and the prompt is shown.
 * @returns {Promise<boolean>} True when the user allowed the origin
 * @throws {Error} When the field is not a full http(s) URL
 */
function requestAccess() {
    const origin = originOf(document.getElementById('serverUrl').value);
    if (!origin) {
        throw new Error('enter a full URL');
    }
    return chrome.permissions.request({ origins: [origin + '/*'] });
}

/**
 * Save the address in the field: ask for access to it, store it, drop the
 * permission of the previous address and probe the server. Shared by the Save
 * and Grant access buttons, so the probe always runs against the address the
 * permission was just granted for.
 */
async function saveSettings() {
    const serverUrlInput = document.getElementById('serverUrl');
    const openArchiveLink = document.getElementById('openArchive');

    let granted;
    try {
        // Chrome only shows the prompt while the click's user gesture is alive,
        // so this must stay the first await of the handler
        granted = await requestAccess();
    } catch (error) {
        showStatus('Enter a full URL, for example https://pinsaver.example', 'error');
        return;
    }

    const serverUrl = normalizeUrl(serverUrlInput.value) || DEFAULT_SERVER_URL;
    serverUrlInput.value = serverUrl;
    openArchiveLink.href = serverUrl;

    await chrome.storage.sync.set({ serverUrl });

    const origin = originOf(serverUrl);
    if (previousOrigin && previousOrigin !== origin && !REQUIRED_ORIGINS.includes(previousOrigin)) {
        try {
            await chrome.permissions.remove({ origins: [previousOrigin + '/*'] });
        } catch {
            // A permission that is already gone is not a failure here
        }
    }
    previousOrigin = origin;

    await refreshAccessState();

    if (!granted) {
        showStatus('Access to this server is not granted — press Save to allow it.', 'error');
    } else {
        showStatus('Testing connection...', 'info');

        try {
            await apiRequest('/health');
            showStatus('Settings saved! Connection successful.', 'success');
        } catch (error) {
            if (error.code === 'NOT_AUTHENTICATED') {
                showStatus('Cloudflare Access needs a sign-in — open the archive in this browser first.', 'error');
            } else if (error.code === 'NO_PERMISSION') {
                showStatus('Access to this server is not granted — press Save to allow it.', 'error');
            } else {
                showStatus(`Connection failed: ${error.message}. Settings saved anyway.`, 'error');
            }
        }
    }

    loadBuildInfo();
}

document.addEventListener('DOMContentLoaded', async () => {
    const serverUrlInput = document.getElementById('serverUrl');
    const saveBtn = document.getElementById('saveBtn');
    const grantBtn = document.getElementById('grantBtn');
    const versionLink = document.getElementById('buildVersion');
    const openArchiveLink = document.getElementById('openArchive');

    // The extension version always comes from the manifest and links to its release tag
    const extensionVersion = chrome.runtime.getManifest().version;
    versionLink.textContent = 'v' + extensionVersion;
    versionLink.href = `${REPO_URL}/releases/tag/v${extensionVersion}`;
    versionLink.title = `Pinterest Archive Saver ${extensionVersion}`;

    // Load saved settings
    const stored = await chrome.storage.sync.get(['serverUrl']);
    const serverUrl = normalizeUrl(stored.serverUrl) || DEFAULT_SERVER_URL;
    previousOrigin = originOf(serverUrl);
    serverUrlInput.value = serverUrl;
    openArchiveLink.href = serverUrl;

    saveBtn.addEventListener('click', saveSettings);
    grantBtn.addEventListener('click', saveSettings);
    document.getElementById('refreshLog').addEventListener('click', renderSaveLog);

    // A save from a page reaches the log while this page is open
    chrome.storage.onChanged.addListener((changes, area) => {
        if (area === 'local' && changes[SAVE_LOG_KEY]) renderSaveLog();
    });

    // The permission can be revoked from chrome://extensions at any time
    chrome.permissions.onRemoved.addListener(() => refreshAccessState());

    renderSaveLog();
    await refreshAccessState();
    loadBuildInfo();
});
