let isSavingNote = false;
let isAnalyzingInbox = false;
const pendingNoteActions = new Set();
const pendingTaskActions = new Set();
const completedNoteIdsCache = new Set();
const analysisQueue = [];
let notificationSettings = null;

// The lens (shell.js, change 009): the life area every list is filtered by.
function lensKey() {
  return (window.LifeInboxLens && window.LifeInboxLens.key) || '';
}

function withLens(url) {
  const key = lensKey();
  if (!key) return url;
  return `${url}${url.includes('?') ? '&' : '?'}bot=${encodeURIComponent(key)}`;
}

// Tells the shell to refresh Home, the life areas and pinned topics.
function notifyChanged() {
  window.dispatchEvent(new CustomEvent('lifeinbox:changed'));
}

// A new note or source was saved (any kind). The shell closes the floating
// composer and shows "Saved" when you captured from another view (change 011a).
function notifyCaptured(itemId) {
  window.dispatchEvent(new CustomEvent('lifeinbox:captured', {detail: {itemId}}));
}

// You edited a note's text. If that moves a date you had confirmed, the shell
// asks you to confirm the new one once the note is filed again (change 012).
function notifyEdited(itemId) {
  window.dispatchEvent(new CustomEvent('lifeinbox:edited', {detail: {itemId}}));
}

async function getCompletedNoteIds() {
  try {
    const completedTasks = await fetchJson(
      '/api/tasks?status=completed',
      undefined,
      'Unable to load completed tasks.'
    );
    for (const t of completedTasks) {
      if (t.source_item_ids) {
        t.source_item_ids.forEach(id => completedNoteIdsCache.add(id));
      }
    }
    return completedNoteIdsCache;
  } catch {
    return completedNoteIdsCache;
  }
}

async function processAnalysisQueue() {
  if (isAnalyzingInbox) return;
  isAnalyzingInbox = true;
  setButtonBusy(
    'analyzeButton',
    true,
    'Re-sorting…',
    'Re-sort everything'
  );

  while (analysisQueue.length > 0) {
    const itemId = analysisQueue.shift();
    setStatus(
      'analysisStatus',
      itemId ? 'Categorizing note with AI…' : 'Analyzing saved notes…'
    );
    try {
      const url = itemId ? `/api/analyze?item_id=${itemId}` : '/api/analyze';
      const data = await fetchJson(
        url,
        {method: 'POST'},
        'Unable to analyze inbox.'
      );
      populateCategoryFilter(data);
      renderAnalysis(data);
      await loadTasks();
      await loadTopics();
      await loadDashboard();
      await loadAttention();
      await loadCalendarEvents();
      setStatus('analysisStatus', 'Analysis complete.');
      if (itemId) window.dispatchEvent(new CustomEvent('lifeinbox:analyzed', {detail: {itemId}}));
    } catch {
      setStatus(
        'analysisStatus',
        'We could not analyze your note. Please try again.',
        true
      );
    }
  }

  isAnalyzingInbox = false;
  setButtonBusy(
    'analyzeButton',
    false,
    'Re-sorting…',
    'Re-sort everything'
  );
}

// "Re-sort everything" (change 014) files every note you didn't file yourself
// again, 25 per AI call. The first click says how many calls; the second runs it.
let resortArmedUntil = 0;
async function resortEverything() {
  const button = document.getElementById('analyzeButton');
  if (Date.now() > resortArmedUntil) {
    try {
      const plan = await fetchJson('/api/filing/resort-plan', undefined, 'Could not count your notes.');
      if (!plan.notes) {
        setStatus('analysisStatus', 'Nothing to re-sort: every note is filed by you or not filed yet.');
        return;
      }
      const cost = plan.ai
        ? `${plan.calls} AI call${plan.calls === 1 ? '' : 's'} (${plan.per_call} notes per call)`
        : 'no AI calls (offline)';
      setStatus('analysisStatus', `Re-sorting ${plan.notes} note${plan.notes === 1 ? '' : 's'} uses ${cost}. Notes you filed yourself stay where they are. Click again to start.`);
      button.textContent = `Yes, re-sort (${plan.ai ? `${plan.calls} call${plan.calls === 1 ? '' : 's'}` : 'offline'})`;
      resortArmedUntil = Date.now() + 15000;
    } catch (error) {
      setStatus('analysisStatus', error.message, true);
    }
    return;
  }
  resortArmedUntil = 0;
  await analyzeInbox();
  button.textContent = 'Re-sort everything';
}

function autoAnalyzeInbox(itemId = null) {
  analysisQueue.push(itemId);
  processAnalysisQueue();
}

const itemFilterFields = {
  q: 'itemSearch',
  item_type: 'itemTypeFilter',
  category: 'categoryFilter',
  priority: 'priorityFilter',
  processing_status: 'processingStatusFilter'
};

function setStatus(elementId, message, isError = false) {
  const element = document.getElementById(elementId);
  if (!element) return;
  element.textContent = message;
  element.classList.toggle('error', isError);
  if (message) {
    element.classList.remove('flash');
    // eslint-disable-next-line no-unused-expressions
    void element.offsetWidth;
    element.classList.add('flash');
  }
}

function setButtonBusy(buttonId, busy, busyLabel, idleLabel) {
  const button = document.getElementById(buttonId);
  if (!button) return;
  button.disabled = busy;
  button.textContent = busy ? busyLabel : idleLabel;
  button.setAttribute('aria-busy', String(busy));
}

function decodeApplicationServerKey(encodedKey) {
  const padded = encodedKey + '='.repeat((4 - encodedKey.length % 4) % 4);
  const base64 = padded.replace(/-/g, '+').replace(/_/g, '/');
  const binary = atob(base64);
  return Uint8Array.from(binary, character => character.charCodeAt(0));
}

function updateNotificationPrompt() {
  const prompt = document.getElementById('notificationPrompt');
  const message = document.getElementById('notificationPromptMessage');
  const button = document.getElementById('enableNotificationPrompt');
  const enabledCheckbox = document.getElementById('notificationsEnabled');
  const supported =
    'Notification' in window
    && 'serviceWorker' in navigator
    && 'PushManager' in window;
  const permission = supported ? Notification.permission : 'unsupported';

  if (!notificationSettings || notificationSettings.enabled) {
    prompt.hidden = true;
    return;
  }
  prompt.hidden = false;

  if (!supported) {
    message.textContent =
      'This browser does not support background task notifications.';
    button.hidden = true;
  } else if (!notificationSettings.push_available) {
    message.textContent =
      'Task notifications are not configured on this server yet.';
    button.hidden = true;
  } else if (permission === 'denied') {
    message.textContent =
      'Notifications are blocked for this site in your browser. Open site settings for 127.0.0.1, change Notifications to Allow, then reload this page.';
    button.hidden = true;
  } else {
    message.textContent =
      'Get a daily reminder for tasks due today and an extra alert for eligible High-priority tasks. Choose Enable to allow this browser and turn them on.';
    button.hidden = false;
    button.disabled = enabledCheckbox.disabled;
  }
}

function enableNotificationsFromPrompt(event) {
  document.getElementById('notificationsEnabled').checked = true;
  saveNotificationSettings(event);
}

async function loadNotificationSettings() {
  try {
    notificationSettings = await fetchJson(
      '/api/notifications/settings',
      undefined,
      'Unable to load notification settings.'
    );
    document.getElementById('notificationsEnabled').checked =
      notificationSettings.enabled;
    document.getElementById('dailyDigestTime').value =
      notificationSettings.daily_digest_time || '08:00';
    document.getElementById('notificationTimezone').value =
      notificationSettings.timezone || 'UTC';
    document.getElementById('includeUnscheduledPrompt').checked =
      notificationSettings.include_unscheduled_prompt;

    if (!notificationSettings.configured) {
      const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (browserTimezone) {
        document.getElementById('notificationTimezone').value = browserTimezone;
      }
    }

    const supported =
      'Notification' in window
      && 'serviceWorker' in navigator
      && 'PushManager' in window;
    document.getElementById('notificationsEnabled').disabled =
      (!supported || !notificationSettings.push_available)
      && !notificationSettings.enabled;
    updateNotificationPrompt();
    if (!supported) {
      setStatus(
        'notificationStatus',
        'This browser does not support background push notifications.'
      );
    } else if (!notificationSettings.push_available) {
      setStatus(
        'notificationStatus',
        'Push delivery is not configured on the server yet.'
      );
    } else {
      setStatus(
        'notificationStatus',
        notificationSettings.enabled
          ? `Notifications are enabled (${notificationSettings.subscription_count} device(s)).`
          : 'Notifications are off. Enable them here to receive task alerts.'
      );
    }
  } catch {
    setStatus(
      'notificationStatus',
      'Could not load notification settings. Reload to try again.',
      true
    );
  }
}

async function saveNotificationSettings(event) {
  event.preventDefault();
  const enabled = document.getElementById('notificationsEnabled').checked;
  const submitButton = document.getElementById('saveNotificationSettingsButton');
  const time = document.getElementById('dailyDigestTime').value;
  const timezoneName = document.getElementById('notificationTimezone').value.trim();

  submitButton.disabled = true;
  setStatus('notificationStatus', 'Saving notification settings…');
  try {
    if (enabled) {
      if (
        !('Notification' in window)
        || !('serviceWorker' in navigator)
        || !('PushManager' in window)
      ) {
        throw new Error('This browser does not support push notifications.');
      }
      if (!notificationSettings?.vapid_public_key) {
        throw new Error('Push delivery is not configured on the server yet.');
      }
      let permission = Notification.permission;
      if (permission === 'default') {
        permission = await Notification.requestPermission();
      }
      if (permission !== 'granted') {
        throw new Error(
          'Notifications are blocked for this site. Open site settings for 127.0.0.1, change Notifications to Allow, then reload this page.'
        );
      }

      const registration = await navigator.serviceWorker.register(
        '/service-worker.js'
      );
      let subscription = await registration.pushManager.getSubscription();
      if (!subscription) {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: decodeApplicationServerKey(
            notificationSettings.vapid_public_key
          )
        });
      }
      await fetchJson(
        '/api/notifications/subscriptions',
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(subscription.toJSON())
        },
        'Unable to register this browser for notifications.'
      );
    }

    await fetchJson(
      '/api/notifications/settings',
      {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          enabled,
          daily_digest_time: time,
          timezone: timezoneName,
          include_unscheduled_prompt:
            document.getElementById('includeUnscheduledPrompt').checked
        })
      },
      'Unable to save notification settings. Check the time and timezone.'
    );
    await loadNotificationSettings();
    setStatus(
      'notificationStatus',
      enabled
        ? 'Notifications enabled. Daily and eligible High-priority task alerts are ready.'
        : 'Notifications disabled.'
    );
  } catch (error) {
    setStatus(
      'notificationStatus',
      error.message || 'Could not save notification settings.',
      true
    );
    updateNotificationPrompt();
  } finally {
    submitButton.disabled = false;
  }
}

function itemFilterParams() {
  const params = new URLSearchParams();
  for (const [name, elementId] of Object.entries(itemFilterFields)) {
    const value = document.getElementById(elementId).value.trim();
    if (value) params.set(name, value);
  }
  return params;
}

function hasItemFilters() {
  return itemFilterParams().size > 0;
}

function updateUrl(updates) {
  const url = new URL(window.location.href);
  for (const [name, value] of Object.entries(updates)) {
    if (value) {
      url.searchParams.set(name, value);
    } else {
      url.searchParams.delete(name);
    }
  }
  window.history.pushState({}, '', url);
}

function syncControlsFromUrl() {
  const params = new URLSearchParams(window.location.search);
  for (const [name, elementId] of Object.entries(itemFilterFields)) {
    const element = document.getElementById(elementId);
    const value = params.get(name) || '';
    if (
      name === 'category'
      && value
      && !Array.from(element.options).some(option => option.value === value)
    ) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      element.appendChild(option);
    }
    element.value = value;
  }

  const taskStatus = params.get('task_status');
  document.getElementById('taskStatusFilter').value =
    ['open', 'completed', 'dismissed'].includes(taskStatus)
      ? taskStatus
      : 'open';
}

function populateCategoryFilter(data) {
  const select = document.getElementById('categoryFilter');
  const selected =
    new URLSearchParams(window.location.search).get('category')
    || select.value;
  const categories = Array.from(
    new Set((data.buckets || []).map(bucket => bucket.name))
  ).sort((first, second) => first.localeCompare(second));

  select.replaceChildren();
  const allOption = document.createElement('option');
  allOption.value = '';
  allOption.textContent = 'All';
  select.appendChild(allOption);

  if (selected && !categories.includes(selected)) {
    categories.push(selected);
    categories.sort((first, second) => first.localeCompare(second));
  }
  for (const category of categories) {
    const option = document.createElement('option');
    option.value = category;
    option.textContent = category;
    select.appendChild(option);
  }
  select.value = selected;
}

function applyItemFilters(event) {
  event.preventDefault();
  const values = {};
  const params = itemFilterParams();
  for (const name of Object.keys(itemFilterFields)) {
    values[name] = params.get(name) || '';
  }
  updateUrl(values);
  loadNotes();
}

function clearItemFilters() {
  for (const elementId of Object.values(itemFilterFields)) {
    document.getElementById(elementId).value = '';
  }
  updateUrl(
    Object.fromEntries(
      Object.keys(itemFilterFields).map(name => [name, ''])
    )
  );
  loadNotes();
}

function showFailedItems() {
  if (window.LifeInboxShell) window.LifeInboxShell.goTo('topics');
  document.getElementById('processingStatusFilter').value = 'failed';
  updateUrl({processing_status: 'failed'});
  document.getElementById('rawSavedNotesHeading').scrollIntoView({
    behavior: 'smooth',
    block: 'start'
  });
  loadNotes();
}

