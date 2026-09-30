/**
 * Job Copilot Assistant — universal form detector.
 *
 * Extracts a normalized description of every visible form field on the
 * page, including Shadow DOM penetration. No site-specific logic here —
 * detection is generic by design; per-ATS quirks live in backend adapters
 * (Milestone 6).
 *
 * Exposes: window.JobCopilotDetector (content scripts), and
 * module.exports if a module system is present (tests).
 */

(function initDetector(global) {
  'use strict';

  const FIELD_SELECTOR = [
    'input',
    'textarea',
    'select',
  ].join(',');

  const IGNORED_TYPES = new Set(['hidden', 'submit', 'button', 'image', 'reset', 'file-hidden']);
  const FORM_CONTROLS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

  function cssEscape(value) {
    if (global.CSS && typeof global.CSS.escape === 'function') return global.CSS.escape(value);
    return String(value).replace(/(["\\])/g, '\\$1');
  }

  function isVisible(el) {
    if (!(el instanceof global.Element)) return false;
    if (!el.isConnected) return false;
    if (el.getAttribute('aria-hidden') === 'true') return false;
    if (el.hasAttribute('disabled') && el.tagName !== 'OPTION') return false;

    const style = (global.getComputedStyle && el.ownerDocument.defaultView)
      ? global.getComputedStyle(el)
      : null;
    if (style && (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0')) {
      return false;
    }
    // Zero-size fields with no content are usually invisible framework ghosts.
    // Form controls are exempt (headless test environments report 0×0 rects).
    const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : { width: 1, height: 1 };
    if (rect.width === 0 && rect.height === 0 && !FORM_CONTROLS.has(el.tagName)) return false;
    return true;
  }

  function findLabel(el, root) {
    // 1. <label for="id">
    if (el.id) {
      const explicit = root.querySelector(`label[for="${cssEscape(el.id)}"]`);
      if (explicit) return explicit.textContent.trim();
    }
    // 2. wrapping <label>
    const wrap = el.closest('label');
    if (wrap) return wrap.textContent.trim();

    // 3. aria-label / aria-labelledby
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const parts = labelledBy
        .split(/\s+/)
        .map((id) => root.querySelector(`#${cssEscape(id)}`))
        .filter(Boolean)
        .map((n) => n.textContent.trim())
        .filter(Boolean);
      if (parts.length) return parts.join(' ');
    }

    // 4. Nearby text: previous sibling, parent's text, table header cell
    const prev = el.previousElementSibling;
    if (prev && prev.textContent && prev.textContent.trim().length <= 200) {
      return prev.textContent.trim();
    }
    const cell = el.closest('td, th');
    if (cell) {
      const row = cell.closest('tr');
      if (row && row.cells && row.cells[0] && row.cells[0] !== cell) {
        return row.cells[0].textContent.trim();
      }
    }
    const parentText = el.parentElement ? el.parentElement.textContent : '';
    const short = parentText.trim();
    if (short && short.length <= 200) return short;

    return '';
  }

  function sectionHeadingFor(el) {
    const container = el.closest('section, fieldset, div[data-section], .section, [role="group"]');
    if (!container) return '';
    const heading = container.querySelector('h1, h2, h3, h4, h5, legend, [data-section-title]');
    return heading ? heading.textContent.trim().slice(0, 120) : '';
  }

  function cssSelectorFor(el) {
    if (el.id) return `#${cssEscape(el.id)}`;
    const name = el.getAttribute('name');
    if (name) return `${el.tagName.toLowerCase()}[name="${name}"]`;
    const type = el.getAttribute('type');
    if (type) {
      const same = el.ownerDocument.querySelectorAll(`${el.tagName.toLowerCase()}[type="${type}"]`);
      const idx = Array.prototype.indexOf.call(same, el);
      if (idx > 0) return `${el.tagName.toLowerCase()}[type="${type}"]:nth-of-type(${idx + 1})`;
    }
    return el.tagName.toLowerCase();
  }

  function detectField(el) {
    const tag = el.tagName.toLowerCase();
    const type = tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : tag;
    if (IGNORED_TYPES.has(type)) return null;

    const options = [];
    if (tag === 'select') {
      for (const opt of el.options) {
        options.push({ value: opt.value, label: opt.textContent.trim() });
      }
    } else if (type === 'checkbox' || type === 'radio') {
      // Radio groups: collect sibling options sharing the same name
      if (type === 'radio' && el.name) {
        const group = el.ownerDocument.querySelectorAll(`input[type="radio"][name="${cssEscape(el.name)}"]`);
        const seen = new Set();
        for (const r of group) {
          const val = r.value;
          if (!seen.has(val)) {
            seen.add(val);
            options.push({ value: val, label: (findLabel(r, el.ownerDocument) || val) });
          }
        }
      }
    }

    const label = findLabel(el, el.ownerDocument);
    const field = {
      field_id: el.id || `f_${cssSelectorFor(el)}`,
      tag,
      type,
      label,
      name: el.getAttribute('name') || '',
      placeholder: el.getAttribute('placeholder') || '',
      aria_label: el.getAttribute('aria-label') || '',
      required: el.required || el.getAttribute('aria-required') === 'true' || /\*/.test(label),
      multiple: tag === 'select' && el.multiple,
      options,
      value: type === 'checkbox' ? String(el.checked) : (el.value || ''),
      section: sectionHeadingFor(el),
      selector: cssSelectorFor(el),
    };
    return field;
  }

  function deepQueryAll(root, selector, out) {
    out = out || [];
    root.querySelectorAll(selector).forEach((el) => out.push(el));
    // Penetrate open shadow roots (common in modern ATS UIs)
    root.querySelectorAll('*').forEach((el) => {
      if (el.shadowRoot) deepQueryAll(el.shadowRoot, selector, out);
    });
    return out;
  }

  function detectForms(doc) {
    doc = doc || global.document;
    const fields = [];
    const seen = new Set();

    const candidates = deepQueryAll(doc, FIELD_SELECTOR);
    for (const el of candidates) {
      if (seen.has(el)) continue;
      seen.add(el);
      if (!isVisible(el)) continue;
      const field = detectField(el);
      if (field) fields.push(field);
    }

    return {
      url: doc.defaultView && doc.defaultView.location ? doc.defaultView.location.href : '',
      title: doc.title || '',
      detected_at: new Date().toISOString(),
      field_count: fields.length,
      fields,
    };
  }

  const api = { detectForms, detectField, findLabel, isVisible };
  global.JobCopilotDetector = api;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})(typeof window !== 'undefined' ? window : globalThis);
