/**
 * Job Copilot Assistant — background service worker (MV3).
 *
 * Acts as the single messaging hub between content scripts and the local
 * FastAPI backend. The auth token lives only here (chrome.storage.local);
 * content scripts never see it — they request API calls by message.
 */

const DEFAULT_SETTINGS = {
  backendUrl: 'http://localhost:8000',
  token: '',
};

async function getSettings() {
  const stored = await chrome.storage.local.get(DEFAULT_SETTINGS);
  return {
    backendUrl: (stored.backendUrl || DEFAULT_SETTINGS.backendUrl).replace(/\/+$/, ''),
    token: stored.token || '',
  };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    if (msg.type === 'getSettings') {
      const settings = await getSettings();
      sendResponse({ ok: true, settings: { backendUrl: settings.backendUrl, hasToken: Boolean(settings.token) } });
      return;
    }

    if (msg.type === 'api') {
      try {
        const { backendUrl, token } = await getSettings();
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers.Authorization = `Bearer ${token}`;

        const resp = await fetch(backendUrl + msg.path, {
          method: msg.method || 'GET',
          headers,
          body: msg.body !== undefined ? JSON.stringify(msg.body) : undefined,
        });

        let data = null;
        const text = await resp.text();
        try {
          data = text ? JSON.parse(text) : null;
        } catch {
          data = { raw: text.slice(0, 500) };
        }
        sendResponse({ ok: resp.ok, status: resp.status, data });
      } catch (err) {
        sendResponse({ ok: false, status: 0, data: null, error: String(err && err.message || err) });
      }
      return;
    }

    sendResponse({ ok: false, error: `Unknown message type: ${msg.type}` });
  })();

  return true; // async sendResponse
});
