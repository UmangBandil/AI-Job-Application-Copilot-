/**
 * Extension content-script tests against local HTML fixtures (jsdom).
 *
 * Loads the real form-detector.js / field-mapper.js source into a jsdom
 * window so the exact shipping code is exercised. No Chrome, no network.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '..', '..');
const FIXTURES = path.join(ROOT, 'tests', 'browser', 'fixtures');
const DETECTOR_SRC = fs.readFileSync(path.join(ROOT, 'extension', 'content', 'form-detector.js'), 'utf8');
const MAPPER_SRC = fs.readFileSync(path.join(ROOT, 'extension', 'content', 'field-mapper.js'), 'utf8');
const AUTOFILL_SRC = fs.readFileSync(path.join(ROOT, 'extension', 'content', 'autofill.js'), 'utf8');
const CONTENT_SRC = fs.readFileSync(path.join(ROOT, 'extension', 'content', 'content.js'), 'utf8');

/** Load a fixture into jsdom with the real content scripts executed. */
function loadFixture(filename) {
  const html = fs.readFileSync(path.join(FIXTURES, filename), 'utf8');
  const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true });
  const { window } = dom;

  if (!window.getComputedStyle) {
    window.getComputedStyle = () => ({ display: '', visibility: '', opacity: '' });
  }

  window.eval(DETECTOR_SRC);
  window.eval(MAPPER_SRC);
  return window;
}

function scanFixture(filename) {
  const window = loadFixture(filename);
  const scan = window.JobCopilotDetector.detectForms(window.document);
  scan.mapped = window.JobCopilotMapper.mapFields(scan.fields);
  return { window, scan };
}

function byName(scan, name) {
  return scan.mapped.find((f) => f.field_id === name || f.selector.includes(`name="${name}"`));
}

// ── simple_form.html ─────────────────────────────────────────────────

test('simple_form: detects all six profile fields with labels', () => {
  const { scan } = scanFixture('simple_form.html');
  assert.equal(scan.field_count, 6);
  assert.deepEqual(
    scan.fields.map((f) => f.name).sort(),
    ['city', 'email', 'first_name', 'last_name', 'linkedin', 'phone'],
  );
  for (const f of scan.fields) assert.ok(f.label, `label missing for ${f.name}`);
});

test('simple_form: every field maps to a semantic profile key', () => {
  const { scan } = scanFixture('simple_form.html');
  const mapped = scan.mapped.filter((f) => f.action === 'profile');
  assert.equal(mapped.length, 6);
  assert.equal(byName(scan, 'first_name').profile_key, 'first_name');
  assert.equal(byName(scan, 'last_name').profile_key, 'last_name');
  assert.equal(byName(scan, 'email').profile_key, 'email');
  assert.equal(byName(scan, 'phone').profile_key, 'phone');
  assert.equal(byName(scan, 'city').profile_key, 'location');
  assert.equal(byName(scan, 'linkedin').profile_key, 'linkedin_url');
});

// ── greenhouse_form.html ─────────────────────────────────────────────

test('greenhouse_form: detects fields, select options, file input, required flags', () => {
  const { scan } = scanFixture('greenhouse_form.html');
  assert.ok(scan.field_count >= 8, `expected >= 8 fields, got ${scan.field_count}`);

  const gender = scan.fields.find((f) => f.name === 'gender');
  assert.equal(gender.type, 'select');
  assert.deepEqual(gender.options.map((o) => o.value), ['', 'male', 'female', 'decline']);

  const resume = scan.fields.find((f) => f.name === 'resume_file');
  assert.ok(resume, 'resume file input detected');
  assert.equal(resume.type, 'file');

  const firstName = scan.fields.find((f) => f.name === 'first_name');
  assert.equal(firstName.required, true, 'asterisk/required flag detected');

  assert.ok(scan.fields.find((f) => f.name === 'cover_letter'));
  assert.ok(scan.fields.find((f) => f.name === 'github'));
});

