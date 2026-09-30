/**
 * Job Copilot Assistant — autofill executor.
 *
 * Executes ONLY allow-listed actions from a backend-approved plan. The
 * executor enforces the same allow-list as the backend (defense in depth):
 * any action whose type is not in ALLOWED_ACTIONS is refused, and there is
 * no code path that evaluates strings as JavaScript.
 *
 * Fills use native value setters plus input/change events so React- and
 * framework-controlled forms register the change.
 *
 * Exposes window.JobCopilotAutofill and module.exports (tests).
 */

(function initAutofill(global) {
  'use strict';

  // Must mirror backend app/agent/actions.py ActionType.
  const ALLOWED_ACTIONS = new Set([
    'FILL', 'SELECT', 'CHECK', 'UNCHECK', 'CLICK', 'SCROLL',
    'WAIT', 'EXTRACT', 'UPLOAD', 'NEXT_PAGE', 'STOP',
  ]);

  const ORCHESTRATED_ACTIONS = new Set(['SCROLL', 'WAIT', 'NEXT_PAGE', 'STOP', 'UPLOAD']);

  function deepFind(selector, field_id) {
    const doc = global.document;
    let el = null;
    if (field_id) {
      el = doc.getElementById(field_id);
      if (el) return el;
    }
    if (selector) {
      el = doc.querySelector(selector);
      if (el) return el;
    }
    // Search open shadow roots (detector can see fields the DOM tree hides).
    const hosts = [];
    const collect = (root) => {
      root.querySelectorAll('*').forEach((n) => {
        if (n.shadowRoot) hosts.push(n.shadowRoot);
      });
    };
    collect(doc);
    for (const root of hosts) {
      if (field_id) {
        el = root.querySelector(`#${field_id.replace(/(["\\])/g, '\\$1')}`);
        if (el) return el;
      }
      if (selector) {
        el = root.querySelector(selector);
        if (el) return el;
      }
      collect(root);
    }
    return null;
  }

  function setNativeValue(el, value) {
    const proto = el.tagName === 'TEXTAREA'
      ? global.HTMLTextAreaElement.prototype
      : global.HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
    if (descriptor && descriptor.set) {
      descriptor.set.call(el, value);
    } else {
      el.value = value;
    }
    el.dispatchEvent(new global.Event('input', { bubbles: true }));
    el.dispatchEvent(new global.Event('change', { bubbles: true }));
  }

  function executeAction(action) {
    if (!action || !ALLOWED_ACTIONS.has(action.action)) {
      return { ok: false, field_id: action && action.field_id, error: `action type not allowed: ${action && action.action}` };
    }

    if (ORCHESTRATED_ACTIONS.has(action.action)) {
      // Multi-page orchestration (M7) handles these; harmless no-op now.
      return { ok: true, field_id: action.field_id, deferred: action.action };
    }

    const el = deepFind(action.selector, action.field_id);
    if (!el) return { ok: false, field_id: action.field_id, error: 'element not found' };

    try {
      switch (action.action) {
        case 'FILL': {
          if (el.tagName === 'SELECT' || el.type === 'file') {
            return { ok: false, field_id: action.field_id, error: `FILL not valid for ${el.tagName.toLowerCase()}` };
          }
          setNativeValue(el, action.value ?? '');
          return { ok: true, field_id: action.field_id };
        }
        case 'SELECT': {
          if (el.tagName === 'SELECT') {
            el.value = action.option_value ?? '';
            if (el.value !== (action.option_value ?? '')) {
              return { ok: false, field_id: action.field_id, error: `option '${action.option_value}' not present` };
            }
          } else if (el.type === 'radio') {
            if (el.value !== action.option_value) {
              return { ok: false, field_id: action.field_id, error: 'radio value mismatch' };
            }
            el.checked = true;
          } else {
            return { ok: false, field_id: action.field_id, error: 'SELECT not valid for this element' };
          }
          el.dispatchEvent(new global.Event('change', { bubbles: true }));
          return { ok: true, field_id: action.field_id };
        }
        case 'CHECK':
        case 'UNCHECK': {
          if (el.type !== 'checkbox') {
            return { ok: false, field_id: action.field_id, error: 'not a checkbox' };
          }
          el.checked = action.action === 'CHECK';
          el.dispatchEvent(new global.Event('change', { bubbles: true }));
          return { ok: true, field_id: action.field_id };
        }
        case 'CLICK': {
          el.click();
          return { ok: true, field_id: action.field_id };
        }
        case 'EXTRACT': {
          const value = el.value !== undefined ? el.value : el.textContent;
          return { ok: true, field_id: action.field_id, extracted: value };
        }
        default:
          return { ok: false, field_id: action.field_id, error: `unhandled action ${action.action}` };
      }
    } catch (err) {
      return { ok: false, field_id: action.field_id, error: String((err && err.message) || err) };
    }
  }

  function executePlan(actions) {
    const results = [];
    for (const action of actions || []) {
      const result = executeAction(action);
      results.push(result);
    }
    return {
      results,
      filled: results.filter((r) => r.ok && !r.deferred).length,
      deferred: results.filter((r) => r.deferred).length,
      failed: results.filter((r) => !r.ok).length,
    };
  }

  const api = { executePlan, executeAction, deepFind, setNativeValue, ALLOWED_ACTIONS };
  global.JobCopilotAutofill = api;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})(typeof window !== 'undefined' ? window : globalThis);
