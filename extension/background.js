/**
 * Background script for Pinterest Archive Saver.
 * Handles API requests to bypass Private Network Access restrictions.
 */

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
    const response = await fetch(url, options);
    
    if (!response.ok) {
        const text = await response.text();
        throw new Error(`HTTP ${response.status}: ${text}`);
    }
    
    return await response.json();
}
