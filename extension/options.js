/**
 * Pinterest Archive Saver - Options Page Script
 */

const DEFAULT_SERVER_URL = 'http://localhost:8000';
const REPO_URL = 'https://github.com/northis/PinSaver';

/**
 * Strip trailing slashes so paths can be appended safely.
 * @param {string} url - Raw URL from the input field.
 * @returns {string} URL without trailing slashes.
 */
function normalizeUrl(url) {
    return (url || '').trim().replace(/\/+$/, '');
}

/**
 * Ask the archive server for the version and commit of its checkout.
 * The extension and the server share one repository, so the commit served
 * here is the revision the extension was loaded from.
 * @param {string} serverUrl - Archive server base URL.
 */
async function loadBuildInfo(serverUrl) {
    const commitLink = document.getElementById('buildCommit');
    const noteEl = document.getElementById('buildNote');

    commitLink.hidden = true;
    noteEl.hidden = false;
    noteEl.textContent = 'checking server...';
    noteEl.title = '';

    try {
        const response = await fetch(`${serverUrl}/api/version`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const info = await response.json();
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
    } catch (error) {
        noteEl.textContent = 'server unavailable';
        noteEl.title = `${serverUrl}: ${error.message || error}`;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const serverUrlInput = document.getElementById('serverUrl');
    const saveBtn = document.getElementById('saveBtn');
    const statusEl = document.getElementById('status');
    const versionLink = document.getElementById('buildVersion');
    const openArchiveLink = document.getElementById('openArchive');

    // The extension version always comes from the manifest and links to its release tag
    const extensionVersion = chrome.runtime.getManifest().version;
    versionLink.textContent = 'v' + extensionVersion;
    versionLink.href = `${REPO_URL}/releases/tag/v${extensionVersion}`;
    versionLink.title = `Pinterest Archive Saver ${extensionVersion}`;

    // Load saved settings
    chrome.storage.sync.get(['serverUrl'], (result) => {
        const serverUrl = normalizeUrl(result.serverUrl) || DEFAULT_SERVER_URL;
        serverUrlInput.value = serverUrl;
        openArchiveLink.href = serverUrl;
        loadBuildInfo(serverUrl);
    });

    // Save settings
    saveBtn.addEventListener('click', async () => {
        const serverUrl = normalizeUrl(serverUrlInput.value) || DEFAULT_SERVER_URL;
        serverUrlInput.value = serverUrl;
        openArchiveLink.href = serverUrl;

        // Test connection
        statusEl.className = 'status';
        statusEl.textContent = 'Testing connection...';
        statusEl.style.display = 'block';
        statusEl.style.background = '#fff3e0';
        statusEl.style.color = '#e65100';

        try {
            const response = await fetch(`${serverUrl}/health`);
            if (!response.ok) {
                throw new Error('Server returned error');
            }

            // Save to storage
            chrome.storage.sync.set({ serverUrl }, () => {
                statusEl.className = 'status success';
                statusEl.textContent = 'Settings saved! Connection successful.';
            });

        } catch (error) {
            statusEl.className = 'status error';
            statusEl.textContent = `Connection failed: ${error.message}. Settings saved anyway.`;

            // Save anyway
            chrome.storage.sync.set({ serverUrl });
        }

        loadBuildInfo(serverUrl);
    });
});