test('greenhouse_form: demographics gated for review, contact mapped to profile, cover letter to ai', () => {
  const { scan } = scanFixture('greenhouse_form.html');
  assert.equal(byName(scan, 'gender').action, 'review');
  assert.equal(byName(scan, 'race').action, 'review');
  assert.equal(byName(scan, 'first_name').action, 'profile');
  assert.equal(byName(scan, 'email').action, 'profile');
  assert.equal(byName(scan, 'cover_letter').action, 'ai');
});

// ── lever_form.html ──────────────────────────────────────────────────

test('lever_form: work auth + sponsorship gated for human review', () => {
  const { scan } = scanFixture('lever_form.html');
  assert.equal(byName(scan, 'work-auth').action, 'review');
  assert.match(byName(scan, 'work-auth').reason, /work authorization/);
  assert.equal(byName(scan, 'sponsor-yes').action, 'review');
  assert.equal(byName(scan, 'sponsor-no').action, 'review');
  assert.match(byName(scan, 'sponsor-yes').reason, /sponsorship/);
});

test('lever_form: radio group collects all options; name maps to profile', () => {
  const { scan } = scanFixture('lever_form.html');
  const sponsor = scan.fields.find((f) => f.name === 'sponsorship');
  assert.ok(sponsor, 'radio field detected');
  assert.deepEqual(
    sponsor.options.map((o) => o.value).sort(),
    ['no', 'yes'],
  );
  assert.equal(byName(scan, 'name').action, 'profile');
  assert.equal(byName(scan, 'name').profile_key, 'full_name');
});

// ── multi_page_form.html ─────────────────────────────────────────────

test('multi_page_form: sections captured and all fields detected', () => {
  const { scan } = scanFixture('multi_page_form.html');
  assert.equal(scan.field_count, 6);
  const city = scan.fields.find((f) => f.name === 'city');
  assert.equal(city.section, 'Address');
  const first = scan.fields.find((f) => f.name === 'first_name');
  assert.equal(first.section, 'Personal Details');
  assert.equal(byName(scan, 'country').type, 'select');
});

// ── custom_dropdown.html ─────────────────────────────────────────────

test('custom_dropdown: shadow DOM input is discovered', async () => {
  const window = loadFixture('custom_dropdown.html');
  // Wait for the fixture's DOMContentLoaded shadow-root setup.
  await new Promise((resolve) => {
    if (window.document.getElementById('shadow-host').shadowRoot) return resolve();
    window.document.addEventListener('shadow-ready', resolve, { once: true });
  });

  const scan = window.JobCopilotDetector.detectForms(window.document);
  const referral = scan.fields.find((f) => f.name === 'referral');
  assert.ok(referral, 'input inside shadow root found');
  assert.equal(referral.label, 'Referral code');
});

test('custom_dropdown: ARIA combobox label resolves via aria-labelledby, textarea is ai', () => {
  const { scan } = scanFixture('custom_dropdown.html');
  // The combobox itself is not an input/select/textarea — its label must not
  // leak onto other fields. The email input keeps its own label.
  assert.equal(byName(scan, 'email').label, 'Email');
  assert.equal(byName(scan, 'notes').action, 'ai');
  assert.equal(scan.mapped.find((f) => f.field_id === 'experience'), undefined);
});

// ── file_upload.html ─────────────────────────────────────────────────

test('file_upload: file input + checkbox detected, consent checkbox is memory bucket', () => {
  const { scan } = scanFixture('file_upload.html');
  const file = scan.fields.find((f) => f.name === 'resume_input');
  assert.equal(file.type, 'file');

  const consent = scan.fields.find((f) => f.name === 'consent');
  assert.equal(consent.type, 'checkbox');
  assert.equal(consent.value, 'false');
  assert.equal(byName(scan, 'consent').action, 'memory');
  assert.equal(byName(scan, 'candidate_name').action, 'profile');
});

