/**
 * Background script for Pinterest Archive Saver.
 * Handles API requests to bypass Private Network Access restrictions.
 */

// The toolbar icon has no popup, so a click opens the settings page
chrome.action.onClicked.addListener(() => {
    chrome.runtime.openOptionsPage();
});

// Handle messages from content script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'API_REQUEST') {
        handleApiRequest(message.url, message.options)
            .then(response => sendResponse({ success: true, data: response }))
            .catch(error => sendResponse({ success: false, error: error.message }));
        return true; // Keep channel open for async response
    }
});

/**
 * Make API request from background script (bypasses PNA restrictions).
 * @param {string} url - API URL
 * @param {Object} options - Fetch options
 * @returns {Promise<Object>} Response data
 */
async function handleApiRequest(url, options) {
    // Guard against a hung request: without it a pin would stay in-flight forever
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 60000);
    
    try {
        // The server refuses mutating requests without this header; a foreign page cannot
        // set it (its preflight is rejected), while the extension keeps its own origin
        const response = await fetch(url, {
            ...options,
            headers: { 'X-PinSaver-Request': '1', ...(options && options.headers) },
            signal: controller.signal
        });
        
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`HTTP ${response.status}: ${text}`);
        }
        
        return await response.json();
    } finally {
        clearTimeout(timeoutId);
    }
}
