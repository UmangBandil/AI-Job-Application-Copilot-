/**
 * Job Copilot Assistant — field mapper.
 *
 * Classifies detected fields into resolution buckets:
 *   profile   → deterministic fill from the profile (M4)
 *   memory    → reuse a stored answer from question memory
 *   ai        → needs the answer engine (M5), grounded generation
 *   review    → sensitive: ALWAYS human confirmation, never auto-filled
 *
 * The mapper never decides values itself. Sensitive or unknown fields are
 * flagged, not guessed. Exposes window.JobCopilotMapper and module.exports.
 */

(function initMapper(global) {
  'use strict';

  // Ordered rules: first match wins. Patterns test against
  // label + name + placeholder + aria-label (lowercased).
  const PROFILE_RULES = [
    { match: /first\s*name|given\s*name/, field: 'first_name' },
    { match: /last\s*name|surname|family\s*name/, field: 'last_name' },
    { match: /^name$|full\s*name|your\s*name/, field: 'full_name' },
    { match: /e-?mail/, field: 'email' },
    { match: /phone|mobile|contact\s*number/, field: 'phone' },
    { match: /linked\s*in/, field: 'linkedin_url' },
    { match: /git\s*hub/, field: 'github_url' },
    { match: /portfolio|website|personal\s*site/, field: 'portfolio_url' },
    { match: /location|city|current\s*city/, field: 'location' },
  ];

  // Anything touching these topics must be confirmed by a human, even if
  // the profile technically has data. Order matters: sensitive checked
  // BEFORE memory/ai buckets.
  const SENSITIVE_RULES = [
    { match: /sponsorship|sponsor|visa|h1b|h-1b|immigra|work\s*auth|authorized|eligible|right\s*to\s*work/, reason: 'work authorization / sponsorship' },
    { match: /salary|compensation|expected\s*pay|pay\s*expect|wage|notice\s*period/, reason: 'compensation / notice period' },
    { match: /gender|ethnic|race|disab|veteran|criminal|background\s*check|religion/, reason: 'demographics / background' },
    { match: /relocat|willing\s*to\s*move|travel/, reason: 'relocation / travel' },
  ];

  const MEMORY_RULES = [
    { match: /years\s*of\s*experience|years\s*exp|experience.*\byears|years.*experience/, reason: 'experience length (profile-or-memory)' },
  ];

  const AI_HINTS = [
    /why\s*(do|are)\s*you|motivat|interest(ed)?\s*in/,
    /describe|explain|tell\s*us|elaborate/,
    /cover\s*letter|summary|about\s*yourself|objective/,
    /strength|weakness|achieve|accomplish/,
  ];

  function searchText(field) {
    return [field.label, field.name, field.placeholder, field.aria_label]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
  }

  function classifyField(field) {
    const text = searchText(field);
    const bucket = {
      field_id: field.field_id,
      selector: field.selector,
      tag: field.tag,
      type: field.type,
      label: field.label,
      action: 'unknown',
      profile_key: null,
      reason: null,
    };

    for (const rule of SENSITIVE_RULES) {
      if (rule.match.test(text)) {
        bucket.action = 'review';
        bucket.reason = rule.reason;
        return bucket;
      }
    }

    for (const rule of PROFILE_RULES) {
      if (rule.match.test(text)) {
        bucket.action = 'profile';
        bucket.profile_key = rule.field;
        return bucket;
      }
    }

    for (const rule of MEMORY_RULES) {
      if (rule.match.test(text)) {
        bucket.action = 'memory';
        bucket.reason = rule.reason;
        return bucket;
      }
    }

    const type = field.type;
    const isLongText = type === 'textarea';
    const isChoice = type === 'select' || type === 'checkbox' || type === 'radio';
    const hasOptions = Array.isArray(field.options) && field.options.length > 0;

    if (isLongText || AI_HINTS.some((rx) => rx.test(text))) {
      bucket.action = 'ai';
      bucket.reason = isLongText ? 'free-text answer' : 'open question';
      return bucket;
    }

    if (isChoice) {
      // Unknown choice: the answer may exist in memory; never guess Yes/No.
      bucket.action = 'memory';
      bucket.reason = 'unknown choice — check saved answers';
      return bucket;
    }

    // Plain unknown short text
    bucket.action = 'ai';
    bucket.reason = 'unknown short field';
    return bucket;
  }

  function mapFields(fields) {
    return (fields || []).map(classifyField);
  }

  const api = { mapFields, classifyField };
  global.JobCopilotMapper = api;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})(typeof window !== 'undefined' ? window : globalThis);