function changeTaskStatusFilter() {
  const status = document.getElementById('taskStatusFilter').value;
  updateUrl({task_status: status});
  loadTasks();
}

async function fetchJson(url, options, friendlyError) {
  let response;
  try {
    response = await fetch(url, {credentials: 'same-origin', ...options});
  } catch {
    throw new Error(friendlyError);
  }

  if (response.status === 401) {
    // Session ended (signed out, expired or revoked): show only the login screen.
    leaveToLogin();
    throw new Error('Signed out.');
  }

  if (!response.ok) {
    // Validation/state errors (4xx) carry a message meant for the user, e.g.
    // "Task has no normalized date"; anything else stays generic.
    if (response.status >= 400 && response.status < 500) {
      try {
        const body = await response.json();
        if (body && typeof body.detail === 'string' && body.detail.length <= 300) {
          throw new Error(body.detail);
        }
      } catch (error) {
        if (error instanceof SyntaxError) {
          throw new Error(friendlyError);
        }
        if (error && error.message && error.message !== friendlyError) {
          throw error;
        }
      }
    }
    throw new Error(friendlyError);
  }

  const method = String((options && options.method) || 'GET').toUpperCase();
  if (method !== 'GET') notifyChanged();

  if (response.status === 204) {
    return null;
  }

  try {
    return await response.json();
  } catch {
    throw new Error(friendlyError);
  }
}

// Matches the server's raw_text max_length in app/schemas.py. The textarea's
// maxlength stops typing and trims pastes at this length.
const NOTE_MAX_LENGTH = 2000;
const NOTE_NEAR_LIMIT = 1800;

function updateNoteCharCount() {
  const textarea = document.getElementById('noteText');
  const counter = document.getElementById('noteCharCount');
  if (!textarea || !counter) return;
  const length = textarea.value.length;
  const field = textarea.closest('.note-field');
  const atLimit = length >= NOTE_MAX_LENGTH;
  counter.textContent = atLimit
    ? `${length} / ${NOTE_MAX_LENGTH} · max 2000 characters reached`
    : `${length} / ${NOTE_MAX_LENGTH} · max 2000 characters`;
  if (field) {
    field.classList.toggle('at-limit', atLimit);
    field.classList.toggle('near-limit', !atLimit && length >= NOTE_NEAR_LIMIT);
  }
}

function handleNotePaste(event) {
  const textarea = event.target;
  const pasted = (event.clipboardData || window.clipboardData)?.getData('text') || '';
  const selected = textarea.selectionEnd - textarea.selectionStart;
  const room = NOTE_MAX_LENGTH - (textarea.value.length - selected);
  if (pasted.length > room) {
    setStatus(
      'noteStatus',
      `Notes can be up to ${NOTE_MAX_LENGTH} characters, so only the first part of what you pasted was added. Save the rest as another note.`,
      true
    );
  }
}

function setupNoteLimit() {
  const textarea = document.getElementById('noteText');
  if (!textarea) return;
  textarea.maxLength = NOTE_MAX_LENGTH;
  textarea.addEventListener('input', updateNoteCharCount);
  textarea.addEventListener('paste', handleNotePaste);
  updateNoteCharCount();
}

// --- Composer: a note, optionally with one attached source ------------------
// The note becomes the source's "context": the user's own words about why it
// matters, which the AI treats as the strongest clue for the topic.
let pendingAttachment = null; // {kind: 'link' | 'pdf' | 'image' | 'audio', url?, file?}
const ATTACHMENT_KINDS = {
  link: {label: 'link', badge: 'LINK', input: null, endpoint: '/api/items/url'},
  pdf: {label: 'PDF', badge: 'PDF', input: 'pdfFile', endpoint: '/api/items/pdf'},
  image: {label: 'image', badge: 'IMAGE', input: 'imageFile', endpoint: '/api/items/image'},
  audio: {label: 'audio', badge: 'AUDIO', input: 'voiceFile', endpoint: '/api/items/voice'}
};
const LONE_LINK = /^https?:\/\/\S+$/i;

function composerAddLabel() {
  if (!pendingAttachment) return 'Add note';
  const kind = ATTACHMENT_KINDS[pendingAttachment.kind].label;
  const hasNote = document.getElementById('noteText').value.trim().length > 0;
  return hasNote ? `Add ${kind} with note` : `Add ${kind}`;
}

function refreshComposer() {
  const chip = document.getElementById('attachmentChip');
  const button = document.getElementById('addNoteButton');
  if (pendingAttachment) {
    const kind = ATTACHMENT_KINDS[pendingAttachment.kind];
    document.getElementById('attachmentKind').textContent = kind.badge;
    document.getElementById('attachmentLabel').textContent =
      pendingAttachment.url || pendingAttachment.file?.name || '';
    chip.hidden = false;
  } else {
    chip.hidden = true;
  }
  if (button && !isSavingNote) button.textContent = composerAddLabel();
}

function setAttachment(attachment) {
  pendingAttachment = attachment;
  refreshComposer();
  document.getElementById('noteText').focus();
}

function clearAttachment() {
  if (pendingAttachment && pendingAttachment.kind !== 'link') {
    const input = document.getElementById(ATTACHMENT_KINDS[pendingAttachment.kind].input);
    if (input) input.value = '';
  }
  pendingAttachment = null;
  refreshComposer();
}

function clearComposerNote(savedText) {
  const textarea = document.getElementById('noteText');
  if (textarea && savedText && textarea.value.trim() === savedText) {
    textarea.value = '';
    updateNoteCharCount();
  }
}

function openLinkAttach() {
  document.getElementById('linkAttachRow').hidden = false;
  document.getElementById('urlText').focus();
}

function cancelLinkAttach() {
  document.getElementById('urlText').value = '';
  document.getElementById('linkAttachRow').hidden = true;
}

function confirmLinkAttach() {
  const input = document.getElementById('urlText');
  const url = input.value.trim();
  if (!LONE_LINK.test(url)) {
    setStatus('noteStatus', 'Paste a full link starting with http:// or https://', true);
    input.focus();
    return;
  }
  cancelLinkAttach();
  setStatus('noteStatus', '');
  setAttachment({kind: 'link', url});
}

function pickAttachment(kind) {
  document.getElementById(ATTACHMENT_KINDS[kind].input).click();
}

function setupComposer() {
  for (const [kind, info] of Object.entries(ATTACHMENT_KINDS)) {
    if (!info.input) continue;
    const input = document.getElementById(info.input);
    input?.addEventListener('change', () => {
      const file = input.files && input.files[0];
      if (file) setAttachment({kind, file});
    });
  }
  const url = document.getElementById('urlText');
  url?.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); confirmLinkAttach(); }
    if (event.key === 'Escape') { event.preventDefault(); cancelLinkAttach(); }
  });
  document.getElementById('noteText')?.addEventListener('input', refreshComposer);
  refreshComposer();
}

function savedSourceMessage(kind, item) {
  const label = ATTACHMENT_KINDS[kind].label;
  const name = label.charAt(0).toUpperCase() + label.slice(1);
  if (item.processing_status !== 'ready') {
    return [`${name} saved, but reading it failed: ${item.error_message || 'unknown error'}`, true];
  }
  return [item.user_context ? `${name} saved with your note.` : `${name} saved.`, false];
}

async function addCapture() {
  if (isSavingNote) return;
  const textarea = document.getElementById('noteText');
  const text = textarea.value.trim();
  let attachment = pendingAttachment;
  let context = text;
  // A link pasted on its own into the note box is saved as a link.
  if (!attachment && LONE_LINK.test(text)) {
    attachment = {kind: 'link', url: text};
    context = '';
  }
  if (!attachment) {
    await addNote();
    refreshComposer();
    return;
  }
  if (context.length > NOTE_MAX_LENGTH) {
    setStatus('noteStatus', `Notes can be up to ${NOTE_MAX_LENGTH} characters.`, true);
    return;
  }
  const kind = attachment.kind;
  const info = ATTACHMENT_KINDS[kind];

  if (kind === 'audio') {
    if (await uploadVoiceFile(attachment.file, 'Uploading audio…', '', context)) {
      clearAttachment();
    }
    return;
  }

  isSavingNote = true;
  setButtonBusy('addNoteButton', true, 'Saving…', composerAddLabel());
  setStatus('noteStatus', kind === 'link' ? 'Saving link and reading the page…' : `Saving ${info.label} and reading it…`);
  try {
    let options;
    if (kind === 'link') {
      options = {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(context ? {url: attachment.url, context} : {url: attachment.url})
      };
    } else {
      const formData = new FormData();
      formData.append('file', attachment.file);
      if (context) formData.append('context', context);
      options = {method: 'POST', body: formData};
    }
    const item = await fetchJson(info.endpoint, options, `Unable to save ${info.label}.`);
    const [message, isError] = item && item.reused_from
      ? [item.filing_reused
          ? 'You saved this link before: Life Inbox reused what it read and filed it the same way (no AI call).'
          : 'You saved this link before: Life Inbox reused what it read, and files it again for your new note.', false]
      : savedSourceMessage(kind, item);
    setStatus('noteStatus', message, isError);
    clearComposerNote(text);
    isSavingNote = false;
    clearAttachment();
    await loadNotes();
    await loadLatestAnalysis();
    await loadDashboard();
    if (item && item.id) {
      notifyCaptured(item.id);
      // A link saved again with no new note is already filed (change 015).
      if (!item.filing_reused) autoAnalyzeInbox(item.id);
      else window.dispatchEvent(new CustomEvent('lifeinbox:changed'));
    }
  } catch {
    setStatus('noteStatus', `We could not save that ${info.label}. Your note and attachment are still here.`, true);
  } finally {
    isSavingNote = false;
    setButtonBusy('addNoteButton', false, 'Saving…', composerAddLabel());
  }
}

async function addNote() {
  if (isSavingNote) return;

  const textarea = document.getElementById('noteText');
  const text = textarea.value.trim();
  if (!text) {
    setStatus('noteStatus', 'Write a note before saving.', true);
    textarea.focus();
    return;
  }
  if (text.length > NOTE_MAX_LENGTH) {
    setStatus('noteStatus', `Notes can be up to ${NOTE_MAX_LENGTH} characters. Shorten it or split it into two notes.`, true);
    textarea.focus();
    return;
  }

  isSavingNote = true;
  setButtonBusy('addNoteButton', true, 'Saving…', 'Add Note');
  setStatus('noteStatus', 'Saving your note…');

  try {
    const createdItem = await fetchJson(
      '/api/items',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({raw_text: text})
      },
      'Unable to save note.'
    );

    if (textarea.value.trim() === text) {
      textarea.value = '';
      updateNoteCharCount();
    }
    setStatus('noteStatus', 'Note saved.');
    await loadNotes(
      'Your note was saved, but the list could not refresh. Reload to try again.'
    );
    await loadLatestAnalysis();
    if (createdItem && createdItem.id) {
      notifyCaptured(createdItem.id);
      autoAnalyzeInbox(createdItem.id);
    }
  } catch {
    setStatus(
      'noteStatus',
      'We could not save your note. Your text is still here—please try again.',
      true
    );
  } finally {
    isSavingNote = false;
    setButtonBusy('addNoteButton', false, 'Saving…', 'Add Note');
  }
}

let voiceRecorder = null;
let voiceChunks = [];
let voiceStream = null;

let micState = 'idle'; // 'idle' | 'recording' | 'processing' | 'error'
let recordingTimerInterval = null;
let recordingStartTime = 0;

