/**
 * Answer-engine client tests (jsdom + real extension code).
 *
 * answer.js is exercised with proposals shaped exactly like what the
 * backend /agent/answer endpoint returns. The trust rule under test:
 * ONLY proposals with requires_review=false AND a fill_action touch the
 * DOM, and they do it through the M4 allow-list executor.
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
const ANSWER_SRC = SRC('answer.js');

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
  window.eval(ANSWER_SRC);
  return window;
}

// ── buildPayload ─────────────────────────────────────────────────────

test('buildPayload: maps detector field + mapper classification to API shape', () => {
  const window = loadFixture('simple_form.html');
  const { document } = window;

  const field = {
    field_id: 'why_us', selector: '#why_us', tag: 'textarea', type: 'textarea',
    label: 'Why do you want to work here?', name: 'why_us', placeholder: '',
    aria_label: '', options: [],
  };
  const mapped = window.JobCopilotMapper.classifyField(field);

  const payload = window.JobCopilotAnswer.buildPayload(field, mapped, 'Job desc text');
  assert.equal(payload.question, 'Why do you want to work here?');
  assert.equal(payload.field_type, 'textarea');
  assert.equal(payload.client_policy, 'ai');
  assert.equal(payload.field_id, 'why_us');
  assert.deepEqual(payload.field_options, []);
  assert.equal(payload.job_description, 'Job desc text');
});

test('buildPayload: includes select options as value/label pairs', () => {
  const window = loadFixture('simple_form.html');
  const field = {
    field_id: 'remote', selector: '#remote', tag: 'select', type: 'select',
    label: 'Work setup', name: 'remote', placeholder: '', aria_label: '',
    options: [{ value: '1', label: 'Remote' }, { value: '2', label: 'Hybrid' }],
  };
  const mapped = window.JobCopilotMapper.classifyField(field);
  const payload = window.JobCopilotAnswer.buildPayload(field, mapped, '');
  assert.deepEqual(payload.field_options, [
    { value: '1', label: 'Remote' },
    { value: '2', label: 'Hybrid' },
  ]);
});

test('mapper: sensitive question classifies as review (client pre-filter)', () => {
  const window = loadFixture('simple_form.html');
  const field = {
    field_id: 'sponsor', selector: '#sponsor', tag: 'select', type: 'select',
    label: 'Do you require visa sponsorship?', name: 'sponsor', placeholder: '',
    aria_label: '', options: [{ value: 'yes', label: 'Yes' }],
  };
  const mapped = window.JobCopilotMapper.classifyField(field);
  assert.equal(mapped.action, 'review');
});

// ── summarizeProposals: trust rules ──────────────────────────────────

test('summarizeProposals: approved proposal fills the field', () => {
  const window = loadFixture('simple_form.html');

  const summary = window.JobCopilotAnswer.summarizeProposals([
    {
      question: 'Why do you want to work here?',
      policy: 'llm_generated',
      answer: 'I admire your developer tools.',
      confidence: 0.92,
      requires_review: false,
      source: 'llm',
      fill_action: { action: 'FILL', field_id: 'first_name', value: 'Umang' },
    },
  ]);

  assert.equal(summary.filled, 1);
  assert.equal(summary.needs_review, 0);
  assert.equal(window.document.getElementById('first_name').value, 'Umang');
});

test('summarizeProposals: requires_review proposals NEVER touch the DOM', () => {
  const window = loadFixture('simple_form.html');

  const summary = window.JobCopilotAnswer.summarizeProposals([
    {
      question: 'Describe your ideal role.',
      policy: 'llm_generated',
      answer: 'A drafted answer shown to the human.',
      confidence: 0.3,
      requires_review: true, // low confidence → review
      source: 'llm',
      fill_action: { action: 'FILL', field_id: 'first_name', value: 'SHOULD NOT FILL' },
    },
  ]);

  assert.equal(summary.needs_review, 1);
  assert.equal(summary.filled, 0);
  assert.equal(window.document.getElementById('first_name').value, '');
});

test('summarizeProposals: sensitive questions queue for human, never fill', () => {
  const window = loadFixture('simple_form.html');

  const summary = window.JobCopilotAnswer.summarizeProposals([
    {
      question: 'Do you require sponsorship?',
      policy: 'user_confirmation_required',
      answer: null,
      confidence: 0,
      requires_review: true,
      source: 'none',
      fill_action: null,
    },
  ]);

  assert.equal(summary.needs_answer, 1);
  assert.equal(summary.needs_review, 0);
  assert.equal(summary.filled, 0);
});

test('summarizeProposals: proposal without fill_action counts as failed, fills nothing', () => {
  const window = loadFixture('simple_form.html');

  const summary = window.JobCopilotAnswer.summarizeProposals([
    {
      question: 'Q', policy: 'llm_generated', answer: 'A',
      confidence: 0.9, requires_review: false, source: 'llm',
      fill_action: null, // backend refused to validate an action
    },
  ]);

  assert.equal(summary.filled, 0);
  assert.equal(summary.failed, 1);
  assert.equal(window.document.getElementById('first_name').value, '');
});

test('summarizeProposals: SELECT proposal fills via allow-list executor', () => {
  const window = loadFixture('greenhouse_form.html');
  // Pick a select field present in the greenhouse fixture.
  const select = window.document.querySelector('select');
  assert.ok(select, 'fixture must contain a select');

  const summary = window.JobCopilotAnswer.summarizeProposals([
    {
      question: 'How did you hear about us?',
      policy: 'llm_generated',
      answer: 'Indeed',
      confidence: 0.9,
      requires_review: false,
      source: 'llm',
      fill_action: {
        action: 'SELECT',
        field_id: select.id,
        option_value: select.options[0] ? select.options[0].value : 'indeed',
      },
    },
  ]);

  assert.equal(summary.filled, 1);
  assert.equal(select.value, select.options[0].value);
});

test('summarizeProposals: mixed batch tallies correctly', () => {
  const window = loadFixture('simple_form.html');

  const summary = window.JobCopilotAnswer.summarizeProposals([
    { question: 'q1', policy: 'llm_generated', answer: 'a1', confidence: 0.9, requires_review: false, source: 'llm', fill_action: { action: 'FILL', field_id: 'first_name', value: 'U' } },
    { question: 'q2', policy: 'llm_generated', answer: 'a2', confidence: 0.2, requires_review: true, source: 'llm', fill_action: null },
    { question: 'q3', policy: 'user_confirmation_required', answer: null, confidence: 0, requires_review: true, source: 'none', fill_action: null },
    { question: 'q4', policy: 'profile_only', answer: null, confidence: 0, requires_review: true, source: 'none', fill_action: null },
  ]);

  assert.equal(summary.filled, 1);
  assert.equal(summary.needs_review, 2); // q2 (low confidence) + q4 (empty profile)
  assert.equal(summary.needs_answer, 1); // q3 (sensitive)
  assert.equal(summary.details.length, 4);
});

test('answer API exposes only the intended surface', () => {
  const window = loadFixture('simple_form.html');
  assert.deepEqual(
    Object.keys(window.JobCopilotAnswer).sort(),
    ['SENSITIVE', 'buildPayload', 'summarizeProposals'],
  );
});
