/* PinSaver service worker.
 *
 * The system share sheet navigates to POST /share, and this worker turns that navigation into
 * an ordinary API request, then answers with a redirect to the outcome page. Everything else -
 * every page, image and stylesheet - goes to the network untouched: there is no caching here at
 * all, so a new release can never be served from a stale cache.
 *
 * The worker exists for two reasons: the share target needs it (a share POST is a navigation
 * the worker intercepts), and Android refuses to install an app whose worker has no fetch
 * handler.
 */
"use strict";

const SAVE_URL = "/api/pins/resolve";
const RESULT_URL = "/share";
const REQUEST_HEADER = "X-PinSaver-Request";

self.addEventListener("fetch", (event) => {
    const url = new URL(event.request.url);
    if (event.request.method !== "POST" || url.pathname !== RESULT_URL) return;
    event.respondWith(handleShare(event.request));
});

/* Read the shared link out of the multipart body and ask the server to save it. */
async function handleShare(request) {
    let link = "";
    try {
        const form = await request.formData();
        link = ["url", "text", "title"]
            .map((name) => form.get(name))
            .filter((value) => typeof value === "string")
            .join(" ")
            .trim();
    } catch (error) {
        return Response.redirect(`${RESULT_URL}?error=empty`, 303);
    }

    if (!link) return Response.redirect(`${RESULT_URL}?error=empty`, 303);

    let response;
    try {
        response = await fetch(SAVE_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                [REQUEST_HEADER]: "1"
            },
            body: JSON.stringify({ url: link })
        });
    } catch (error) {
        return serverIsDown();
    }

    const data = await response.json().catch(() => null);

    if (!response.ok || !data || typeof data !== "object") {
        /* An Access login page served with 200, a Traefik error page or an empty body all
           parse to nothing: there is no outcome to show, so say what actually happened. */
        if (!data) return serverIsDown();
        return Response.redirect(
            `${RESULT_URL}?error=${encodeURIComponent(data.detail || "unknown")}`,
            303
        );
    }

    const params = new URLSearchParams({ status: data.status || "added" });
    if (data.pin_id) params.set("pin", data.pin_id);
    if (data.size) params.set("size", data.size);
    return Response.redirect(`${RESULT_URL}?${params.toString()}`, 303);
}

/* The outcome page is rendered by the server, and the server is exactly what is missing:
   answer with a page of our own instead of redirecting into a Traefik error. */
function serverIsDown() {
    const html =
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">' +
        '<meta name="viewport" content="width=device-width, initial-scale=1">' +
        "<title>PinSaver</title></head>" +
        '<body style="font:16px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;padding:24px;max-width:520px">' +
        '<h1 style="font-size:20px">PinSaver server is not answering</h1>' +
        "<p>The pin was not saved. Check that the machine with the archive is on, then share again.</p>" +
        "</body></html>";

    return new Response(html, {
        status: 503,
        headers: { "Content-Type": "text/html; charset=utf-8" }
    });
}
