/**
 * Job Copilot Assistant — answer-engine client (M5).
 *
 * Asks the backend for a review-gated answer proposal for ONE field and
 * applies it ONLY if the backend explicitly approved the fill via a
 * validated fill_action. Key trust rules:
 *
 *   - requires_review=true  → the field is NEVER filled automatically;
 *     the proposal goes to the review queue (M8 UI) instead.
 *   - No fill_action        → nothing touches the DOM.
 *   - fill_action is executed through JobCopilotAutofill (same M4
 *     allow-list executor), so no new DOM powers are introduced here.
 *   - Sensitive fields always return requires_review=true (server-enforced)
 *     and are listed for human answering.
 *
 * Exposes window.JobCopilotAnswer and module.exports (tests).
 */

(function initAnswer(global) {
  'use strict';

  // Fields the user must answer themselves (server policy enforces this
  // too; this list only shapes the summary the popup shows).
  const SENSITIVE = 'user_confirmation_required';

  function buildPayload(field, mapped, jobDescription) {
    return {
      question: field.label || field.name || field.field_id,
      field_type: field.type || 'text',
      field_options: (field.options || []).map((o) => ({
        value: o.value || '',
        label: o.label || '',
      })),
      field_id: field.field_id,
      selector: field.selector || null,
      client_policy: mapped && mapped.action ? mapped.action : null,
      job_description: jobDescription || '',
    };
  }

  function summarizeProposals(proposals) {
    const summary = {
      filled: 0,
      needs_review: 0,
      needs_answer: 0, // sensitive → human must answer
      failed: 0,
      details: [],
    };

    for (const p of proposals || []) {
      const detail = {
        question: p.question,
        answer: p.answer,
        confidence: p.confidence,
        source: p.source,
        requires_review: p.requires_review,
        policy: p.policy,
        notes: p.notes,
      };

      if (p.requires_review) {
        if (p.policy === SENSITIVE) {
          summary.needs_answer += 1;
        } else {
          summary.needs_review += 1;
        }
        summary.details.push(detail);
        continue; // never filled
      }

      if (p.fill_action) {
        const result = global.JobCopilotAutofill.executeAction(p.fill_action);
        if (result.ok) {
          summary.filled += 1;
        } else {
          summary.failed += 1;
          detail.error = result.error;
        }
        summary.details.push(detail);
        continue;
      }

      summary.failed += 1;
      summary.details.push(detail);
    }

    return summary;
  }

  const api = { buildPayload, summarizeProposals, SENSITIVE };
  global.JobCopilotAnswer = api;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})(typeof window !== 'undefined' ? window : globalThis);
