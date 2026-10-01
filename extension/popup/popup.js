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

async function autofillPage() {
  const btn = $('autofill-btn');
  btn.disabled = true;
  btn.textContent = 'Filling…';
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) return;

    let resp;
    try {
      resp = await chrome.tabs.sendMessage(tab.id, { type: 'autofill' });
    } catch {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['content/form-detector.js', 'content/field-mapper.js', 'content/autofill.js', 'content/answer.js', 'content/content.js'],
      });
      resp = await chrome.tabs.sendMessage(tab.id, { type: 'autofill' });
    }

    if (resp?.ok) {
      $('autofill-summary').textContent =
        `${resp.execution.filled} filled from your profile`;
      $('f-filled').textContent = resp.execution.filled;
      $('f-skipped').textContent = resp.plan_summary.skipped;
      $('f-review').textContent = resp.plan_summary.needs_review;
      $('f-ai').textContent = resp.plan_summary.needs_ai;
      $('f-failed').textContent = resp.execution.failed;

      // Answer-engine proposals (M5): approved fills + review queue.
      if (resp.answers) {
        const a = resp.answers;
        if (a.filled > 0) {
          $('autofill-summary').textContent +=
            ` + ${a.filled} AI-drafted (approved)`;
        }
        if (a.needs_answer > 0) {
          $('autofill-summary').textContent +=
            ` · ${a.needs_answer} sensitive — answer these yourself`;
        } else if (a.needs_review > 0) {
          $('autofill-summary').textContent +=
            ` · ${a.needs_review} drafted for your review`;
        }
      }

      $('autofill-result').classList.remove('hidden');
    } else {
      $('autofill-summary').textContent = resp?.error || 'Could not reach the backend';
      $('autofill-result').classList.remove('hidden');
    }
  } finally {
    btn.disabled = false;
    btn.textContent = 'Autofill profile fields';
  }
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
$('autofill-btn').addEventListener('click', autofillPage);
$('options-btn').addEventListener('click', () => chrome.runtime.openOptionsPage());
$('open-options').addEventListener('click', (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

checkConnection();