function setMicState(state, message = '', isError = false) {
  micState = state;
  const btn = document.getElementById('micVoiceButton');
  const icon = document.getElementById('micIcon');
  const pulse = document.getElementById('micPulse');
  const timer = document.getElementById('micTimer');
  const spinner = document.getElementById('micSpinner');
  const label = document.getElementById('micLabel');
  const status = document.getElementById('micVoiceStatus');

  if (btn) {
    btn.className = `mic-button ${state}`;
    if (state === 'idle') {
      btn.disabled = false;
      if (icon) { icon.style.display = 'inline'; icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0014 0M12 18v4M8 22h8"/></svg>'; }
      if (pulse) pulse.style.display = 'none';
      if (timer) timer.style.display = 'none';
      if (spinner) spinner.style.display = 'none';
      if (label) label.textContent = 'Record note';
    } else if (state === 'recording') {
      btn.disabled = false;
      if (icon) { icon.style.display = 'inline'; icon.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12"/></svg>'; }
      if (pulse) pulse.style.display = 'inline-block';
      if (timer) { timer.style.display = 'inline'; timer.textContent = '00:00'; }
      if (spinner) spinner.style.display = 'none';
      if (label) label.textContent = 'Stop';
    } else if (state === 'processing') {
      btn.disabled = true;
      if (icon) icon.style.display = 'none';
      if (pulse) pulse.style.display = 'none';
      if (timer) timer.style.display = 'none';
      if (spinner) spinner.style.display = 'inline-block';
      if (label) label.textContent = 'Transcribing…';
    } else if (state === 'error') {
      btn.disabled = false;
      if (icon) { icon.style.display = 'inline'; icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M12 3l10 18H2z"/><path d="M12 10v4M12 17h.01"/></svg>'; }
      if (pulse) pulse.style.display = 'none';
      if (timer) timer.style.display = 'none';
      if (spinner) spinner.style.display = 'none';
      if (label) label.textContent = 'Retry mic';
    }
  }

  if (status) {
    status.textContent = message;
    status.classList.toggle('error', isError);
  }
}

let speechRecognizer = null;
let speechTranscript = '';

async function uploadVoiceFile(file, statusMessage, transcript = '', context = '') {
  setMicState('processing', 'Transcribing and cleaning transcript with NVIDIA NIM…');
  setStatus('noteStatus', statusMessage);
  const formData = new FormData();
  formData.append('file', file, file.name || 'voice-note.webm');
  if (transcript) {
    formData.append('transcript', transcript);
  }
  if (context) {
    formData.append('context', context);
  }
  try {
    const item = await fetchJson(
      '/api/items/voice',
      {method: 'POST', body: formData},
      'Unable to upload voice note.'
    );
    setStatus(
      'noteStatus',
      item.processing_status === 'ready'
        ? (item.extracted_text
          ? 'Voice note saved and transcribed.'
          : 'Voice note saved. Add or edit the transcript if needed.')
        : `Voice note saved but processing failed: ${item.error_message || 'unknown error'}`,
      item.processing_status !== 'ready'
    );
    setMicState('idle', 'Voice note saved and transcribed.');
    clearComposerNote(context);
    await loadNotes();
    await loadLatestAnalysis();
    await loadDashboard();
    if (item && item.id) {
      notifyCaptured(item.id);
      autoAnalyzeInbox(item.id);
    }
    return true;
  } catch {
    setStatus('noteStatus', 'We could not upload that voice note.', true);
    setMicState('error', 'Voice processing failed. Please try again.', true);
    return false;
  }
}

async function toggleVoiceRecording() {
  if (voiceRecorder && voiceRecorder.state === 'recording') {
    if (recordingTimerInterval) {
      clearInterval(recordingTimerInterval);
      recordingTimerInterval = null;
    }
    if (speechRecognizer) {
      try { speechRecognizer.stop(); } catch {}
    }
    voiceRecorder.stop();
    setButtonBusy('recordVoiceButton', false, 'Recording…', 'Record');
    setMicState('processing', 'Transcribing…');
    return;
  }

  if (micState === 'processing') return;

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    const msg = 'Browser recording is not available in this browser. Upload an audio file instead.';
    setMicState('error', msg, true);
    setStatus('voiceStatus', msg, true);
    return;
  }

  try {
    voiceStream = await navigator.mediaDevices.getUserMedia({audio: true});
    voiceChunks = [];

    let mimeType = 'audio/webm;codecs=opus';
    if (typeof MediaRecorder.isTypeSupported === 'function') {
      if (!MediaRecorder.isTypeSupported(mimeType)) {
        mimeType = MediaRecorder.isTypeSupported('audio/webm')
          ? 'audio/webm'
          : (MediaRecorder.isTypeSupported('audio/wav') ? 'audio/wav' : '');
      }
    } else {
      mimeType = '';
    }

    voiceRecorder = mimeType
      ? new MediaRecorder(voiceStream, {mimeType})
      : new MediaRecorder(voiceStream);

    voiceRecorder.addEventListener('dataavailable', event => {
      if (event.data && event.data.size > 0) voiceChunks.push(event.data);
    });

    // Start speech recognition in tandem if browser supports it
    speechTranscript = '';
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      try {
        const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
        speechRecognizer = new SpeechRec();
        speechRecognizer.continuous = true;
        speechRecognizer.interimResults = true;
        speechRecognizer.lang = 'en-US';
        speechRecognizer.onresult = (event) => {
          let text = '';
          for (let i = 0; i < event.results.length; ++i) {
            text += event.results[i][0].transcript + ' ';
          }
          if (text) speechTranscript = text.trim();
        };
        speechRecognizer.start();
      } catch (e) {
        console.debug('Speech recognition init info:', e);
      }
    }

    voiceRecorder.addEventListener('stop', async () => {
      if (recordingTimerInterval) {
        clearInterval(recordingTimerInterval);
        recordingTimerInterval = null;
      }
      if (speechRecognizer) {
        try { speechRecognizer.stop(); } catch {}
      }
      if (voiceStream) {
        voiceStream.getTracks().forEach(track => track.stop());
        voiceStream = null;
      }
      const actualType = (voiceRecorder && voiceRecorder.mimeType) || mimeType || 'audio/webm';
      const blob = new Blob(voiceChunks, {type: actualType});
      voiceRecorder = null;
      if (!blob.size) {
        setMicState('error', 'Recording was empty. Check microphone.', true);
        setStatus('voiceStatus', 'Recording was empty.', true);
        return;
      }
      const ext = actualType.includes('wav') ? 'wav' : 'webm';
      const file = new File([blob], `voice-recording-${Date.now()}.${ext}`, {
        type: actualType
      });
      const capturedSpeech = speechTranscript;
      speechTranscript = '';
      // Anything typed in the note box is saved as context for the recording.
      const typedNote = document.getElementById('noteText')?.value.trim() || '';
      await uploadVoiceFile(file, 'Saving recorded voice note…', capturedSpeech, typedNote);
    });

    voiceRecorder.start(250);
    recordingStartTime = Date.now();
    if (recordingTimerInterval) clearInterval(recordingTimerInterval);
    recordingTimerInterval = setInterval(() => {
      const elapsed = Math.floor((Date.now() - recordingStartTime) / 1000);
      const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
      const s = String(elapsed % 60).padStart(2, '0');
      const timerEl = document.getElementById('micTimer');
      if (timerEl) timerEl.textContent = `${m}:${s}`;
    }, 500);

    setMicState('recording', 'Recording… click Stop when finished.');
    const recordBtn = document.getElementById('recordVoiceButton');
    if (recordBtn) {
      recordBtn.textContent = 'Stop';
      recordBtn.disabled = false;
    }
  } catch (err) {
    if (recordingTimerInterval) {
      clearInterval(recordingTimerInterval);
      recordingTimerInterval = null;
    }
    const isDenied =
      err &&
      (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError');
    const msg = isDenied
      ? 'Microphone permission denied. Allow mic access in browser settings.'
      : 'Could not access the microphone. Check device permissions.';
    setMicState('error', msg, true);
    setStatus('voiceStatus', msg, true);
  }
}

function esc(str) {
  return String(str ?? '').replace(/[&<>'"]/g, tag => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'
  }[tag]));
}

function actionButton(label, className, onClick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  button.className = className;
  button.addEventListener('click', onClick);
  return button;
}

function captureTypeLabel(itemType) {
  if (itemType === 'pdf') return 'PDF';
  if (itemType === 'image') return 'Image';
  if (itemType === 'voice') return 'Voice';
  if (itemType === 'url') return 'URL';
  return 'Item';
}

// Change 023: your note on a saved source can be edited; saving files it again.
function sourceNoteButton(note) {
  return actionButton(note.user_context ? 'Edit note' : 'Add a note', 'secondary', () => {
    if (window.LifeInboxShell && window.LifeInboxShell.editNoteContext) window.LifeInboxShell.editNoteContext(note.id);
  });
}

function renderNote(note) {
  // The list shows a note's masked copy when it holds a secret (change 016);
  // Edit still opens the real text.
  const view = note.secret_masked ? {...note, ...note.secret_masked} : note;
  const root = document.createElement('div');
  root.className = 'note';
  root.dataset.noteId = String(note.id);

  const text = document.createElement('div');
  text.className = 'note-text';
  if (view.item_type === 'url') {
    const title = view.title || view.source_url || 'Saved URL';
    const body = view.extracted_text || view.raw_text || '';
    text.innerHTML = `<strong>${esc(title)}</strong><div class="muted">${esc(view.source_url || '')}</div>${body ? `<div>${esc(body.slice(0, 280))}${body.length > 280 ? '…' : ''}</div>` : ''}`;
  } else if (view.item_type === 'pdf') {
    const title = view.title || view.original_filename || 'PDF document';
    const body = view.extracted_text || view.raw_text || '';
    const preview = view.storage_path
      ? `<a href="/api/items/${view.id}/file" target="_blank" rel="noopener">Open PDF</a>`
      : '';
    text.innerHTML = `<strong>${esc(title)}</strong><div class="muted">${esc(view.original_filename || '')}${preview ? ` · ${preview}` : ''}</div>${body ? `<div>${esc(body.slice(0, 280))}${body.length > 280 ? '…' : ''}</div>` : ''}`;
  } else if (view.item_type === 'image') {
    const title = view.title || view.original_filename || 'Image';
    const ocr = view.extracted_text || '';
    const ai = view.ai_description || '';
    const thumb = view.storage_path
      ? `<img class="capture-thumb" src="/api/items/${view.id}/file?variant=thumb" alt="Thumbnail for ${esc(title)}" />`
      : '';
    const open = view.storage_path
      ? `<a href="/api/items/${view.id}/file" target="_blank" rel="noopener">Open image</a>`
      : '';
    text.innerHTML = [
      `<strong>${esc(title)}</strong>`,
      `<div class="muted">${esc(view.original_filename || '')}${open ? ` · ${open}` : ''}</div>`,
      thumb,
      `<div class="provenance"><span class="label">OCR (extracted)</span>: ${ocr ? esc(ocr.slice(0, 280)) + (ocr.length > 280 ? '…' : '') : '<em class="muted">none</em>'}</div>`,
      ai ? `<div class="provenance"><span class="label">AI description (inferred)</span>: ${esc(ai.slice(0, 320))}${ai.length > 320 ? '…' : ''}</div>` : ''
    ].join('');
  } else if (view.item_type === 'voice') {
    const title = view.title || view.original_filename || 'Voice note';
    const transcript = view.extracted_text || '';
    const cleaned = view.raw_text || '';
    const player = view.storage_path
      ? `<audio controls preload="none" src="/api/items/${view.id}/file"></audio>`
      : '';
    text.innerHTML = [
      `<strong>${esc(title)}</strong>`,
      `<div class="muted">${esc(view.original_filename || '')}</div>`,
      player,
      cleaned ? `<div class="voice-cleaned-text">${esc(cleaned)}</div>` : '',
      `<div class="provenance"><span class="label">Raw transcript</span>: ${transcript ? esc(transcript.slice(0, 320)) + (transcript.length > 320 ? '…' : '') : '<em class="muted">none yet — edit to add</em>'}</div>`
    ].join('');
  } else {
    text.textContent = view.raw_text;
  }

  if (note.secret_masked) {
    const hidden = document.createElement('div');
    hidden.className = 'provenance muted';
    hidden.textContent = 'Secret values hidden. Open the note to show them.';
    text.append(hidden);
  }

  // The user's own note about a saved source, shown apart from source text.
  if (view.user_context && view.item_type !== 'text') {
    const context = document.createElement('div');
    context.className = 'provenance user-context';
    context.innerHTML = `<span class="label">Your note</span>: ${esc(view.user_context)}`;
    text.prepend(context);
  }

  const time = document.createElement('div');
  time.className = 'time';
  const status = note.processing_status ? ` · ${note.processing_status}` : '';
  const error = note.error_message ? ` · ${note.error_message}` : '';
  time.textContent = `#${note.id} · ${note.item_type}${status}${error} · ${note.created_at}`;

  const actions = document.createElement('div');
  actions.className = 'note-actions';
  if (['url', 'pdf', 'image', 'voice'].includes(note.item_type) && note.processing_status !== 'failed') {
    actions.append(sourceNoteButton(note));
  }

  if (note.item_type === 'text') {
    const editButton = actionButton('Edit', 'secondary', () => {
      showEditNote(note, root);
    });
    const deleteButton = actionButton('Delete', 'danger', () => {
      deleteExistingNote(note, root, editButton, deleteButton);
    });
    actions.append(editButton, deleteButton);
  } else if (
    ['url', 'pdf', 'image', 'voice'].includes(note.item_type) &&
    note.processing_status === 'failed'
  ) {
    actions.append(sourceNoteButton(note));
    actions.append(
      actionButton('Retry', '', async () => {
        try {
          const updated = await fetchJson(
            `/api/items/${note.id}/retry`,
            {method: 'POST'},
            'Unable to retry capture processing.'
          );
          const failedOnlyFilter =
            document.getElementById('processingStatusFilter').value === 'failed';
          if (updated.processing_status === 'ready' && failedOnlyFilter) {
            root.remove();
            await loadNotes();
          } else {
            root.replaceWith(renderNote(updated));
          }
          const label = captureTypeLabel(note.item_type);
          setStatus(
            'noteStatus',
            updated.processing_status === 'ready'
              ? `${label} processed.`
              : `${label} still failed.`
          );
          await loadLatestAnalysis();
          await loadDashboard();
        } catch {
          setStatus('noteStatus', 'Retry failed.', true);
        }
      })
    );
    actions.append(
      actionButton('Delete', 'danger', () => {
        deleteExistingNote(note, root, null, null);
      })
    );
  } else if (
    (note.item_type === 'image' || note.item_type === 'voice') &&
    note.processing_status === 'ready'
  ) {
    if (note.item_type === 'voice') {
      actions.append(
        actionButton('Edit note', 'secondary', () => {
          showEditNote(note, root);
        })
      );
    }
    actions.append(
      actionButton(
        note.item_type === 'voice' ? 'Edit transcript' : 'Edit OCR text',
        'secondary',
        () => {
          showEditExtractedText(note, root);
        }
      )
    );
    actions.append(
      actionButton('Delete', 'danger', () => {
        deleteExistingNote(note, root, null, null);
      })
    );
  } else if (note.item_type === 'pdf') {
    actions.append(
      actionButton('Delete', 'danger', () => {
        deleteExistingNote(note, root, null, null);
      })
    );
  } else {
    actions.append(
      actionButton('Delete', 'danger', () => {
        deleteExistingNote(note, root, null, null);
      })
    );
  }

  const completeButton = actionButton('✓ Complete', 'complete-btn', async () => {
    if (pendingNoteActions.has(note.id)) return;
    pendingNoteActions.add(note.id);
    completeButton.disabled = true;
    setStatus('noteStatus', 'Completing note…');
    try {
      await fetchJson(
        `/api/items/${note.id}/complete`,
        {method: 'POST'},
        'Unable to complete note.'
      );
      completedNoteIdsCache.add(note.id);
      LifeInboxPagination.afterLoadedNoteDeleted(itemPagination, note.id);
      root.style.transition = 'all 0.3s ease';
      root.style.opacity = '0';
      root.style.transform = 'scale(0.95)';
      setTimeout(() => root.remove(), 300);
      setStatus('noteStatus', 'Note completed and removed from active inbox.');
      await loadTasks();
      await refreshAnalysisViews();
      await loadAttention();
      await loadCalendarEvents();
    } catch {
      setStatus('noteStatus', 'Could not complete note.', true);
      completeButton.disabled = false;
    } finally {
      pendingNoteActions.delete(note.id);
    }
  });
  actions.prepend(completeButton);

  root.append(text, time, actions);
  return root;
}

function showEditExtractedText(note, root) {
  if (pendingNoteActions.has(note.id)) return;

  const textarea = document.createElement('textarea');
  textarea.className = 'note-edit-input';
  textarea.maxLength = 20000;
  textarea.value = note.extracted_text || '';

  const hint = document.createElement('div');
  hint.className = 'provenance';
  const isVoice = note.item_type === 'voice';
  hint.innerHTML = isVoice
    ? '<span class="label">Editing transcript</span> (extracted text from the original audio).'
    : '<span class="label">Editing extracted / OCR text</span> (facts). AI description stays separate.';

  const actions = document.createElement('div');
  actions.className = 'note-actions';

  const saveButton = actionButton(isVoice ? 'Save transcript' : 'Save OCR text', '', async () => {
    if (pendingNoteActions.has(note.id)) return;
    pendingNoteActions.add(note.id);
    saveButton.disabled = true;
    cancelButton.disabled = true;
    saveButton.textContent = 'Saving…';
    setStatus('noteStatus', 'Saving extracted text…');
    try {
      const updated = await fetchJson(
        `/api/items/${note.id}/extracted-text`,
        {
          method: 'PATCH',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({extracted_text: textarea.value})
        },
        'Unable to update extracted text.'
      );
      root.replaceWith(renderNote(updated));
      setStatus('noteStatus', isVoice ? 'Transcript updated.' : 'Extracted text updated.');
      await loadLatestAnalysis();
      notifyEdited(note.id);
      autoAnalyzeInbox(note.id);
      await loadCalendarEvents();
    } catch {
      setStatus('noteStatus', 'Could not update extracted text.', true);
      saveButton.disabled = false;
      cancelButton.disabled = false;
      saveButton.textContent = isVoice ? 'Save transcript' : 'Save OCR text';
    } finally {
      pendingNoteActions.delete(note.id);
    }
  });

  const cancelButton = actionButton('Cancel', 'secondary', () => {
    if (pendingNoteActions.has(note.id)) return;
    root.replaceWith(renderNote(note));
  });

  actions.append(saveButton, cancelButton);
  root.replaceChildren(hint, textarea, actions);
}

function showEditNote(note, root) {
  if (pendingNoteActions.has(note.id)) return;

  const textarea = document.createElement('textarea');
  textarea.className = 'note-edit-input';
  textarea.maxLength = 2000;
  textarea.value = note.raw_text;

  const actions = document.createElement('div');
  actions.className = 'note-actions';

  const saveButton = actionButton('Save', '', async () => {
    const text = textarea.value.trim();
    if (!text) {
      setStatus('noteStatus', 'Edited note text cannot be empty.', true);
      textarea.focus();
      return;
    }
    if (pendingNoteActions.has(note.id)) return;

    pendingNoteActions.add(note.id);
    saveButton.disabled = true;
    cancelButton.disabled = true;
    saveButton.textContent = 'Saving…';
    setStatus('noteStatus', 'Saving your changes…');

    try {
      const updatedNote = await fetchJson(
        `/api/items/${note.id}`,
        {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({raw_text: text})
        },
        'Unable to update note.'
      );
      LifeInboxPagination.afterLoadedNoteUpdated(itemPagination, updatedNote);
      root.replaceWith(renderNote(updatedNote));
      setStatus('noteStatus', 'Note updated.');
      await loadLatestAnalysis();
      notifyEdited(note.id);
      autoAnalyzeInbox(note.id);
      await loadCalendarEvents();
    } catch {
      setStatus(
        'noteStatus',
        'We could not update this note. Your changes are still here—please try again.',
        true
      );
      saveButton.disabled = false;
      cancelButton.disabled = false;
      saveButton.textContent = 'Save';
    } finally {
      pendingNoteActions.delete(note.id);
    }
  });

  const cancelButton = actionButton('Cancel', 'secondary', () => {
    if (pendingNoteActions.has(note.id)) return;
    root.replaceWith(renderNote(note));
    setStatus('noteStatus', 'Edit cancelled.');
  });

  actions.append(saveButton, cancelButton);
  root.replaceChildren(textarea, actions);
  textarea.focus();
}

async function deleteExistingNote(note, root, editButton, deleteButton) {
  if (pendingNoteActions.has(note.id)) return;

  const confirmed = window.confirm(
    'Delete this item? This action cannot be undone.'
  );
  if (!confirmed) return;

  pendingNoteActions.add(note.id);
  if (editButton) editButton.disabled = true;
  if (deleteButton) {
    deleteButton.disabled = true;
    deleteButton.textContent = 'Deleting…';
  }
  setStatus('noteStatus', 'Deleting note…');

  try {
    await fetchJson(
      `/api/items/${note.id}`,
      {method: 'DELETE'},
      'Unable to delete note.'
    );
    LifeInboxPagination.afterLoadedNoteDeleted(itemPagination, note.id);
    root.remove();
    setStatus('noteStatus', 'Note deleted.');
    await refreshAnalysisViews();
    await loadTasks();
    await loadAttention();
    await loadCalendarEvents();
  } catch {
    setStatus(
      'noteStatus',
      'We could not delete this note. It is still here—please try again.',
      true
    );
    if (editButton) editButton.disabled = false;
    if (deleteButton) {
      deleteButton.disabled = false;
      deleteButton.textContent = 'Delete';
    }
  } finally {
    pendingNoteActions.delete(note.id);
  }
}

function renderTask(task) {
  const root = document.createElement('div');
  root.className = 'task';
  root.dataset.taskId = String(task.id);
  root.dataset.priority = String(task.priority || '').toLowerCase();

  const text = document.createElement('strong');
  text.textContent = task.text;

  const priority = document.createElement('span');
  priority.className = 'pill';
  priority.textContent = task.priority;

  const content = document.createElement('div');
  content.append(text, priority);

  const meta = document.createElement('div');
  meta.className = 'task-meta';
  // Where the date stands (change 012): confirmed by you, from your note's own
  // words, or a suggestion waiting for your OK.
  const dateStand = task.timing_confirmed && task.due_on
    ? ' (confirmed)'
    : task.due_on ? ' (from your note)' : task.suggested_due_on ? ' (suggested, confirm it)' : '';
  const timingLabel = task.timing_text ? ` · ${task.timing_text}${dateStand}` : '';
  const sources = task.source_item_ids
    .map(itemId => `#${itemId}`)
    .join(', ');
  meta.textContent = `${task.status}${timingLabel} · Sources: ${sources}`;

  const actions = document.createElement('div');
  actions.className = 'task-actions';

  if (task.status === 'open') {
    actions.append(
      actionButton('Complete', '', () => {
        transitionTask(task.id, 'complete', actions);
      }),
      actionButton('Edit', 'secondary', () => {
        showEditTask(task, root);
      }),
      actionButton('Dismiss', 'secondary', () => {
        transitionTask(task.id, 'dismiss', actions);
      })
    );
    // "Remind me tomorrow" keeps the date (change 018). A task at a set time
    // (a meeting, an appointment) only makes sense to postpone, so it's hidden.
    if (!task.due_time) actions.append(
      actionButton('Remind me tomorrow', 'secondary', async () => {
        // Tomorrow in your own time zone. A UTC date is still "yesterday" in
        // India until 05:30, so it snoozed only until later the same day.
        const until = new Date();
        until.setDate(until.getDate() + 1);
        const iso = toCalendarIsoDate(until);
        try {
          await fetchJson(
            `/api/tasks/${task.id}/snooze`,
            {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({until: iso})
            },
            'Unable to snooze task.'
          );
          setStatus('taskStatus', `It reminds you again tomorrow (${iso}). The date stays.`);
          await loadTasks();
          await loadAttention();
        } catch {
          setStatus('taskStatus', 'Could not set the reminder.', true);
        }
      })
    );
    if (task.suggested_due_on && !task.timing_confirmed) {
      actions.append(
        actionButton('Confirm date', 'secondary', async () => {
          try {
            await fetchJson(
              `/api/tasks/${task.id}/confirm-timing`,
              {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({timing_text: task.timing_text})
              },
              'Unable to confirm timing.'
            );
            setStatus('taskStatus', 'Timing confirmed.');
            await loadTasks();
            await loadDashboard();
            await loadAttention();
            await loadCalendarEvents();
          } catch {
            setStatus('taskStatus', 'Could not confirm timing.', true);
          }
        })
      );
    }
    const dateButton = actionButton(task.due_on ? 'Postpone' : 'Set date', 'secondary', () => {});
    dateButton.dataset.dateTask = String(task.id);
    actions.append(dateButton);
    if (task.timing_confirmed && (task.due_on || task.timing_text)) {
      actions.append(
        actionButton('Preview calendar', 'secondary', () => {
          previewCalendarForTask(task);
        })
      );
    }
  } else {
    actions.append(
      actionButton('Reopen', '', () => {
        transitionTask(task.id, 'reopen', actions);
      })
    );
  }

  root.append(content, meta, actions);
  return root;
}

function showEditTask(task, root) {
  const form = document.createElement('form');
  form.className = 'task-edit-form';

  const textInput = document.createElement('input');
  textInput.type = 'text';
  textInput.maxLength = 500;
  textInput.required = true;
  textInput.value = task.text;
  textInput.setAttribute('aria-label', 'Task');

  const prioritySelect = document.createElement('select');
  prioritySelect.setAttribute('aria-label', 'Priority');
  ['High', 'Medium', 'Low'].forEach((level) => {
    const option = document.createElement('option');
    option.value = level;
    option.textContent = level;
    option.selected = level === task.priority;
    prioritySelect.appendChild(option);
  });

  const dueInput = document.createElement('input');
  dueInput.type = 'date';
  dueInput.setAttribute('aria-label', 'Due date');
  dueInput.value = task.due_on || '';
  const hadDue = Boolean(task.due_on);

  const save = actionButton('Save', '', () => {});
  save.type = 'submit';
  const cancel = actionButton('Cancel', 'secondary', async () => {
    await loadTasks();
  });
  cancel.type = 'button';

  form.append(textInput, prioritySelect, dueInput, save, cancel);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const changes = {};
    const newText = textInput.value.trim();
    if (!newText) {
      setStatus('taskStatus', 'Task cannot be empty.', true);
      return;
    }
    if (newText !== task.text) changes.text = newText;
    if (prioritySelect.value !== task.priority) changes.priority = prioritySelect.value;
    if (dueInput.value && dueInput.value !== (task.due_on || '')) {
      changes.due_on = dueInput.value;
    } else if (!dueInput.value && hadDue) {
      changes.clear_due_date = true;
    }
    if (Object.keys(changes).length === 0) {
      await loadTasks();
      return;
    }
    save.disabled = true;
    try {
      await fetchJson(
        `/api/tasks/${task.id}`,
        {
          method: 'PATCH',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(changes)
        },
        'Unable to update task.'
      );
      setStatus('taskStatus', 'Task updated.');
      await loadTasks();
      await loadAttention();
      await refreshAnalysisViews();
      await loadCalendarEvents();
    } catch (error) {
      setStatus('taskStatus', error.message || 'Could not update task.', true);
      save.disabled = false;
    }
  });

  root.replaceChildren(form);
  textInput.focus();
}

