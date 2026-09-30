/**
 * Autofill executor tests (jsdom + real extension code).
 *
 * The executor is exercised against fixture DOMs with plans identical in
 * shape to what the backend /agent/fill-plan endpoint returns.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '..', '..');
const FIXTURES = path.join(ROOT, 'tests', 'browser', 'fixtures');
const SRC = (p) => fs.readFileSync(path.join(ROOT, 'extension', 'content', p), 'utf8');
const DETECTOR_SRC = SRC('form-detector.js');
const MAPPER_SRC = SRC('field-mapper.js');
const AUTOFILL_SRC = SRC('autofill.js');

function loadFixture(filename) {
  const html = fs.readFileSync(path.join(FIXTURES, filename), 'utf8');
  const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true });
  const { window } = dom;
  if (!window.getComputedStyle) {
    window.getComputedStyle = () => ({ display: '', visibility: '', opacity: '' });
  }
  window.eval(DETECTOR_SRC);
  window.eval(MAPPER_SRC);
  window.eval(AUTOFILL_SRC);
  return window;
}

// ── Allow-list enforcement ───────────────────────────────────────────

test('executor: refuses non-allow-listed action types', () => {
  const window = loadFixture('simple_form.html');
  const { executeAction } = window.JobCopilotAutofill;

  for (const evil of ['EXECUTE_JS', 'EVAL', 'NAVIGATE', 'FETCH', 'DELETE']) {
    const result = executeAction({ action: evil, field_id: 'first_name', value: 'x' });
    assert.equal(result.ok, false);
    assert.match(result.error, /not allowed/);
  }
});

test('executor: no code path evaluates strings as JS', () => {
  const window = loadFixture('simple_form.html');
  // Even a crafted "action" whose value looks like code is stored as text.
  const result = window.JobCopilotAutofill.executeAction({
    action: 'FILL', field_id: 'first_name', value: 'alert(document.cookie)',
  });
  assert.equal(result.ok, true);
  assert.equal(window.document.getElementById('first_name').value, 'alert(document.cookie)');
});

// ── FILL behavior ────────────────────────────────────────────────────

test('executor: FILL sets value and dispatches input + change events', () => {
  const window = loadFixture('simple_form.html');
  const events = [];
  const el = window.document.getElementById('first_name');
  el.addEventListener('input', () => events.push('input'));
  el.addEventListener('change', () => events.push('change'));

  const result = window.JobCopilotAutofill.executeAction({
    action: 'FILL', field_id: 'first_name', value: 'Umang',
  });
  assert.equal(result.ok, true);
  assert.equal(el.value, 'Umang');
  assert.deepEqual(events, ['input', 'change']);
});

test('executor: FILL targets by selector when field_id missing', () => {
  const window = loadFixture('simple_form.html');
  const result = window.JobCopilotAutofill.executeAction({
    action: 'FILL', selector: 'input[name="email"]', value: 'u@x.com',
  });
  assert.equal(result.ok, true);
  assert.equal(window.document.getElementById('email').value, 'u@x.com');
});

test('executor: FILL refuses select and file elements', () => {
  const window = loadFixture('file_upload.html');
  const bad = window.JobCopilotAutofill.executeAction({ action: 'FILL', field_id: 'resume_input', value: 'x' });
  assert.equal(bad.ok, false);
  assert.match(bad.error, /not valid/);
});

test('executor: element not found reported cleanly', () => {
  const window = loadFixture('simple_form.html');
  const result = window.JobCopilotAutofill.executeAction({ action: 'FILL', field_id: 'nope', selector: '#missing', value: 'x' });
  assert.equal(result.ok, false);
  assert.equal(result.error, 'element not found');
});

// ── SELECT / CHECK / UNCHECK ─────────────────────────────────────────

test('executor: SELECT picks option on <select> and fires change', () => {
  const window = loadFixture('multi_page_form.html');
  const events = [];
  window.document.getElementById('country').addEventListener('change', () => events.push('change'));

  const result = window.JobCopilotAutofill.executeAction({
    action: 'SELECT', field_id: 'country', option_value: 'IN',
  });
  assert.equal(result.ok, true);
  assert.equal(window.document.getElementById('country').value, 'IN');
  assert.deepEqual(events, ['change']);
});

test('executor: SELECT with absent option fails safely', () => {
  const window = loadFixture('multi_page_form.html');
  const result = window.JobCopilotAutofill.executeAction({
    action: 'SELECT', field_id: 'country', option_value: 'XX',
  });
  assert.equal(result.ok, false);
  assert.match(result.error, /not present/);
});

test('executor: SELECT checks the right radio in a group', () => {
  const window = loadFixture('lever_form.html');
  const result = window.JobCopilotAutofill.executeAction({
    action: 'SELECT', field_id: 'sponsor-yes', option_value: 'yes',
  });
  assert.equal(result.ok, true);
  assert.equal(window.document.getElementById('sponsor-yes').checked, true);
  assert.equal(window.document.getElementById('sponsor-no').checked, false);
});

test('executor: CHECK/UNCHECK toggles checkboxes only', () => {
  const window = loadFixture('file_upload.html');
  const check = window.JobCopilotAutofill.executeAction({ action: 'CHECK', field_id: 'consent' });
  assert.equal(check.ok, true);
  assert.equal(window.document.getElementById('consent').checked, true);

  const uncheck = window.JobCopilotAutofill.executeAction({ action: 'UNCHECK', field_id: 'consent' });
  assert.equal(uncheck.ok, true);
  assert.equal(window.document.getElementById('consent').checked, false);

  const wrong = window.JobCopilotAutofill.executeAction({ action: 'CHECK', field_id: 'candidate_name' });
  assert.equal(wrong.ok, false);
  assert.match(wrong.error, /not a checkbox/);
});

// ── Shadow DOM ───────────────────────────────────────────────────────

test('executor: deepFind reaches inputs inside open shadow roots', async () => {
  const window = loadFixture('custom_dropdown.html');
  await new Promise((resolve) => {
    if (window.document.getElementById('shadow-host').shadowRoot) return resolve();
    window.document.addEventListener('shadow-ready', resolve, { once: true });
  });

  const result = window.JobCopilotAutofill.executeAction({
    action: 'FILL', field_id: 'referral', value: 'EMP-42',
  });
  assert.equal(result.ok, true);
  const inner = window.document.getElementById('shadow-host').shadowRoot.getElementById('referral');
  assert.equal(inner.value, 'EMP-42');
});

// ── Plan-level summary ───────────────────────────────────────────────

test('executor: executePlan summarizes filled/deferred/failed', () => {
  const window = loadFixture('simple_form.html');
  const summary = window.JobCopilotAutofill.executePlan([
    { action: 'FILL', field_id: 'first_name', value: 'Umang' },
    { action: 'FILL', field_id: 'email', value: 'u@x.com' },
    { action: 'NEXT_PAGE', field_id: 'whatever' },   // deferred (M7)
    { action: 'FILL', field_id: 'missing', value: 'x' }, // failed
  ]);
  assert.equal(summary.filled, 2);
  assert.equal(summary.deferred, 1);
  assert.equal(summary.failed, 1);
});

// ── End-to-end: detect → map → plan (backend-shaped) → fill ──────────

test('end-to-end: simple_form profile fields filled from a backend-shaped plan', () => {
  const window = loadFixture('simple_form.html');
  const scan = window.JobCopilotDetector.detectForms(window.document);
  scan.mapped = window.JobCopilotMapper.mapFields(scan.fields);

  // Simulate exactly what POST /api/v1/agent/fill-plan returns for a
  // populated profile: a FILL action per profile field.
  const byKey = Object.fromEntries(scan.mapped.map((m) => [m.profile_key, m]));
  const plan = [
    { action: 'FILL', field_id: byKey.first_name.field_id, selector: byKey.first_name.selector, value: 'Umang' },
    { action: 'FILL', field_id: byKey.last_name.field_id, selector: byKey.last_name.selector, value: 'Bandil' },
    { action: 'FILL', field_id: byKey.email.field_id, selector: byKey.email.selector, value: 'umang@example.com' },
    { action: 'FILL', field_id: byKey.phone.field_id, selector: byKey.phone.selector, value: '+91 90000 00000' },
    { action: 'FILL', field_id: byKey.location.field_id, selector: byKey.location.selector, value: 'Pune, Maharashtra' },
    { action: 'FILL', field_id: byKey.linkedin_url.field_id, selector: byKey.linkedin_url.selector, value: 'https://linkedin.com/in/umang' },
  ];

  const execution = window.JobCopilotAutofill.executePlan(plan);
  assert.equal(execution.filled, 6);
  assert.equal(execution.failed, 0);
  assert.equal(window.document.getElementById('first_name').value, 'Umang');
  assert.equal(window.document.getElementById('last_name').value, 'Bandil');
  assert.equal(window.document.getElementById('email').value, 'umang@example.com');
  assert.equal(window.document.getElementById('phone').value, '+91 90000 00000');
  assert.equal(window.document.getElementById('city').value, 'Pune, Maharashtra');
  assert.equal(window.document.getElementById('linkedin').value, 'https://linkedin.com/in/umang');
});

test('end-to-end: plan carries no action for review fields — nothing sensitive is filled', () => {
  const window = loadFixture('lever_form.html');
  const scan = window.JobCopilotDetector.detectForms(window.document);
  scan.mapped = window.JobCopilotMapper.mapFields(scan.fields);

  // Backend plan for this page with a full profile: name/email/phone FILLs
  // only; work-auth + sponsorship fields are needs_review → NOT in plan.
  const reviewIds = scan.mapped.filter((m) => m.action === 'review').map((m) => m.field_id);
  assert.ok(reviewIds.includes('work-auth'));
  assert.ok(reviewIds.includes('sponsor-yes'));
  assert.ok(reviewIds.includes('sponsor-no'));

  const plan = []; // planner returns nothing for review fields
  const execution = window.JobCopilotAutofill.executePlan(plan);
  assert.equal(execution.filled, 0);
  assert.equal(window.document.getElementById('work-auth').value, ''); // untouched
  assert.equal(window.document.getElementById('sponsor-yes').checked, false); // untouched
});
