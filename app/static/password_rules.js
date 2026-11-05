// Live password checklist shared by the sign-up, reset and change-password forms.
// The server (app/auth.py: password_problem) is the authority and also blocks
// common passwords, repeats, sequences and your name/email; this only gives
// instant feedback on the visible rules.

const PasswordRules = (() => {
  const RULES = [
    {id: 'length', label: 'At least 10 characters', test: (p) => p.length >= 10},
    {id: 'upper', label: 'An upper-case letter (A-Z)', test: (p) => /[A-Z]/.test(p)},
    {id: 'lower', label: 'A lower-case letter (a-z)', test: (p) => /[a-z]/.test(p)},
    {id: 'digit', label: 'A number (0-9)', test: (p) => /[0-9]/.test(p)},
    {id: 'symbol', label: 'A symbol (like ! - _ ?)', test: (p) => /[^A-Za-z0-9]/.test(p)}
  ];

  function evaluate(password) {
    return RULES.map((rule) => ({...rule, ok: rule.test(password || '')}));
  }

  function allPass(password) {
    return evaluate(password).every((rule) => rule.ok);
  }

  function unmetSummary(password) {
    const unmet = evaluate(password).filter((rule) => !rule.ok);
    return unmet.length
      ? `Password still needs: ${unmet.map((r) => r.label.toLowerCase()).join('; ')}.`
      : '';
  }

  // Render the checklist into `listEl` and keep it in sync with `input`.
  function attach(input, listEl, confirmInput, matchEl) {
    function render() {
      listEl.textContent = '';
      for (const rule of evaluate(input.value)) {
        const item = document.createElement('li');
        item.className = rule.ok ? 'pw-rule ok' : 'pw-rule';
        item.textContent = `${rule.ok ? '✓' : '○'} ${rule.label}`;
        listEl.appendChild(item);
      }
      if (confirmInput && matchEl) {
        if (!confirmInput.value) {
          matchEl.textContent = '';
          matchEl.className = 'pw-match';
        } else if (confirmInput.value === input.value) {
          matchEl.textContent = '✓ Passwords match';
          matchEl.className = 'pw-match ok';
        } else {
          matchEl.textContent = '○ Passwords do not match yet';
          matchEl.className = 'pw-match';
        }
      }
    }
    input.addEventListener('input', render);
    if (confirmInput) confirmInput.addEventListener('input', render);
    render();
  }

  return {evaluate, allPass, unmetSummary, attach};
})();