async function transitionTask(taskId, action, actions) {
  if (pendingTaskActions.has(taskId)) return;

  pendingTaskActions.add(taskId);
  const buttons = actions ? actions.querySelectorAll('button') : [];
  buttons.forEach(button => {
    button.disabled = true;
  });
  setStatus('taskStatus', 'Updating task…');
  setStatus('inAppCalendarStatus', 'Updating task…');

  try {
    const updated = await fetchJson(
      `/api/tasks/${taskId}/${action}`,
      {method: 'POST'},
      'Unable to update task.'
    );
    if (action === 'complete' && updated.source_item_ids) {
      updated.source_item_ids.forEach(itemId => {
        completedNoteIdsCache.add(itemId);
        LifeInboxPagination.afterLoadedNoteDeleted(itemPagination, itemId);
        const noteEl = document.querySelector(`.note[data-note-id="${itemId}"]`);
        if (noteEl) {
          noteEl.style.transition = 'all 0.3s ease';
          noteEl.style.opacity = '0';
          noteEl.style.transform = 'scale(0.95)';
          setTimeout(() => noteEl.remove(), 300);
        }
      });
      await loadNotes();
    }
    if (action === 'reopen' && updated.source_item_ids) {
      updated.source_item_ids.forEach(itemId => {
        completedNoteIdsCache.delete(itemId);
      });
      await loadNotes();
    }
    const messages = {
      complete: 'Task completed. Associated notes removed.',
      dismiss: 'Task dismissed.',
      reopen: 'Task reopened.'
    };
    setStatus('taskStatus', messages[action]);
    setStatus('inAppCalendarStatus', messages[action]);
    await loadTasks();
    await loadAttention();
    await refreshAnalysisViews();
    await loadCalendarEvents();
  } catch {
    setStatus(
      'taskStatus',
      'We could not update this task. Please try again.',
      true
    );
    setStatus(
      'inAppCalendarStatus',
      'We could not update this task. Please try again.',
      true
    );
    buttons.forEach(button => {
      button.disabled = false;
    });
  } finally {
    pendingTaskActions.delete(taskId);
  }
}


