// Login / registration page. Runs only on /login; the app itself never loads
// until the server sees a valid session.

function $(id) {
  return document.getElementById(id);
}

function showMessage(text, isError = true) {
  const box = $('authMessage');
  box.textContent = text;
  box.classList.toggle('error', isError);
}

const CARD_COPY = {
  signIn: {
    title: 'Enter your <span class="life">Life</span>',
    lead: 'Welcome back. Everything is right where you left it.'
  },
  register: {
    title: 'Create New <span class="life">Life</span>',
    lead: 'A calm place for every thought, plan and idea. It takes a minute.'
  },
  forgot: {
    title: 'Find your way <span class="life">back</span>',
    lead: "It happens to everyone. We'll get you back in."
  }
};

const GOOGLE_ERRORS = {
  google_denied: 'Google sign-in was cancelled.',
  google_state: 'That Google sign-in expired or was interrupted. Please try again.',
  google_failed: 'Google sign-in did not work. Please try again.',
  google_unverified: 'Google says that email address is not verified, so we cannot use it.',
  google_no_account: 'No Life Inbox account uses that Google email yet. Create one here, tick both boxes, then continue with Google.',
  google_consent: 'Tick both boxes (18+ and Terms) before continuing with Google.'
};

let googleEnabled = false;

function updateGoogleBlock() {
  const registering = !$('registerForm').hidden;
  $('googleBlock').hidden = !googleEnabled || !$('forgotPanel').hidden;
  $('googleButtonLabel').textContent = registering
    ? 'Sign up with Google'
    : 'Continue with Google';
}

function startGoogle() {
  const registering = !$('registerForm').hidden;
  if (registering && !($('registerAdult').checked && $('registerTerms').checked)) {
    showMessage(GOOGLE_ERRORS.google_consent);
    return;
  }
  const params = new URLSearchParams({intent: registering ? 'register' : 'signin'});
  if (registering) {
    params.set('adult', '1');
    params.set('terms', '1');
  }
  window.location.assign(`/api/auth/google/start?${params.toString()}`);
}

async function initGoogle() {
  try {
    const response = await fetch('/api/auth/providers', {credentials: 'same-origin'});
    googleEnabled = response.ok && Boolean((await response.json()).google);
  } catch {
    googleEnabled = false;
  }
  updateGoogleBlock();
}

function showReturnedError() {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('error');
  if (params.get('tab') === 'register') selectTab('register');
  if (code && GOOGLE_ERRORS[code]) showMessage(GOOGLE_ERRORS[code]);
  if (code) window.history.replaceState({}, '', '/login');
}

function setCardCopy(view) {
  // Static strings only; no user input is ever inserted as HTML.
  $('cardTitle').innerHTML = CARD_COPY[view].title;
  $('cardLead').textContent = CARD_COPY[view].lead;
}

function selectTab(name) {
  const signIn = name === 'signIn';
  $('forgotPanel').hidden = true;
  document.querySelector('.tabs').hidden = false;
  setCardCopy(signIn ? 'signIn' : 'register');
  $('signInForm').hidden = !signIn;
  $('registerForm').hidden = signIn;
  $('tabSignIn').classList.toggle('active', signIn);
  $('tabRegister').classList.toggle('active', !signIn);
  $('tabSignIn').setAttribute('aria-selected', String(signIn));
  $('tabRegister').setAttribute('aria-selected', String(!signIn));
  showMessage('', false);
  updateGoogleBlock();
  (signIn ? $('signInEmail') : $('registerName')).focus();
}

async function postJson(url, body) {
  let response;
  try {
    response = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
  } catch {
    throw new Error('Could not reach Life Inbox. Check your connection.');
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    // Non-JSON error body.
  }
  if (!response.ok) {
    let detail = data && data.detail;
    if (Array.isArray(detail)) {
      detail = 'Please check the form and try again.';
    }
    throw new Error(detail || 'Something went wrong. Please try again.');
  }
  return data;
}

function setBusy(button, busy, busyLabel) {
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = busyLabel;
  } else if (button.dataset.label) {
    button.textContent = button.dataset.label;
  }
  button.disabled = busy;
}

async function handleSignIn(event) {
  event.preventDefault();
  const email = $('signInEmail').value.trim();
  const password = $('signInPassword').value;
  if (!email || !password) {
    showMessage('Enter your email and password.');
    return;
  }
  const button = $('signInButton');
  setBusy(button, true, 'Entering your Life…');
  try {
    await postJson('/api/auth/login', {email, password});
    window.location.replace('/');
  } catch (error) {
    showMessage(error.message);
    $('signInPassword').value = '';
    $('signInPassword').focus();
    setBusy(button, false);
  }
}

async function handleRegister(event) {
  event.preventDefault();
  const displayName = $('registerName').value.trim();
  const email = $('registerEmail').value.trim();
  const password = $('registerPassword').value;
  const confirm = $('registerPasswordConfirm').value;

  if (!email) {
    showMessage('Enter your email address.');
    return;
  }
  if (!PasswordRules.allPass(password)) {
    showMessage(PasswordRules.unmetSummary(password));
    return;
  }
  if (password !== confirm) {
    showMessage('Passwords do not match.');
    return;
  }
  if (!$('registerAdult').checked) {
    showMessage('You must confirm you are 18 or older.');
    return;
  }
  if (!$('registerTerms').checked) {
    showMessage('You must accept the Terms and Privacy Policy.');
    return;
  }

  const button = $('registerButton');
  setBusy(button, true, 'Creating your new Life…');
  try {
    await postJson('/api/auth/register', {
      display_name: displayName,
      email,
      password,
      confirm_adult: true,
      accept_terms: true,
      // Change 025 (decision Q): unticked means AI processing is off.
      ai_processing: $('registerAi') ? $('registerAi').checked : false
    });
    window.location.replace('/#/welcome');
  } catch (error) {
    showMessage(error.message);
    setBusy(button, false);
  }
}