// ── unknown_question_form.html ───────────────────────────────────────

test('unknown_question_form: buckets split profile/memory/ai/review correctly', () => {
  const { scan } = scanFixture('unknown_question_form.html');
  assert.equal(scan.field_count, 6);

  assert.equal(byName(scan, 'q_experience').action, 'memory'); // years of experience
  assert.equal(byName(scan, 'q_java').action, 'memory'); // unknown choice — memory
  assert.equal(byName(scan, 'q_why').action, 'ai'); // open question
  assert.equal(byName(scan, 'q_salary').action, 'review'); // sensitive
  assert.equal(byName(scan, 'q_notice').action, 'review'); // sensitive
  assert.equal(byName(scan, 'q_mystery').action, 'ai'); // textarea
});

// ── Cross-cutting safety properties ──────────────────────────────────

test('safety: no sensitive field is ever auto-fillable', () => {
  const files = [
    'simple_form.html',
    'greenhouse_form.html',
    'lever_form.html',
    'multi_page_form.html',
    'file_upload.html',
    'unknown_question_form.html',
  ];
  for (const file of files) {
    const { scan } = scanFixture(file);
    for (const f of scan.mapped) {
      if (f.action === 'review') {
        assert.equal(f.profile_key, null, `${file}: sensitive field ${f.field_id} must not carry a profile mapping`);
      }
      if (f.profile_key) {
        assert.ok(['first_name', 'last_name', 'full_name', 'email', 'phone', 'linkedin_url', 'github_url', 'portfolio_url', 'location'].includes(f.profile_key),
          `${file}: unexpected profile key ${f.profile_key}`);
      }
    }
  }
});

test('safety: every mapped field carries a selector for later fill actions', () => {
  for (const file of ['simple_form.html', 'lever_form.html', 'unknown_question_form.html']) {
    const { scan } = scanFixture(file);
    for (const f of scan.mapped) {
      assert.ok(f.selector, `${file}: ${f.field_id} missing selector`);
    }
  }
});

test('content flow: fastApply runs one analyze request and executes safe actions', async () => {
  const html = `
    <html><body>
      <form>
        <label for="first_name">First name</label>
        <input id="first_name" name="first_name" />
        <label for="email">Email</label>
        <input id="email" name="email" type="email" />
      </form>
    </body></html>
  `;
  const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true });
  const { window } = dom;

  if (!window.getComputedStyle) {
    window.getComputedStyle = () => ({ display: '', visibility: '', opacity: '' });
  }

  const calls = [];
  const chromeApi = {
    runtime: {
      onMessage: { addListener() {} },
      sendMessage: async (msg) => {
        calls.push(msg);
        if (msg.type === 'api' && msg.path === '/api/v1/fast-apply/analyze') {
          return {
            ok: true,
            data: {
              job: { title: 'Software Engineer', company: 'Acme', source_url: 'https://example.com/job', created: false },
              safe_actions: [{ action: 'FILL', field_id: 'first_name', selector: '#first_name', value: 'Ada' }],
              review_actions: [],
              blocked_actions: [],
              generated_answers: [],
              warnings: [],
              already_applied: null,
              summary: { safe_actions: 1, review_actions: 0, blocked_actions: 0, generated_answers: 0 },
            },
          };
        }
        return { ok: true, data: {} };
      },
    },
  };
  window.chrome = chromeApi;
  globalThis.chrome = chromeApi;

  window.eval(DETECTOR_SRC);
  window.eval(MAPPER_SRC);
  window.eval(AUTOFILL_SRC);
  window.eval(CONTENT_SRC);

  const result = await window.JobCopilotContent.fastApply();

  assert.ok(calls.some((m) => m.type === 'api' && m.path === '/api/v1/fast-apply/analyze'));
  assert.equal(result.ok, true);
  assert.equal(result.safe_actions_count, 1);
  assert.equal(window.document.getElementById('first_name').value, 'Ada');
});