async function createQuickTask(event) {
  event.preventDefault();

  const form = document.getElementById('quickTaskForm');
  const textInput = document.getElementById('quickTaskText');
  const priorityInput = document.getElementById('quickTaskPriority');
  const dueInput = document.getElementById('quickTaskDueOn');
  const submitButton = document.getElementById('quickTaskSubmit');

  const text = textInput.value.trim();

  if (!text) {
    setStatus('taskStatus', 'Please enter a task title.', true);
    textInput.focus();
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = 'Adding…';

  try {
    const dueOn = dueInput.value || null;
    await fetchJson(
      '/api/tasks',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          text,
          priority: priorityInput.value,
          due_on: dueOn
        })
      },
      'Unable to create task.'
    );

    form.reset();
    priorityInput.value = 'Medium';

    if (dueOn) {
      // Show the month (and day) the new task landed on so it is visible.
      const due = parseCalendarIsoDate(dueOn);
      calendarViewYear = due.getFullYear();
      calendarViewMonth = due.getMonth();
      calendarSelectedDateStr = dueOn;
    }

    await loadTasks();
    await loadAttention();
    await loadDashboard();
    await loadCalendarEvents();

    setStatus('taskStatus', 'Task added successfully.');
    textInput.focus();
  } catch {
    setStatus('taskStatus', 'Could not add task. Please try again.', true);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = 'Add task';
  }
}


async function loadTasks() {
  const filter = document.getElementById('taskStatusFilter').value;
  try {
    const tasks = await fetchJson(
      withLens(`/api/tasks?status=${encodeURIComponent(filter)}`),
      undefined,
      'Unable to load tasks.'
    );
    const root = document.getElementById('tasks');
    root.innerHTML = '';

    if (!tasks.length) {
      root.innerHTML = '<div class="panel muted">No tasks in this view.</div>';
      return true;
    }

    for (const task of tasks) {
      root.appendChild(renderTask(task));
    }
    return true;
  } catch {
    setStatus(
      'taskStatus',
      'We could not load tasks. Reload to try again.',
      true
    );
    return false;
  }
}

function renderAnalysis(data) {
  const root = document.getElementById('aiOutput');
  const generatedAt = data.generated_at
    ? new Date(data.generated_at).toLocaleString()
    : null;
  const staleBanner = data.is_stale
    ? `<div class="banner warn" role="status">Analysis is stale — inbox items changed since this run. Re-analyze to refresh.</div>`
    : '';

  const bucketHtml = (data.buckets || []).map(bucket => {
    const activeNotes = (bucket.notes || []).filter(n => !completedNoteIdsCache.has(n.id));
    if (!activeNotes.length) return '';
    return `
      <div class="panel">
        <h3>${esc(bucket.name)}</h3>
        <ul>
          ${activeNotes.map(n =>
            `<li>${esc(n.title)} <span class="pill">${esc(n.priority)}</span></li>`
          ).join('')}
        </ul>
      </div>
    `;
  }).join('');

  const todoHtml = (data.todos || []).filter(t => {
    const sources = t.source_note_ids || [];
    return !sources.some(id => completedNoteIdsCache.has(id));
  }).map(t =>
    `<li><strong>${esc(t.task)}</strong> <span class="pill">${esc(t.priority)}</span>${t.when ? ` · ${esc(t.when)}` : ''}</li>`
  ).join('');

  const pv = data.priority_view || {High: [], Medium: [], Low: []};
  const priorityHtml = ['High', 'Medium', 'Low'].map(level => {
    const activeNotes = (pv[level] || []).filter(n => !completedNoteIdsCache.has(n.id));
    return `
      <div class="panel">
        <h3>${level} priority (${activeNotes.length})</h3>
        <ul>
          ${activeNotes.map(n => `<li>${esc(n.title)}</li>`).join('') || '<li class="muted">None</li>'}
        </ul>
      </div>
    `;
  }).join('');

  root.innerHTML = `
    ${staleBanner}
    ${generatedAt ? `<p class="muted"><strong>Generated:</strong> ${esc(generatedAt)}</p>` : ''}

    <h3>Buckets</h3>
    ${bucketHtml || '<p class="muted">No notes yet.</p>'}

    <h3>ToDos</h3>
    <ul>${todoHtml || '<li class="muted">No concrete ToDos detected.</li>'}</ul>

    <h3>Priority view</h3>
    ${priorityHtml}

    <p class="muted">Mode: ${esc(data.mode || 'unknown')}</p>
  `;
}

async function loadLatestAnalysis() {
  try {
    await getCompletedNoteIds();
    const data = await fetchJson(
      '/api/analyze/latest',
      undefined,
      'Unable to load saved analysis.'
    );
    if (!data) return;

    populateCategoryFilter(data);
    renderAnalysis(data);
    const generatedAt = new Date(data.generated_at).toLocaleString();
    setStatus(
      'analysisStatus',
      data.is_stale
        ? `Saved analysis from ${generatedAt} is stale — re-analyze after inbox changes.`
        : `Showing saved analysis generated ${generatedAt}.`,
      Boolean(data.is_stale)
    );
  } catch {
    setStatus(
      'analysisStatus',
      'We could not load the saved analysis. You can try analyzing again.',
      true
    );
  }
}

// Re-render everything derived from analysis (AI-organized inbox, topic
// counts, dashboard) after a note is deleted or completed.
async function refreshAnalysisViews() {
  await loadLatestAnalysis();
  await loadTopics();
  await loadDashboard();
}

async function analyzeInbox(itemId = null) {
  analysisQueue.push(itemId);
  return processAnalysisQueue();
}

const itemPagination = LifeInboxPagination.createState(
  LifeInboxPagination.PAGE_SIZE
);

function updateLoadMoreButton(failureMessage) {
  const existingMore = document.getElementById('loadMoreItems');
  if (existingMore) existingMore.remove();
  if (!itemPagination.hasMore) return;

  const root = document.getElementById('notes');
  const more = document.createElement('button');
  more.id = 'loadMoreItems';
  more.type = 'button';
  more.className = 'secondary';
  more.textContent = itemPagination.listRequestInFlight
    ? 'Loading…'
    : 'Load more';
  more.disabled = itemPagination.listRequestInFlight;
  more.setAttribute(
    'aria-busy',
    String(itemPagination.listRequestInFlight)
  );
  more.addEventListener('click', () => {
    if (itemPagination.listRequestInFlight) return;
    loadNotes(failureMessage, {append: true});
  });
  root.appendChild(more);
}

async function loadNotes(
  failureMessage = 'We could not load your notes. Reload to try again.',
  {append = false} = {}
) {
  if (!LifeInboxPagination.beginListRequest(itemPagination)) {
    return false;
  }

  const params = itemFilterParams();
  if (!append) {
    LifeInboxPagination.resetForReload(itemPagination);
  }
  params.set('limit', String(itemPagination.pageSize));
  params.set('offset', String(itemPagination.loadedOffset));
  if (lensKey()) params.set('bot', lensKey());
  const filtered = [...params.keys()].some(
    key => key !== 'limit' && key !== 'offset' && params.get(key)
  );
  const failureCenterFilter = params.get('processing_status') === 'failed';
  const hasAdditionalFilters = [...params.keys()].some(
    key => !['limit', 'offset', 'processing_status'].includes(key) && params.get(key)
  );
  const emptyMessage = failureCenterFilter
    ? hasAdditionalFilters
      ? 'No failed items match these filters.'
      : 'No failed items. Nothing needs a retry.'
    : filtered
      ? 'No inbox items match these filters.'
      : 'No saved notes yet. Capture a thought above to get started.';
  const query = params.toString();

  if (append) {
    updateLoadMoreButton(failureMessage);
  }

  try {
    const notes = await fetchJson(
      `/api/items?${query}`,
      undefined,
      'Unable to load notes.'
    );
    const root = document.getElementById('notes');
    if (!append) {
      root.innerHTML = '';
    } else {
      const existingMore = document.getElementById('loadMoreItems');
      if (existingMore) existingMore.remove();
    }

    if (!append && !notes.length) {
      root.innerHTML = `<div class="panel muted">${emptyMessage}</div>`;
      setStatus(
        'searchStatus',
        failureCenterFilter ? emptyMessage : filtered ? 'No results found.' : ''
      );
      return true;
    }

    const {textNotes, hasMore} = LifeInboxPagination.applyFetchedPage(
      itemPagination,
      notes,
      {append}
    );

    const completedIds = await getCompletedNoteIds();
    const activeNotes = textNotes.filter(note => !completedIds.has(note.id));

    if (!append && !activeNotes.length) {
      const inactiveNotesMessage = failureCenterFilter
        ? emptyMessage
        : filtered
          ? 'No inbox items match these filters.'
          : 'No active saved notes. Capture a thought above or all completed!';
      root.innerHTML = `<div class="panel muted">${inactiveNotesMessage}</div>`;
      setStatus(
        'searchStatus',
        failureCenterFilter
          ? emptyMessage
          : filtered
            ? 'No results found.'
            : ''
      );
      return true;
    }

    for (const note of activeNotes) {
      root.appendChild(renderNote(note));
    }

    if (hasMore) {
      updateLoadMoreButton(failureMessage);
    }

    const loadedCount = itemPagination.loadedItems.length;
    setStatus(
      'searchStatus',
      filtered
        ? `${loadedCount}${hasMore ? '+' : ''} matching item${loadedCount === 1 ? '' : 's'}.`
        : hasMore
          ? `Showing ${loadedCount}+ items.`
          : ''
    );
    return true;
  } catch {
    if (append) {
      setStatus(
        'noteStatus',
        'We could not load more notes. Your current notes are still here—please try again.',
        true
      );
      updateLoadMoreButton(failureMessage);
    } else if (filtered) {
      setStatus(
        'searchStatus',
        'Search failed. Please try again.',
        true
      );
    } else {
      setStatus('noteStatus', failureMessage, true);
    }
    return false;
  } finally {
    LifeInboxPagination.endListRequest(itemPagination);
    if (itemPagination.hasMore) {
      updateLoadMoreButton(failureMessage);
    }
  }
}

// Topics are drawn by shell.js: cards grouped by life area, and a page per
// topic with rename, move and delete (change 010). Callers still call this
// after a change, and the shell redraws.
async function loadTopics() {
  if (window.LifeInboxShell) await window.LifeInboxShell.refreshTopics();
}

// --- Delete a user topic, after an inline "Are you sure?" -------------------

function topicDeletePreview(topic, parent, subtopics) {
  const n = topic.item_count;
  const notes = `${n} note${n === 1 ? '' : 's'}`;
  let text = `Delete “${topic.name}”? `;
  if (parent) {
    text += n ? `Its ${notes} will move to ${parent.name}.` : 'It has no notes.';
  } else {
    text += n ? `Its ${notes} will be re-sorted into your other topics.` : 'It has no notes.';
  }
  if (subtopics.length) {
    const names = subtopics.map(t => `“${t.name}”`).join(', ');
    text += ` Its subtopic${subtopics.length === 1 ? '' : 's'} ${names} will become main topic${subtopics.length === 1 ? '' : 's'}.`;
  }
  return `${text} This can't be undone.`;
}

function topicDeleteSummary(result) {
  let text = `Deleted “${result.deleted.name}”.`;
  const moved = result.moved_notes || [];
  if (result.moved_to_parent && moved.length) {
    text += ` ${moved.length} note${moved.length === 1 ? '' : 's'} moved to ${result.moved_to_parent.name}.`;
  } else if (moved.length) {
    const counts = {};
    for (const note of moved) counts[note.topic_name] = (counts[note.topic_name] || 0) + 1;
    const parts = Object.entries(counts).map(([name, n]) => `${n} to ${name}`);
    text += ` ${moved.length} note${moved.length === 1 ? '' : 's'} re-sorted: ${parts.join(', ')}.`;
  }
  for (const sub of result.promoted_subtopics || []) {
    text += ` “${sub.name}” is now a main topic.`;
  }
  return text;
}

// --- Add topic: name + description, then an optional subtopic suggestion ---
let pendingTopic = null;

function postTopicJson(url, body) {
  return topicRequest('POST', url, body);
}

