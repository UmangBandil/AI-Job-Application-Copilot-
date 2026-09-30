/**
 * Job Copilot Assistant — content script entry point.
 *
 * Detects forms on application pages, reports them to the popup/background,
 * and executes ONLY actions the backend approved (M4+). It never evaluates
 * strings as code and never navigates on its own.
 */

(function initContent() {
  'use strict';

  let lastScan = null;

  function scan() {
    const scanResult = window.JobCopilotDetector.detectForms(document);
    scanResult.mapped = window.JobCopilotMapper.mapFields(scanResult.fields);
    lastScan = scanResult;
    return scanResult;
  }

  function summarize(scanResult) {
    const counts = { profile: 0, memory: 0, ai: 0, review: 0, unknown: 0 };
    for (const m of scanResult.mapped) counts[m.action] = (counts[m.action] || 0) + 1;
    return {
      url: scanResult.url,
      title: scanResult.title,
      field_count: scanResult.field_count,
      actions: counts,
    };
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === 'scan') {
      const result = scan();
      sendResponse({ ok: true, scan: result, summary: summarize(result) });
      return true;
    }
    if (msg.type === 'summary') {
      if (!lastScan) scan();
      sendResponse({ ok: true, summary: summarize(lastScan) });
      return true;
    }
    return false;
  });

  // Expose for tests / manual debugging in the page console.
  window.JobCopilotContent = { scan, summarize };
})();