// Change 025: after deleting an account, the sign-in page says so.
if (new URLSearchParams(window.location.search).get('deleted') === '1') {
  window.addEventListener('DOMContentLoaded', () => showMessage('Your account and everything in it were deleted.'));
}

// --- forgot password ---------------------------------------------------------

let resendTimer = null;

function showForgotPanel() {
  $('signInForm').hidden = true;
  $('registerForm').hidden = true;
  document.querySelector('.tabs').hidden = true;
  setCardCopy('forgot');
  $('forgotPanel').hidden = false;
  updateGoogleBlock();
  $('forgotRequestForm').hidden = false;
  $('forgotResetForm').hidden = true;
  $('forgotEmail').value = $('signInEmail').value.trim();
  showMessage('', false);
  $('forgotEmail').focus();
}

function startResendCountdown(seconds) {
  const button = $('forgotResendButton');
  clearInterval(resendTimer);
  let left = seconds;
  button.disabled = true;
  button.textContent = `Resend code (${left}s)`;
  resendTimer = setInterval(() => {
    left -= 1;
    if (left <= 0) {
      clearInterval(resendTimer);
      button.disabled = false;
      button.textContent = 'Resend code';
    } else {
      button.textContent = `Resend code (${left}s)`;
    }
  }, 1000);
}

async function sendResetCode() {
  const email = $('forgotEmail').value.trim();
  if (!email) {
    showMessage('Enter your account email.');
    return false;
  }
  const result = await postJson('/api/auth/password/forgot', {email});
  let info = `If ${email} has a Life Inbox account, a 6-digit code is on its way.`;
  if (result.delivery === 'console') {
    info += ' Local mode: the code is printed in the terminal running the server.';
  }
  $('forgotSentInfo').textContent = info;
  startResendCountdown(result.resend_after_seconds || 60);
  return true;
}

async function handleForgotRequest(event) {
  event.preventDefault();
  const button = $('forgotSendButton');
  setBusy(button, true, 'Sending…');
  try {
    if (await sendResetCode()) {
      showMessage('', false);
      $('forgotRequestForm').hidden = true;
      $('forgotResetForm').hidden = false;
      $('forgotCode').focus();
    }
  } catch (error) {
    showMessage(error.message);
  } finally {
    setBusy(button, false);
  }
}

async function handleForgotResend() {
  try {
    await sendResetCode();
    showMessage('A new code was sent. Only the newest code works.', false);
  } catch (error) {
    showMessage(error.message);
  }
}

async function handleForgotReset(event) {
  event.preventDefault();
  const code = $('forgotCode').value.replace(/\s/g, '');
  const newPassword = $('forgotNewPassword').value;
  if (!/^\d{6}$/.test(code)) {
    showMessage('Enter the 6-digit code.');
    return;
  }
  if (!PasswordRules.allPass(newPassword)) {
    showMessage(PasswordRules.unmetSummary(newPassword));
    return;
  }
  if (newPassword !== $('forgotNewPasswordConfirm').value) {
    showMessage('Passwords do not match.');
    return;
  }
  const button = $('forgotResetButton');
  setBusy(button, true, 'Resetting…');
  try {
    await postJson('/api/auth/password/reset', {
      email: $('forgotEmail').value.trim(),
      code,
      new_password: newPassword
    });
    window.location.replace('/');
  } catch (error) {
    showMessage(error.message);
    $('forgotCode').select();
    setBusy(button, false);
  }
}

// --- gentle affirmations ----------------------------------------------------

const AFFIRMATIONS = [
  'Your mind is for having ideas, not holding them.',
  'You are not stressed. You are free.',
  'Ambitious, creative, and unhurried.',
  'Nothing gets lost. Everything finds its place.',
  'One calm step at a time is still forward.'
];

function startAffirmations() {
  const line = $('affirmation');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!line || reduceMotion) return;
  let index = 0;
  setInterval(() => {
    line.classList.add('fading');
    setTimeout(() => {
      index = (index + 1) % AFFIRMATIONS.length;
      line.textContent = AFFIRMATIONS[index];
      line.classList.remove('fading');
    }, 600);
  }, 6000);
}

function togglePassword(event) {
  const button = event.currentTarget;
  const input = $(button.dataset.target);
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  button.textContent = show ? 'Hide' : 'Show';
  button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
}

$('tabSignIn').addEventListener('click', () => selectTab('signIn'));
$('tabRegister').addEventListener('click', () => selectTab('register'));
$('signInForm').addEventListener('submit', handleSignIn);
$('registerForm').addEventListener('submit', handleRegister);
$('forgotPasswordButton').addEventListener('click', showForgotPanel);
$('forgotRequestForm').addEventListener('submit', handleForgotRequest);
$('forgotResetForm').addEventListener('submit', handleForgotReset);
$('forgotResendButton').addEventListener('click', handleForgotResend);
$('forgotBackButton').addEventListener('click', () => selectTab('signIn'));
document.querySelectorAll('.toggle-password').forEach((button) => {
  button.addEventListener('click', togglePassword);
});
PasswordRules.attach(
  $('registerPassword'), $('registerRules'), $('registerPasswordConfirm'), $('registerMatch')
);
PasswordRules.attach(
  $('forgotNewPassword'), $('forgotRules'), $('forgotNewPasswordConfirm'), $('forgotMatch')
);
$('googleButton').addEventListener('click', startGoogle);
initGoogle();
startAffirmations();
$('signInEmail').focus();
showReturnedError();