async function topicRequest(method, url, body) {
  const response = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers: body === undefined ? {} : {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (response.status === 401) {
    leaveToLogin();
    throw new Error('Signed out.');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : 'Something went wrong. Please try again.';
    throw new Error(detail);
  }
  if (String(method).toUpperCase() !== 'GET') notifyChanged();
  return data;
}

function resetTopicForm() {
  pendingTopic = null;
  document.getElementById('topicSuggestion').hidden = true;
  document.getElementById('topicForm').hidden = false;
  document.getElementById('topicAcceptParent').hidden = false;
  document.getElementById('topicKeepSeparate').textContent = 'Keep it as a separate topic';
  const next = document.getElementById('topicNextButton');
  next.disabled = false;
  next.textContent = 'Next';
}

// The suggestion step: an optional parent topic, and the life area (change 010).
function showTopicChoice(name, suggestion) {
  const parent = suggestion.suggested_parent;
  const area = document.getElementById('topicBotChoice');
  area.value = (suggestion.suggested_bot && suggestion.suggested_bot.key) || '';
  if (parent) {
    document.getElementById('topicSuggestionText').textContent =
      `“${name}” looks like part of ${parent.name}. Make it a subtopic of ${parent.name}?`;
    document.getElementById('topicAcceptParent').textContent = `Yes, make it a subtopic of ${parent.name}`;
    document.getElementById('topicAcceptParent').hidden = false;
    document.getElementById('topicBotLabel').textContent = 'If it stays separate, its life area:';
    document.getElementById('topicKeepSeparate').textContent = 'Keep it as a separate topic';
  } else {
    document.getElementById('topicSuggestionText').textContent =
      `Which part of life is “${name}” about?`;
    document.getElementById('topicAcceptParent').hidden = true;
    document.getElementById('topicBotLabel').textContent = 'Life area';
    document.getElementById('topicKeepSeparate').textContent = 'Create topic';
  }
  document.getElementById('topicSuggestionReason').textContent = suggestion.reason || '';
  document.getElementById('topicForm').hidden = true;
  document.getElementById('topicSuggestion').hidden = false;
  setStatus('topicStatus', '');
  document.getElementById(parent ? 'topicAcceptParent' : 'topicBotChoice').focus();
}

function cancelTopicSuggestion() {
  resetTopicForm();
  setStatus('topicStatus', 'Nothing was created.');
  document.getElementById('topicName').focus();
}

async function createTopic(event) {
  event.preventDefault();
  const name = document.getElementById('topicName').value.trim();
  const description = document.getElementById('topicDescription').value.trim();
  if (!name) {
    setStatus('topicStatus', 'Give the topic a name.', true);
    return;
  }
  if (!description) {
    setStatus('topicStatus', 'Add a short description so Life Inbox knows which notes belong here.', true);
    return;
  }
  const next = document.getElementById('topicNextButton');
  next.disabled = true;
  next.textContent = 'Checking…';
  setStatus('topicStatus', 'Checking whether this fits under an existing topic…');
  try {
    const suggestion = await postTopicJson('/api/topics/suggest-parent', {name, description});
    pendingTopic = {name, description, suggestion};
    showTopicChoice(name, suggestion);
  } catch (error) {
    setStatus('topicStatus', error.message, true);
    resetTopicForm();
  }
}

async function confirmTopic(asSubtopic) {
  if (!pendingTopic) return;
  const {name, description, suggestion} = pendingTopic;
  const parent = asSubtopic && suggestion.suggested_parent ? suggestion.suggested_parent : null;
  // A subtopic always shares its parent's area; otherwise the user's pick, or
  // none and the server's keyword rules choose.
  const botKey = parent ? null : (document.getElementById('topicBotChoice').value || null);
  try {
    const created = await postTopicJson('/api/topics', {
      name,
      description,
      parent_topic_id: parent ? parent.id : null,
      bot_key: botKey
    });
    document.getElementById('topicName').value = '';
    document.getElementById('topicDescription').value = '';
    resetTopicForm();
    const areaName = created && created.bot_key
      ? (document.querySelector(`#topicBotChoice option[value="${created.bot_key}"]`) || {}).textContent
      : '';
    setStatus(
      'topicStatus',
      parent
        ? `Added “${name}” as a subtopic of ${parent.name}. Re-sorting your notes…`
        : `Added “${name}”${areaName ? ` to ${areaName}` : ''}. Re-sorting your notes…`
    );
    await loadTopics();
    // Re-check only the notes whose words fit the new topic (change 014: at
    // most 25 notes, so 0-1 AI call), then offer to undo the moves.
    const where = parent ? ` under ${parent.name}` : (areaName ? ` to ${areaName}` : '');
    const recheck = await fetchJson(`/api/topics/${created.id}/recheck`, {method: 'POST'}, 'Could not re-check your notes.');
    const moved = recheck.moved || [];
    setStatus(
      'topicStatus',
      moved.length
        ? `Added “${name}”${where}. Moved ${moved.length} note${moved.length === 1 ? '' : 's'} into it.`
        : `Added “${name}”${where}. No saved note fits it yet.`
    );
    if (moved.length) {
      await loadNotes();
      await loadTopics();
      if (window.LifeInboxShell && window.LifeInboxShell.toast) {
        window.LifeInboxShell.toast(`Moved ${moved.length} note${moved.length === 1 ? '' : 's'} into ${name}.`, {
          actions: [{label: 'Undo', run: async () => {
            await fetchJson('/api/filing/undo-moves', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({moves: moved}),
            }, 'Could not undo.');
            setStatus('topicStatus', `Put ${moved.length} note${moved.length === 1 ? '' : 's'} back where they were.`);
            await loadNotes();
            await loadTopics();
            window.dispatchEvent(new CustomEvent('lifeinbox:changed'));
          }}],
        });
      }
      window.dispatchEvent(new CustomEvent('lifeinbox:changed'));
    }
  } catch (error) {
    setStatus('topicStatus', error.message, true);
    resetTopicForm();
  }
}

// Main topics with their subtopics nested underneath; counts include subtopics.
function renderDashboardTopics(topics) {
  if (!topics || !topics.length) return '<p class="muted">Nothing here yet.</p>';
  const ids = new Set(topics.map(t => t.id));
  const children = {};
  for (const t of topics) {
    if (t.parent_topic_id && ids.has(t.parent_topic_id)) {
      (children[t.parent_topic_id] ||= []).push(t);
    }
  }
  const items = topics
    .filter(t => !(t.parent_topic_id && ids.has(t.parent_topic_id)))
    .map(t => {
      const total = t.total_item_count ?? t.item_count;
      const subs = (children[t.id] || [])
        .map(c => `<li><strong>${esc(c.name)}</strong> · ${c.item_count}</li>`)
        .join('');
      return `<li><strong>${esc(t.name)}</strong> · ${total}${subs ? `<ul class="dashboard-subtopics">${subs}</ul>` : ''}</li>`;
    })
    .join('');
  return `<ul>${items}</ul>`;
}

const CHART_COLORS = ['var(--li-pop)', 'var(--li-rose)', 'var(--li-amber)', 'var(--li-primary)', 'var(--li-primary-deep)'];

function renderTopicsChart(topics) {
  const data = (topics || [])
    .filter(t => t.item_count > 0)
    .sort((a, b) => b.item_count - a.item_count)
    .slice(0, 8);
  if (!data.length) {
    return '<p class="muted">Nothing here yet.</p>';
  }
  const max = Math.max(...data.map(t => t.item_count));
  const rowH = 30;
  const gap = 10;
  const trackW = 220;
  const labelW = 110;
  const valueW = 28;
  const labelMaxChars = 15;
  const totalW = labelW + trackW + valueW;
  const height = data.length * (rowH + gap) - gap;
  const truncate = name =>
    name.length > labelMaxChars ? `${name.slice(0, labelMaxChars - 1)}…` : name;
  const rows = data.map((t, i) => {
    const barW = Math.max(6, Math.round((t.item_count / max) * trackW));
    const y = i * (rowH + gap);
    const color = CHART_COLORS[i % CHART_COLORS.length];
    return `
      <g transform="translate(0, ${y})">
        <text x="0" y="${rowH / 2 + 4}" class="chart-label"><title>${esc(t.name)}</title>${esc(truncate(t.name))}</text>
        <rect x="${labelW}" y="3" width="${trackW}" height="${rowH - 6}" fill="var(--li-paper-dim)" stroke="var(--li-ink)" stroke-width="2"></rect>
        <rect x="${labelW}" y="3" width="${barW}" height="${rowH - 6}" fill="${color}" stroke="var(--li-ink)" stroke-width="2"></rect>
        <text x="${labelW + trackW + 8}" y="${rowH / 2 + 4}" class="chart-value">${t.item_count}</text>
      </g>
    `;
  }).join('');
  const summary = data.map(t => `${t.name}: ${t.item_count}`).join(', ');
  return `
    <svg viewBox="0 0 ${totalW} ${height}" width="100%" height="${height}" role="img" aria-label="Bar chart of saved items per topic">
      <title>Items per topic</title>
      <desc>${esc(summary)}</desc>
      ${rows}
    </svg>
  `;
}

async function loadDashboard() {
  try {
    const data = await fetchJson(
      '/api/dashboard',
      undefined,
      'Unable to load dashboard.'
    );
    const root = document.getElementById('dashboard');
    const section = (title, body) => `
      <div class="panel">
        <h3>${esc(title)}</h3>
        ${body}
      </div>
    `;
    const listOrEmpty = (items, render) =>
      items && items.length
        ? `<ul>${items.map(render).join('')}</ul>`
        : '<p class="muted">Nothing here yet.</p>';

    const completedIds = await getCompletedNoteIds();
    const activeHighPriority = (data.high_priority || []).filter(item => !completedIds.has(item.id));
    const activeRecentlyCaptured = (data.recently_captured || []).filter(item => !completedIds.has(item.id));
    const activeNeedsReview = (data.needs_review || []).filter(item => !completedIds.has(item.id));

    root.innerHTML = `
      <div class="dashboard-grid">
        ${section('Topics / Spaces', renderDashboardTopics(data.topics))}
        ${section('High Priority', listOrEmpty(activeHighPriority, item =>
          `<li>${esc(item.effective_title || item.raw_text || ('#' + item.id))}${item.rationale ? `<div class="why">Why: ${esc(item.rationale)}</div>` : ''}</li>`
        ))}
        ${section('Open Tasks', listOrEmpty(data.open_tasks, task =>
          `<li><strong>${esc(task.text)}</strong> <span class="pill">${esc(task.priority)}</span>${task.timing_text ? ` · ${esc(task.timing_text)}${task.timing_confirmed ? ' (confirmed)' : ' (AI suggested)'}` : ''}</li>`
        ))}
        ${section('Recently Captured', listOrEmpty(activeRecentlyCaptured, item =>
          `<li>#${item.id} · ${esc((item.raw_text || '').slice(0, 80))}</li>`
        ))}
        ${section('Needs Review', listOrEmpty(activeNeedsReview, item =>
          `<li>#${item.id} · ${esc(item.reason || 'Review needed')}</li>`
        ))}
        <div class="panel dashboard-chart">
          <h3>Items by Topic</h3>
          ${renderTopicsChart(data.topics)}
        </div>
      </div>
    `;
    setStatus('dashboardStatus', 'Dashboard updated.');
  } catch {
    setStatus('dashboardStatus', 'We could not load the organized dashboard.', true);
  }
}

function fillAskExample(text) {
  const input = document.getElementById('askQuestion');
  input.value = text;
  input.focus();
}

function askAreaName(key) {
  const shell = window.LifeInboxShell;
  return shell && shell.areaName ? shell.areaName(key) : key;
}

function askDay(iso) {
  const day = new Date(`${iso}T00:00:00`);
  return Number.isNaN(day.getTime()) ? iso : day.toLocaleDateString(undefined, {weekday: 'short', day: 'numeric', month: 'short'});
}

function noteLinks(ids) {
  return (ids || []).map(id => `<button type="button" class="link-btn small" data-open-note="${Number(id)}">note #${Number(id)}</button>`).join(' ');
}

function renderAskResponse(data) {
  const root = document.getElementById('askOutput');
  root.innerHTML = '';
  const confidence = document.createElement('div');
  confidence.className = 'confidence';
  const modeLabel = data.mode ? ` · ${String(data.mode).replaceAll('_', ' ')}` : '';
  confidence.textContent = `Confidence: ${data.confidence} · ${data.answer_kind.replace('_', ' ')}${modeLabel}`;
  const answer = document.createElement('div');
  answer.textContent = data.answer;
  root.append(confidence, answer);
  // Change 019: what it remembered and your tasks, each with its notes.
  if (data.facts && data.facts.length) {
    const block = document.createElement('div');
    block.className = 'citation';
    block.innerHTML = `<h3>From what Life Inbox remembers</h3>${data.facts.map(fact =>
      `<div>${esc(fact.text)} ${noteLinks(fact.source_item_ids)}</div>`).join('')}`;
    root.appendChild(block);
  }
  if (data.tasks && data.tasks.length) {
    const block = document.createElement('div');
    block.className = 'citation';
    block.innerHTML = `<h3>From your tasks</h3>${data.tasks.map(task =>
      `<div>${esc(task.text)} · ${esc(askDay(task.day))}${task.time ? ` ${esc(task.time)}` : ''}${task.status === 'completed' ? ' · done' : task.confirmed ? '' : ' · <em>date not confirmed</em>'} ${noteLinks(task.source_item_ids)}</div>`).join('')}`;
    root.appendChild(block);
  }
  if (data.suggested_actions && data.suggested_actions.length) {
    const block = document.createElement('div');
    block.className = 'ask-actions';
    for (const action of data.suggested_actions) {
      // Nothing runs until you tap it.
      block.appendChild(actionButton(action.label, 'secondary', async () => {
        try {
          await fetchJson(`/api/tasks/${action.task_id}/date`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(action.due_time ? {due_on: action.due_on, due_time: action.due_time} : {due_on: action.due_on})
          }, 'Unable to confirm the date.');
          setStatus('askStatus', `Confirmed ${askDay(action.due_on)}.`);
          window.dispatchEvent(new CustomEvent('lifeinbox:changed'));
          block.querySelectorAll('button').forEach(button => { if (button.textContent === action.label) button.remove(); });
        } catch {
          setStatus('askStatus', 'Could not confirm the date.', true);
        }
      }));
    }
    root.appendChild(block);
  }
  if (data.how) {
    const how = data.how;
    const details = document.createElement('details');
    details.className = 'ask-how';
    const areas = (how.areas || []).map(askAreaName);
    const parts = [
      how.lens ? `Asked only ${esc(askAreaName(how.lens))} (your lens)` : areas.length ? `Asked: ${esc(areas.join(', '))}` : 'No area matched',
      `read ${how.notes_read.length} note${how.notes_read.length === 1 ? '' : 's'}${how.notes_read.length ? ` (${how.notes_read.map(id => `#${id}`).join(', ')})` : ''}`,
      `used ${how.memory_used} of ${how.facts_considered} remembered fact${how.facts_considered === 1 ? '' : 's'}`,
      how.period ? `looked at ${how.tasks_read} task${how.tasks_read === 1 ? '' : 's'} for ${esc(how.period)}` : '',
      how.ai_calls ? `${how.ai_calls} AI call${how.ai_calls === 1 ? '' : 's'}` : 'no AI call',
    ].filter(Boolean);
    details.innerHTML = `<summary>How I answered</summary><p class="muted small">${parts.join(' · ')}.</p>`;
    root.appendChild(details);
  }
  if (data.citations && data.citations.length) {
    const heading = document.createElement('h3');
    heading.textContent = 'Sources';
    root.appendChild(heading);
    for (const cite of data.citations) {
      const block = document.createElement('div');
      block.className = 'citation';
      const link = cite.preview_url
        ? `<a href="${esc(cite.preview_url)}" target="_blank" rel="noopener">Open source</a>`
        : '';
      block.innerHTML = `<strong>${esc(cite.title)}</strong> (#${cite.item_id} · ${esc(cite.source_kind)}) ${link}<div>${esc(cite.excerpt)}</div>`;
      root.appendChild(block);
    }
  }
}

