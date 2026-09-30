/** Job Copilot popup: shows connection status and per-page scan summary. */

const $ = (id) => document.getElementById(id);

function setStatus(kind, text) {
  const el = $('ai-status');
  el.className = `status ${kind}`;
  el.textContent = text;
}

async function checkConnection() {
  const resp = await chrome.runtime.sendMessage({ type: 'getSettings' });
  if (!resp?.ok) {
    setStatus('offline', 'error');
    return false;
  }
  $('backend-label').textContent = resp.settings.backendUrl.replace(/^https?:\/\//, '');

  if (!resp.settings.hasToken) {
    setStatus('offline', 'no token');
    $('setup-hint').classList.remove('hidden');
    return false;
  }

  const health = await chrome.runtime.sendMessage({
    type: 'api',
    path: '/api/v1/ai/health',
    method: 'GET',
  });
  if (health?.ok && health.data?.connected) {
    setStatus('online', health.data.model || 'connected');
    return true;
  }
  setStatus('offline', 'offline');
  return false;
}

async function scanPage() {
  $('scan-btn').disabled = true;
  $('scan-btn').textContent = 'Scanning…';
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) return;

    let resp;
    try {
      resp = await chrome.tabs.sendMessage(tab.id, { type: 'scan' });
    } catch {
      // Content script not injected (e.g. chrome:// page) — inject then retry.
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content/form-detector.js', 'content/field-mapper.js', 'content/content.js'] });
      resp = await chrome.tabs.sendMessage(tab.id, { type: 'scan' });
    }

    if (resp?.ok) {
      const s = resp.summary;
      $('summary-title').textContent = s.title || s.url;
      $('c-profile').textContent = s.actions.profile || 0;
      $('c-memory').textContent = s.actions.memory || 0;
      $('c-ai').textContent = s.actions.ai || 0;
      $('c-review').textContent = s.actions.review || 0;
      $('scan-summary').classList.remove('hidden');
    }
  } finally {
    $('scan-btn').disabled = false;
    $('scan-btn').textContent = 'Scan this page';
  }
}

$('scan-btn').addEventListener('click', scanPage);
$('options-btn').addEventListener('click', () => chrome.runtime.openOptionsPage());
$('open-options').addEventListener('click', (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

checkConnection();
