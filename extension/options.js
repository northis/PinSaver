/**
 * Pinterest Archive Saver - Options Page Script
 */

const DEFAULT_SERVER_URL = 'http://localhost:8000';

document.addEventListener('DOMContentLoaded', () => {
    const serverUrlInput = document.getElementById('serverUrl');
    const saveBtn = document.getElementById('saveBtn');
    const statusEl = document.getElementById('status');

    // Load saved settings
    chrome.storage.sync.get(['serverUrl'], (result) => {
        serverUrlInput.value = result.serverUrl || DEFAULT_SERVER_URL;
    });

    // Save settings
    saveBtn.addEventListener('click', async () => {
        const serverUrl = serverUrlInput.value.trim() || DEFAULT_SERVER_URL;

        // Test connection
        statusEl.className = 'status';
        statusEl.textContent = 'Testing connection...';
        statusEl.style.display = 'block';
        statusEl.style.background = '#fff3e0';
        statusEl.style.color = '#e65100';

        try {
            const response = await fetch(`${serverUrl}/api/pins?limit=1`);
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
    });
});