async function askInbox(event) {
  event.preventDefault();
  const input = document.getElementById('askQuestion');
  const question = input.value.trim();
  if (!question) return;
  setButtonBusy('askButton', true, 'Thinking…', 'Ask');
  setStatus('askStatus', 'Searching your inbox…');
  try {
    const data = await fetchJson(
      '/api/ask',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        // Change 019: the lens, so only that area's notes are read.
        body: JSON.stringify({question, bot: (window.LifeInboxShell && window.LifeInboxShell.lensKey && window.LifeInboxShell.lensKey()) || undefined})
      },
      'Unable to answer from your inbox.'
    );
    renderAskResponse(data);
    setStatus('askStatus', data.confidence === 'insufficient' ? 'Not enough evidence in your inbox.' : 'Answer ready.');
  } catch {
    setStatus('askStatus', 'Ask My Inbox failed.', true);
  } finally {
    setButtonBusy('askButton', false, 'Thinking…', 'Ask');
  }
}

async function loadAttention() {
  const briefingRoot = document.getElementById('briefing');
  const attentionRoot = document.getElementById('attention');
  try {
    const [briefing, board] = await Promise.all([
      fetchJson('/api/briefing', {}, 'Unable to load briefing.'),
      fetchJson('/api/attention', {}, 'Unable to load attention board.')
    ]);
    briefingRoot.innerHTML = [
      `<strong>Daily briefing</strong> · ${esc(briefing.reference_date)}`,
      `<div>${esc(briefing.summary)}</div>`,
      briefing.priority_suggestions.length
        ? `<div class="provenance"><span class="label">Suggested focus</span>: ${
            briefing.priority_suggestions
              .map(item => `#${item.task_id} ${esc(item.text)} (${esc(item.reason)})`)
              .join('; ')
          }</div>`
        : '<div class="muted">No timed open tasks yet.</div>'
    ].join('');

    const sections = [
      ['overdue', 'Overdue'],
      ['today', 'Today'],
      ['upcoming', 'Upcoming'],
      ['unscheduled', 'Unscheduled'],
      ['snoozed', 'Snoozed']
    ];
    attentionRoot.replaceChildren();
    for (const [key, label] of sections) {
      const panel = document.createElement('div');
      panel.className = `panel attention-tile attention-tile--${key}`;
      const items = board[key] || [];
      panel.innerHTML = `
        <div class="attention-tile-head">
          <span class="attention-tile-value">${items.length}</span>
          <span class="attention-tile-label">${esc(label)}</span>
        </div>
      `;
      if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'muted';
        empty.textContent = 'None';
        panel.appendChild(empty);
      } else {
        for (const item of items.slice(0, 8)) {
          const row = document.createElement('div');
          row.className = 'task-meta';
          const phrase = item.original_timing_phrase
            ? ` · “${item.original_timing_phrase}”`
            : '';
          const due = item.normalized_due_on ? ` → ${item.normalized_due_on}` : '';
          const conf = item.due_confidence ? ` · ${item.due_confidence}` : '';
          const needs = item.needs_confirmation ? ' · needs confirmation' : '';
          row.textContent = `#${item.id} ${item.text}${phrase}${due}${conf}${needs}`;
          panel.appendChild(row);
        }
      }
      attentionRoot.appendChild(panel);
    }
    setStatus('briefingStatus', 'Attention board updated.');
  } catch {
    setStatus('briefingStatus', 'Could not load attention board.', true);
  }
}

async function previewCalendarForTask(task) {
  setStatus('calendarStatus', 'Building calendar preview…');
  try {
    const preview = await fetchJson(
      '/api/calendar/preview',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({task_id: task.id})
      },
      'Unable to preview calendar event.'
    );
    const root = document.getElementById('calendarPreview');
    root.innerHTML = [
      `<strong>Calendar preview</strong> (${esc(preview.provider)} / ${esc(preview.status)})`,
      `<div>${esc(preview.title)} · ${esc(preview.start_date)} (${esc(preview.timezone)})</div>`,
      `<div class="provenance">${(preview.notes || []).map(note => esc(note)).join(' · ')}</div>`
    ].join('');
    const confirmBtn = actionButton('Confirm (mock only)', '', async () => {
      try {
        const confirmed = await fetchJson(
          '/api/calendar/confirm',
          {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({draft_id: preview.draft_id})
          },
          'Unable to confirm calendar action.'
        );
        setStatus(
          'calendarStatus',
          confirmed.status === 'confirmed_mock'
            ? 'Mock calendar confirmation recorded. No external event created.'
            : `Calendar action status: ${confirmed.status}`
        );
        root.innerHTML += `<div class="provenance"><span class="label">Receipt</span>: ${esc(confirmed.status)} / ${esc(confirmed.provider)}</div>`;
      } catch (error) {
        setStatus('calendarStatus', error.message || 'Calendar confirm blocked or failed.', true);
      }
    });
    root.appendChild(confirmBtn);
    const readyMessage = 'Preview ready — confirm explicitly to record a mock receipt.';
    setStatus('calendarStatus', readyMessage);
    // The preview panel lives in the Calendar zone, away from the Tasks list
    // where the button is, so report here too and bring the panel into view.
    setStatus('taskStatus', `${readyMessage} Shown in the Calendar section.`);
    root.scrollIntoView({behavior: 'smooth', block: 'center'});
  } catch (error) {
    const message = error.message || 'Calendar preview failed.';
    setStatus('calendarStatus', message, true);
    setStatus('taskStatus', message, true);
  }
}

async function loadAuthUser() {
  try {
    const user = await fetchJson('/api/auth/me', {}, 'Unable to load session.');
    document.getElementById('authUser').textContent =
      `Signed in as ${user.display_name} <${user.email}>`;
  } catch {
    document.getElementById('authUser').textContent = 'Session unavailable.';
  }
}

function leaveToLogin() {
  // Drop everything rendered for this user before navigating away.
  document.body.innerHTML = '';
  window.location.replace('/login');
}

async function logoutSession() {
  try {
    await fetchJson('/api/auth/logout', {method: 'POST'}, 'Unable to sign out.');
  } catch {
    // The cookie may already be gone; the login page is still the right place.
  }
  leaveToLogin();
}

async function logoutAllSessions() {
  if (!confirm('Sign out of Life Inbox on every device?')) return;
  try {
    await fetchJson('/api/auth/logout-all', {method: 'POST'}, 'Unable to sign out.');
  } catch {
    // Fall through to the login page either way.
  }
  leaveToLogin();
}

async function changePassword(event) {
  event.preventDefault();
  const currentPassword = document.getElementById('currentPassword');
  const newPassword = document.getElementById('newPassword');
  const confirmPassword = document.getElementById('newPasswordConfirm');
  if (!PasswordRules.allPass(newPassword.value)) {
    setStatus('authStatus', PasswordRules.unmetSummary(newPassword.value), true);
    return;
  }
  if (newPassword.value !== confirmPassword.value) {
    setStatus('authStatus', 'New passwords do not match.', true);
    return;
  }
  const button = document.getElementById('changePasswordButton');
  button.disabled = true;
  try {
    const response = await fetch('/api/auth/password/change', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        current_password: currentPassword.value,
        new_password: newPassword.value
      })
    });
    if (response.status === 401) {
      leaveToLogin();
      return;
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : 'Unable to change password.';
      setStatus('authStatus', detail, true);
      return;
    }
    currentPassword.value = '';
    newPassword.value = '';
    confirmPassword.value = '';
    setStatus('authStatus', 'Password updated. Other devices have been signed out.');
  } catch {
    setStatus('authStatus', 'Unable to change password.', true);
  } finally {
    button.disabled = false;
  }
}

// --- In-App Calendar Component ---
let calendarViewYear = new Date().getFullYear();
let calendarViewMonth = new Date().getMonth();
let calendarSelectedDateStr = toCalendarIsoDate(new Date());
let calendarEventsByDate = new Map();

function toCalendarIsoDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function parseCalendarIsoDate(str) {
  const [y, m, d] = str.split('-').map(Number);
  return new Date(y, m - 1, d);
}

function changeCalendarMonth(delta) {
  calendarViewMonth += delta;
  if (calendarViewMonth < 0) {
    calendarViewMonth = 11;
    calendarViewYear -= 1;
  } else if (calendarViewMonth > 11) {
    calendarViewMonth = 0;
    calendarViewYear += 1;
  }
  loadCalendarEvents();
}

function jumpCalendarToToday() {
  const today = new Date();
  calendarViewYear = today.getFullYear();
  calendarViewMonth = today.getMonth();
  calendarSelectedDateStr = toCalendarIsoDate(today);
  loadCalendarEvents();
}

async function loadCalendarEvents() {
  const gridEl = document.getElementById('calendarGrid');
  if (!gridEl) return;

  const firstDay = new Date(calendarViewYear, calendarViewMonth, 1);
  const lastDay = new Date(calendarViewYear, calendarViewMonth + 1, 0);

  // Monday-based week: 0=Mon, 6=Sun
  const startDayOfWeek = (firstDay.getDay() + 6) % 7;
  const gridStart = new Date(firstDay);
  gridStart.setDate(firstDay.getDate() - startDayOfWeek);

  const endDayOfWeek = (lastDay.getDay() + 6) % 7;
  const gridEnd = new Date(lastDay);
  gridEnd.setDate(lastDay.getDate() + (6 - endDayOfWeek));

  const startIso = toCalendarIsoDate(gridStart);
  const endIso = toCalendarIsoDate(gridEnd);

  try {
    const events = await fetchJson(
      withLens(`/api/calendar/events?start=${startIso}&end=${endIso}`),
      {},
      'Unable to load calendar events.'
    );

    calendarEventsByDate = new Map();
    for (const ev of events) {
      if (!calendarEventsByDate.has(ev.event_date)) {
        calendarEventsByDate.set(ev.event_date, []);
      }
      calendarEventsByDate.get(ev.event_date).push(ev);
    }
    renderCalendar(gridStart, gridEnd);
    renderSelectedDayEvents();
  } catch {
    setStatus('inAppCalendarStatus', 'Could not load calendar events.', true);
  }
}

