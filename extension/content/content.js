/**
 * Job Copilot Assistant — content script entry point.
 *
 * Detects forms on application pages, reports them to the popup/background,
 * and executes ONLY actions the backend approved. It never evaluates
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

  // Ask the answer engine (M5) for review-gated proposals on the fields
  // the deterministic plan deferred. Sequential on purpose: one request
  // per field, no fan-out surprises on slow local LLMs.
  async function requestAnswers(scanResult, needsAi, jobDescription) {
    const answer = window.JobCopilotAnswer;
    if (!answer || !needsAi || needsAi.length === 0) return [];
    const proposals = [];
    for (const item of needsAi) {
      const field = scanResult.fields.find((f) => f.field_id === item.field_id);
      if (!field) continue;
      const mapped = scanResult.mapped.find((m) => m.field_id === item.field_id);
      try {
        const resp = await chrome.runtime.sendMessage({
          type: 'api',
          path: '/api/v1/agent/answer',
          method: 'POST',
          body: answer.buildPayload(field, mapped, jobDescription),
        });
        if (resp?.ok) proposals.push(resp.data);
      } catch (_err) {
        // Answer engine offline — proposals just stay empty.
      }
    }
    return proposals;
  }

  async function autofill() {
    const scanResult = scan();

    // 1. Ask the backend for a validated, allow-listed action plan.
    const planResp = await chrome.runtime.sendMessage({
      type: 'api',
      path: '/api/v1/agent/fill-plan',
      method: 'POST',
      body: { fields: scanResult.fields.map((f) => ({
        field_id: f.field_id,
        selector: f.selector,
        tag: f.tag,
        type: f.type,
        label: f.label,
        name: f.name,
        placeholder: f.placeholder,
        aria_label: f.aria_label,
        options: f.options,
        action: (scanResult.mapped.find((m) => m.field_id === f.field_id) || {}).action || 'unknown',
        profile_key: (scanResult.mapped.find((m) => m.field_id === f.field_id) || {}).profile_key || null,
        reason: (scanResult.mapped.find((m) => m.field_id === f.field_id) || {}).reason || null,
      })) },
    });

    if (!planResp?.ok) {
      return { ok: false, error: (planResp && (planResp.error || planResp.data)) || 'backend unavailable', summary: summarize(scanResult) };
    }

    const plan = planResp.data;

    // 2. Execute only the backend-approved actions.
    const execution = window.JobCopilotAutofill.executePlan(plan.plan);

    // 3. Answer engine for deferred fields (review-gated proposals).
    const proposals = await requestAnswers(scanResult, plan.needs_ai, '');
    const answerSummary = window.JobCopilotAnswer
      ? window.JobCopilotAnswer.summarizeProposals(proposals)
      : null;

    return {
      ok: true,
      summary: summarize(scanResult),
      plan_summary: plan.summary,
      skipped: plan.skipped,
      needs_review: plan.needs_review,
      needs_ai: plan.needs_ai,
      execution,
      answers: answerSummary,
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
    if (msg.type === 'autofill') {
      autofill()
        .then((result) => sendResponse(result))
        .catch((err) => sendResponse({ ok: false, error: String((err && err.message) || err) }));
      return true; // async response
    }
    return false;
  });

  // Expose for tests / manual debugging in the page console.
  window.JobCopilotContent = { scan, summarize, autofill };
})();
