/** Options page: backend URL + JWT storage with connection verification. */

const $ = (id) => document.getElementById(id);

async function load() {
  const { backendUrl = 'http://localhost:8000', token = '' } = await chrome.storage.local.get(['backendUrl', 'token']);
  $('backend-url').value = backendUrl;
  $('token').value = token;
}

async function save() {
  const backendUrl = $('backend-url').value.trim().replace(/\/+$/, '') || 'http://localhost:8000';
  const token = $('token').value.trim();
  await chrome.storage.local.set({ backendUrl, token });

  const status = $('status');
  if (token) {
    status.textContent = 'Saved. Checking connection…';
    const resp = await chrome.runtime.sendMessage({ type: 'api', path: '/api/v1/ai/health', method: 'GET' });
    if (resp?.ok && resp.data?.connected) {
      status.textContent = `Saved — connected (${resp.data.model || 'local AI online'})`;
    } else if (resp?.ok && resp.status === 401) {
      status.textContent = 'Saved — but the token was rejected (401). Re-copy it from the web app.';
    } else {
      status.textContent = 'Saved — backend not reachable yet (is it running?)';
    }
  } else {
    status.textContent = 'Saved (no token set yet).';
  }
}

$('save').addEventListener('click', save);
load();