function renderCalendar(gridStart, gridEnd) {
  const titleEl = document.getElementById('calMonthYear');
  const gridEl = document.getElementById('calendarGrid');
  if (!titleEl || !gridEl) return;

  const monthNames = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
  ];
  titleEl.textContent = `${monthNames[calendarViewMonth]} ${calendarViewYear}`;

  gridEl.replaceChildren();

  const daysOfWeek = [
    ['Mon', 'Monday'],
    ['Tue', 'Tuesday'],
    ['Wed', 'Wednesday'],
    ['Thu', 'Thursday'],
    ['Fri', 'Friday'],
    ['Sat', 'Saturday'],
    ['Sun', 'Sunday']
  ];
  for (const [shortName, fullName] of daysOfWeek) {
    const colHeader = document.createElement('div');
    colHeader.className = 'cal-day-header';
    colHeader.setAttribute('role', 'columnheader');
    colHeader.setAttribute('aria-label', fullName);
    colHeader.textContent = shortName;
    gridEl.appendChild(colHeader);
  }

  const todayStr = toCalendarIsoDate(new Date());
  const iter = new Date(gridStart);

  while (iter <= gridEnd) {
    const dateStr = toCalendarIsoDate(iter);
    const dayNum = iter.getDate();
    const isOtherMonth = iter.getMonth() !== calendarViewMonth;
    const isToday = dateStr === todayStr;
    const isSelected = dateStr === calendarSelectedDateStr;
    const dayEvents = calendarEventsByDate.get(dateStr) || [];

    const cell = document.createElement('div');
    cell.className = 'cal-day-cell' +
      (isOtherMonth ? ' cal-day-other' : '') +
      (isToday ? ' cal-day-today' : '') +
      (isSelected ? ' cal-day-selected' : '');
    cell.setAttribute('role', 'gridcell');
    cell.tabIndex = 0;
    cell.dataset.date = dateStr;
    cell.setAttribute('aria-selected', isSelected ? 'true' : 'false');

    const formattedLabel = iter.toLocaleDateString(undefined, {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    });
    cell.setAttribute(
      'aria-label',
      `${formattedLabel}${dayEvents.length ? `, ${dayEvents.length} events` : ', no events'}`
    );

    const numSpan = document.createElement('span');
    numSpan.className = 'cal-day-num';
    numSpan.textContent = String(dayNum);
    cell.appendChild(numSpan);

    if (dayEvents.length > 0) {
      const dotsContainer = document.createElement('div');
      dotsContainer.className = 'cal-event-dots';

      for (const ev of dayEvents.slice(0, 3)) {
        const dot = document.createElement('span');
        dot.className = `cal-dot cal-dot-${ev.bot_key || 'none'}` +
          (ev.status === 'completed' ? ' completed' : ev.needs_confirmation ? ' unconfirmed' : '');
        dotsContainer.appendChild(dot);
      }
      if (dayEvents.length > 3) {
        const moreSpan = document.createElement('span');
        moreSpan.style.fontSize = '9px';
        moreSpan.style.color = '#64748b';
        moreSpan.textContent = `+${dayEvents.length - 3}`;
        dotsContainer.appendChild(moreSpan);
      }
      cell.appendChild(dotsContainer);
    }

    const cellDateCopy = new Date(iter);
    cell.addEventListener('click', () => {
      calendarSelectedDateStr = dateStr;
      if (isOtherMonth) {
        calendarViewMonth = cellDateCopy.getMonth();
        calendarViewYear = cellDateCopy.getFullYear();
        loadCalendarEvents();
      } else {
        renderCalendar(gridStart, gridEnd);
        renderSelectedDayEvents();
      }
    });

    cell.addEventListener('keydown', (e) => {
      let targetDate = parseCalendarIsoDate(dateStr);
      let handled = false;
      if (e.key === 'ArrowLeft') {
        targetDate.setDate(targetDate.getDate() - 1);
        handled = true;
      } else if (e.key === 'ArrowRight') {
        targetDate.setDate(targetDate.getDate() + 1);
        handled = true;
      } else if (e.key === 'ArrowUp') {
        targetDate.setDate(targetDate.getDate() - 7);
        handled = true;
      } else if (e.key === 'ArrowDown') {
        targetDate.setDate(targetDate.getDate() + 7);
        handled = true;
      } else if (e.key === 'Enter' || e.key === ' ') {
        calendarSelectedDateStr = dateStr;
        renderCalendar(gridStart, gridEnd);
        renderSelectedDayEvents();
        e.preventDefault();
        return;
      }

      if (handled) {
        e.preventDefault();
        calendarSelectedDateStr = toCalendarIsoDate(targetDate);
        if (targetDate.getMonth() !== calendarViewMonth || targetDate.getFullYear() !== calendarViewYear) {
          calendarViewMonth = targetDate.getMonth();
          calendarViewYear = targetDate.getFullYear();
          loadCalendarEvents();
        } else {
          renderCalendar(gridStart, gridEnd);
          renderSelectedDayEvents();
          const nextCell = document.querySelector(`.cal-day-cell[data-date="${calendarSelectedDateStr}"]`);
          if (nextCell) nextCell.focus();
        }
      }
    });

    gridEl.appendChild(cell);
    iter.setDate(iter.getDate() + 1);
  }
}

function renderSelectedDayEvents() {
  const headingEl = document.getElementById('calendarDayHeading');
  const listEl = document.getElementById('calendarEventsList');
  if (!headingEl || !listEl) return;

  const selectedDate = parseCalendarIsoDate(calendarSelectedDateStr);
  const formattedDate = selectedDate.toLocaleDateString(undefined, {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric'
  });
  const todayStr = toCalendarIsoDate(new Date());
  const isToday = calendarSelectedDateStr === todayStr;

  headingEl.textContent = (isToday ? 'Today · ' : '') + formattedDate;
  listEl.replaceChildren();

  const events = calendarEventsByDate.get(calendarSelectedDateStr) || [];
  if (events.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'muted';
    empty.style.padding = '8px 0';
    empty.textContent = 'No events or timed items on this day.';
    listEl.appendChild(empty);
    return;
  }

  for (const ev of events) {
    const card = document.createElement('div');
    card.className = 'cal-event-card';

    const titleEl = document.createElement(ev.source_item_id ? 'button' : 'div');
    titleEl.className = 'cal-event-title' + (ev.status === 'completed' ? ' completed' : '');
    titleEl.textContent = ev.title;
    if (ev.source_item_id) {
      titleEl.type = 'button';
      titleEl.dataset.openNote = String(ev.source_item_id);
    }
    card.appendChild(titleEl);

    const metaEl = document.createElement('div');
    metaEl.className = 'cal-event-meta';

    // Type badge
    const typeBadge = document.createElement('span');
    typeBadge.className = 'cal-pill type';
    typeBadge.textContent = ev.source_type;
    metaEl.appendChild(typeBadge);

    // Priority badge
    if (ev.priority) {
      const priorityBadge = document.createElement('span');
      priorityBadge.className = `cal-pill priority-${ev.priority.toLowerCase()}`;
      priorityBadge.textContent = ev.priority;
      metaEl.appendChild(priorityBadge);
    }

    // Time chip
    if (ev.time_of_day) {
      const timeBadge = document.createElement('span');
      timeBadge.className = 'cal-pill time';
      timeBadge.textContent = ev.time_of_day;
      metaEl.appendChild(timeBadge);
    }

    // Completed badge
    if (ev.status === 'completed') {
      const completedBadge = document.createElement('span');
      completedBadge.className = 'cal-pill completed';
      completedBadge.textContent = '✓ Completed';
      metaEl.appendChild(completedBadge);
    }

    // Needs confirmation badge
    if (ev.needs_confirmation) {
      const unconfBadge = document.createElement('span');
      unconfBadge.className = 'cal-pill unconfirmed';
      unconfBadge.textContent = `Unconfirmed${ev.timing_text ? ` ("${ev.timing_text}")` : ''}`;
      metaEl.appendChild(unconfBadge);
    }

    card.appendChild(metaEl);

    // Actions row
    const actionsEl = document.createElement('div');
    actionsEl.className = 'cal-event-actions';

    if (ev.source_item_id) {
      const jumpBtn = document.createElement('button');
      jumpBtn.type = 'button';
      jumpBtn.className = 'secondary cal-action-btn';
      jumpBtn.textContent = 'View source note';
      jumpBtn.onclick = () => jumpToSourceNote(ev.source_item_id);
      actionsEl.appendChild(jumpBtn);
    }

    if (ev.status !== 'completed') {
      const moveBtn = document.createElement('button');
      moveBtn.type = 'button';
      moveBtn.className = 'secondary cal-action-btn';
      moveBtn.textContent = 'Postpone';
      moveBtn.dataset.dateTask = String(ev.id);
      actionsEl.appendChild(moveBtn);
    }

    if (ev.needs_confirmation) {
      const confirmBtn = document.createElement('button');
      confirmBtn.type = 'button';
      confirmBtn.className = 'secondary cal-action-btn';
      confirmBtn.textContent = 'Confirm date';
      confirmBtn.onclick = async () => {
        try {
          await fetchJson(
            `/api/tasks/${ev.id}/confirm-timing`,
            {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({timing_text: ev.event_date})
            },
            'Unable to confirm timing.'
          );
          setStatus('inAppCalendarStatus', 'Event date confirmed.');
          await loadTasks();
          await loadAttention();
          await loadCalendarEvents();
        } catch {
          setStatus('inAppCalendarStatus', 'Could not confirm timing.', true);
        }
      };
      actionsEl.appendChild(confirmBtn);
    }

    if (ev.status === 'open') {
      const doneBtn = document.createElement('button');
      doneBtn.type = 'button';
      doneBtn.className = 'secondary cal-action-btn';
      doneBtn.textContent = 'Mark done';
      doneBtn.onclick = async () => {
        await transitionTask(ev.id, 'complete', actionsEl);
      };
      actionsEl.appendChild(doneBtn);
    } else if (ev.status === 'completed') {
      const reopenBtn = document.createElement('button');
      reopenBtn.type = 'button';
      reopenBtn.className = 'secondary cal-action-btn';
      reopenBtn.textContent = 'Reopen';
      reopenBtn.onclick = async () => {
        await transitionTask(ev.id, 'reopen', actionsEl);
      };
      actionsEl.appendChild(reopenBtn);
    }

    card.appendChild(actionsEl);
    listEl.appendChild(card);
  }
}

async function jumpToSourceNote(itemId) {
  let noteEl = document.querySelector(`.note[data-note-id="${itemId}"]`);
  if (!noteEl) {
    setStatus('searchStatus', `Locating source note #${itemId}…`);
    try {
      const input = document.getElementById('itemSearch');
      if (input) input.value = '';
      const typeFilter = document.getElementById('itemTypeFilter');
      if (typeFilter) typeFilter.value = '';
      await loadNotes();
      noteEl = document.querySelector(`.note[data-note-id="${itemId}"]`);
    } catch {
      // ignore
    }
  }

  if (noteEl) {
    noteEl.scrollIntoView({behavior: 'smooth', block: 'center'});
    noteEl.classList.add('note-highlight');
    setTimeout(() => noteEl.classList.remove('note-highlight'), 2600);
    setStatus('noteStatus', `Scrolled to source note #${itemId}.`);
  } else {
    setStatus('noteStatus', `Source note #${itemId} is not in the active notes view.`);
    const notesEl = document.getElementById('notes');
    if (notesEl) notesEl.scrollIntoView({behavior: 'smooth', block: 'start'});
  }
}

setupNoteLimit();
setupComposer();
syncControlsFromUrl();
loadAuthUser();
loadNotes();
loadLatestAnalysis();
loadTasks();
loadTopics();
loadDashboard();
loadAttention();
loadCalendarEvents();
loadNotificationSettings();

window.addEventListener('popstate', () => {
  syncControlsFromUrl();
  loadNotes();
  loadTasks();
});

function initRailScrollSpy() {
  const links = Array.from(document.querySelectorAll('.app-rail-link'));
  if (!links.length) return;
  const targets = links
    .map(link => {
      const id = (link.getAttribute('href') || '').replace('#', '');
      const section = id ? document.getElementById(id) : null;
      return section ? {link, section} : null;
    })
    .filter(Boolean);
  if (!targets.length) return;

  const probe = 130; // px from the top of the viewport that counts as "current"
  let ticking = false;

  const updateActive = () => {
    ticking = false;
    const atBottom = window.innerHeight + window.scrollY
      >= document.documentElement.scrollHeight - 2;
    let current = targets[0];
    if (atBottom) {
      // The last section may be too short to ever cross the probe line
      // (e.g. an empty state with little content below its heading).
      // Use getBoundingClientRect + scrollY (not offsetTop, which is
      // relative to the nearest positioned ancestor and not comparable
      // across sections) to find whichever section sits lowest on the page.
      current = targets.reduce((lowest, target) => (
        target.section.getBoundingClientRect().top > lowest.section.getBoundingClientRect().top ? target : lowest
      ), targets[0]);
    } else {
      // Pick whichever section's top is closest above the probe line, by
      // actual page position, not by the rail's icon order (which doesn't
      // match DOM order).
      let bestTop = -Infinity;
      for (const target of targets) {
        const top = target.section.getBoundingClientRect().top - probe;
        if (top <= 0 && top > bestTop) {
          bestTop = top;
          current = target;
        }
      }
    }
    for (const target of targets) {
      target.link.classList.toggle('active', target === current);
    }
  };

  window.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(updateActive);
  }, {passive: true});

  updateActive();
}

initRailScrollSpy();

function toggleAccountMenu(forceOpen) {
  const panel = document.getElementById('accountMenuPanel');
  const toggle = document.getElementById('accountMenuToggle');
  if (!panel || !toggle) return;
  const nextOpen = typeof forceOpen === 'boolean' ? forceOpen : panel.hidden;
  panel.hidden = !nextOpen;
  toggle.setAttribute('aria-expanded', String(nextOpen));
}

document.addEventListener('click', (event) => {
  const menu = document.getElementById('accountMenuToggle');
  const panel = document.getElementById('accountMenuPanel');
  if (!menu || !panel || panel.hidden) return;
  if (!menu.contains(event.target) && !panel.contains(event.target)) {
    toggleAccountMenu(false);
  }
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    toggleAccountMenu(false);
  }
});

function resetFilePickerName(input) {
  const nameEl = input.closest('.file-picker')?.querySelector('.file-picker-name');
  if (!nameEl) return;
  nameEl.textContent = 'No file chosen';
  nameEl.classList.remove('has-file');
}

function initFilePickers() {
  const inputs = document.querySelectorAll('.file-picker-input');
  for (const input of inputs) {
    const nameEl = input.closest('.file-picker')?.querySelector('.file-picker-name');
    if (!nameEl) continue;
    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      nameEl.textContent = file ? file.name : 'No file chosen';
      nameEl.classList.toggle('has-file', Boolean(file));
    });
  }
}

initFilePickers();

if (new URLSearchParams(window.location.search).get('google') === 'linked') {
  setStatus(
    'authStatus',
    'Google sign-in is now linked to this account. Your old password was removed; use "Forgot password" on the sign-in page if you want one again.'
  );
  window.history.replaceState({}, '', '/');
}

PasswordRules.attach(
  document.getElementById('newPassword'),
  document.getElementById('newPasswordRules'),
  document.getElementById('newPasswordConfirm'),
  document.getElementById('newPasswordMatch')
);
