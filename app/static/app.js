let isSavingNote = false;
let isAnalyzingInbox = false;
const pendingNoteActions = new Set();
const pendingTaskActions = new Set();
const completedNoteIdsCache = new Set();
const analysisQueue = [];
let notificationSettings = null;

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
    'Analyzing…',
    'Analyze Entire Inbox with AI'
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
    'Analyzing…',
    'Analyze Entire Inbox with AI'
  );
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
    throw new Error(friendlyError);
  }

  if (response.status === 204) {
    return null;
  }

  try {
    return await response.json();
  } catch {
    throw new Error(friendlyError);
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
    }
    setStatus('noteStatus', 'Note saved.');
    await loadNotes(
      'Your note was saved, but the list could not refresh. Reload to try again.'
    );
    await loadLatestAnalysis();
    if (createdItem && createdItem.id) {
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

async function addPdf() {
  const input = document.getElementById('pdfFile');
  const file = input.files && input.files[0];
  if (!file) {
    setStatus('noteStatus', 'Choose a PDF file before uploading.', true);
    input.focus();
    return;
  }
  setButtonBusy('addPdfButton', true, 'Uploading…', 'Upload PDF');
  setStatus('noteStatus', 'Saving PDF and extracting text…');
  const formData = new FormData();
  formData.append('file', file);
  try {
    const item = await fetchJson(
      '/api/items/pdf',
      {method: 'POST', body: formData},
      'Unable to upload PDF.'
    );
    input.value = '';
    resetFilePickerName(input);
    setStatus(
      'noteStatus',
      item.processing_status === 'ready'
        ? 'PDF saved and processed.'
        : `PDF saved but processing failed: ${item.error_message || 'unknown error'}`,
      item.processing_status !== 'ready'
    );
    await loadNotes();
    await loadLatestAnalysis();
    await loadDashboard();
    if (item && item.id) {
      autoAnalyzeInbox(item.id);
    }
  } catch {
    setStatus('noteStatus', 'We could not upload that PDF.', true);
  } finally {
    setButtonBusy('addPdfButton', false, 'Uploading…', 'Upload PDF');
  }
}

async function addImage() {
  const input = document.getElementById('imageFile');
  const file = input.files && input.files[0];
  if (!file) {
    setStatus('noteStatus', 'Choose an image before uploading.', true);
    input.focus();
    return;
  }
  setButtonBusy('addImageButton', true, 'Uploading…', 'Upload image');
  setStatus('noteStatus', 'Saving image and running OCR…');
  const formData = new FormData();
  formData.append('file', file);
  try {
    const item = await fetchJson(
      '/api/items/image',
      {method: 'POST', body: formData},
      'Unable to upload image.'
    );
    input.value = '';
    resetFilePickerName(input);
    setStatus(
      'noteStatus',
      item.processing_status === 'ready'
        ? 'Image saved and processed.'
        : `Image saved but processing failed: ${item.error_message || 'unknown error'}`,
      item.processing_status !== 'ready'
    );
    await loadNotes();
    await loadLatestAnalysis();
    await loadDashboard();
    if (item && item.id) {
      autoAnalyzeInbox(item.id);
    }
  } catch {
    setStatus('noteStatus', 'We could not upload that image.', true);
  } finally {
    setButtonBusy('addImageButton', false, 'Uploading…', 'Upload image');
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

async function addVoice() {
  const input = document.getElementById('voiceFile');
  const file = input.files && input.files[0];
  if (!file) {
    setStatus('noteStatus', 'Choose an audio file or record one first.', true);
    input.focus();
    return;
  }
  await uploadVoiceFile(file, 'Uploading voice note…');
  input.value = '';
  resetFilePickerName(input);
}

async function uploadVoiceFile(file, statusMessage, transcript = '') {
  setButtonBusy('addVoiceButton', true, 'Uploading…', 'Upload audio');
  setMicState('processing', 'Transcribing and cleaning transcript with NVIDIA NIM…');
  setStatus('noteStatus', statusMessage);
  const formData = new FormData();
  formData.append('file', file, file.name || 'voice-note.webm');
  if (transcript) {
    formData.append('transcript', transcript);
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
    setStatus('voiceStatus', '');
    await loadNotes();
    await loadLatestAnalysis();
    await loadDashboard();
    if (item && item.id) {
      autoAnalyzeInbox(item.id);
    }
  } catch {
    setStatus('noteStatus', 'We could not upload that voice note.', true);
    setMicState('error', 'Voice processing failed. Please try again.', true);
  } finally {
    setButtonBusy('addVoiceButton', false, 'Uploading…', 'Upload audio');
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
      await uploadVoiceFile(file, 'Saving recorded voice note…', capturedSpeech);
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

async function addUrl() {
  const input = document.getElementById('urlText');
  const url = input.value.trim();
  if (!url) {
    setStatus('noteStatus', 'Paste a URL before saving.', true);
    input.focus();
    return;
  }
  setButtonBusy('addUrlButton', true, 'Saving…', 'Save URL');
  setStatus('noteStatus', 'Saving URL and fetching article text…');
  try {
    const item = await fetchJson(
      '/api/items/url',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url})
      },
      'Unable to save URL.'
    );
    if (input.value.trim() === url) input.value = '';
    setStatus(
      'noteStatus',
      item.processing_status === 'ready'
        ? 'URL saved and processed.'
        : `URL saved but processing failed: ${item.error_message || 'unknown error'}`,
      item.processing_status !== 'ready'
    );
    await loadNotes();
    await loadLatestAnalysis();
    await loadDashboard();
    if (item && item.id) {
      autoAnalyzeInbox(item.id);
    }
  } catch {
    setStatus('noteStatus', 'We could not save that URL.', true);
  } finally {
    setButtonBusy('addUrlButton', false, 'Saving…', 'Save URL');
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

function renderNote(note) {
  const root = document.createElement('div');
  root.className = 'note';
  root.dataset.noteId = String(note.id);

  const text = document.createElement('div');
  text.className = 'note-text';
  if (note.item_type === 'url') {
    const title = note.title || note.source_url || 'Saved URL';
    const body = note.extracted_text || note.raw_text || '';
    text.innerHTML = `<strong>${esc(title)}</strong><div class="muted">${esc(note.source_url || '')}</div>${body ? `<div>${esc(body.slice(0, 280))}${body.length > 280 ? '…' : ''}</div>` : ''}`;
  } else if (note.item_type === 'pdf') {
    const title = note.title || note.original_filename || 'PDF document';
    const body = note.extracted_text || note.raw_text || '';
    const preview = note.storage_path
      ? `<a href="/api/items/${note.id}/file" target="_blank" rel="noopener">Open PDF</a>`
      : '';
    text.innerHTML = `<strong>${esc(title)}</strong><div class="muted">${esc(note.original_filename || '')}${preview ? ` · ${preview}` : ''}</div>${body ? `<div>${esc(body.slice(0, 280))}${body.length > 280 ? '…' : ''}</div>` : ''}`;
  } else if (note.item_type === 'image') {
    const title = note.title || note.original_filename || 'Image';
    const ocr = note.extracted_text || '';
    const ai = note.ai_description || '';
    const thumb = note.storage_path
      ? `<img class="capture-thumb" src="/api/items/${note.id}/file?variant=thumb" alt="Thumbnail for ${esc(title)}" />`
      : '';
    const open = note.storage_path
      ? `<a href="/api/items/${note.id}/file" target="_blank" rel="noopener">Open image</a>`
      : '';
    text.innerHTML = [
      `<strong>${esc(title)}</strong>`,
      `<div class="muted">${esc(note.original_filename || '')}${open ? ` · ${open}` : ''}</div>`,
      thumb,
      `<div class="provenance"><span class="label">OCR (extracted)</span>: ${ocr ? esc(ocr.slice(0, 280)) + (ocr.length > 280 ? '…' : '') : '<em class="muted">none</em>'}</div>`,
      ai ? `<div class="provenance"><span class="label">AI description (inferred)</span>: ${esc(ai.slice(0, 320))}${ai.length > 320 ? '…' : ''}</div>` : ''
    ].join('');
  } else if (note.item_type === 'voice') {
    const title = note.title || note.original_filename || 'Voice note';
    const transcript = note.extracted_text || '';
    const cleaned = note.raw_text || '';
    const player = note.storage_path
      ? `<audio controls preload="none" src="/api/items/${note.id}/file"></audio>`
      : '';
    text.innerHTML = [
      `<strong>${esc(title)}</strong>`,
      `<div class="muted">${esc(note.original_filename || '')}</div>`,
      player,
      cleaned ? `<div class="voice-cleaned-text">${esc(cleaned)}</div>` : '',
      `<div class="provenance"><span class="label">Raw transcript</span>: ${transcript ? esc(transcript.slice(0, 320)) + (transcript.length > 320 ? '…' : '') : '<em class="muted">none yet — edit to add</em>'}</div>`
    ].join('');
  } else {
    text.textContent = note.raw_text;
  }

  const time = document.createElement('div');
  time.className = 'time';
  const status = note.processing_status ? ` · ${note.processing_status}` : '';
  const error = note.error_message ? ` · ${note.error_message}` : '';
  time.textContent = `#${note.id} · ${note.item_type}${status}${error} · ${note.created_at}`;

  const actions = document.createElement('div');
  actions.className = 'note-actions';

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
  const timingLabel = task.timing_text
    ? ` · ${task.timing_text}${task.timing_confirmed ? ' (confirmed)' : ' (AI suggested)'}`
    : '';
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
      actionButton('Dismiss', 'secondary', () => {
        transitionTask(task.id, 'dismiss', actions);
      }),
      actionButton('Snooze 1 day', 'secondary', async () => {
        const until = new Date();
        until.setUTCDate(until.getUTCDate() + 1);
        const iso = until.toISOString().slice(0, 10);
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
          setStatus('taskStatus', `Snoozed until ${iso}.`);
          await loadTasks();
          await loadAttention();
        } catch {
          setStatus('taskStatus', 'Could not snooze task.', true);
        }
      })
    );
    if (task.timing_text && !task.timing_confirmed) {
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
      `/api/tasks?status=${encodeURIComponent(filter)}`,
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

async function loadTopics() {
  try {
    const topics = await fetchJson(
      '/api/topics',
      undefined,
      'Unable to load topics.'
    );
    const root = document.getElementById('topics');
    root.innerHTML = '';
    if (!topics.length) {
      root.innerHTML = '<div class="panel muted">No topics yet.</div>';
      return;
    }
    for (const topic of topics) {
      const row = document.createElement('div');
      row.className = 'topic';
      row.innerHTML = `<strong>${esc(topic.name)}</strong><div class="muted">${topic.item_count} item${topic.item_count === 1 ? '' : 's'}${topic.description ? ` · ${esc(topic.description)}` : ''}</div>`;
      root.appendChild(row);
    }
  } catch {
    setStatus('topicStatus', 'We could not load topics.', true);
  }
}

async function createTopic(event) {
  event.preventDefault();
  const input = document.getElementById('topicName');
  const name = input.value.trim();
  if (!name) return;
  try {
    await fetchJson(
      '/api/topics',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name})
      },
      'Unable to create topic.'
    );
    input.value = '';
    setStatus('topicStatus', 'Topic added.');
    await loadTopics();
    await loadDashboard();
  } catch {
    setStatus('topicStatus', 'Could not create that topic. It may already exist.', true);
  }
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
        ${section('Topics / Spaces', listOrEmpty(data.topics, t =>
          `<li><strong>${esc(t.name)}</strong> · ${t.item_count}</li>`
        ))}
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
        ${section('Related Items', listOrEmpty(data.related_items, rel =>
          `<li>#${rel.item_id_a} ↔ #${rel.item_id_b} <span class="pill">${esc(rel.relation_type)}</span></li>`
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
        body: JSON.stringify({question})
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
      `/api/calendar/events?start=${startIso}&end=${endIso}`,
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
        dot.className = 'cal-dot' +
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

    const titleEl = document.createElement('div');
    titleEl.className = 'cal-event-title' + (ev.status === 'completed' ? ' completed' : '');
    titleEl.textContent = ev.title;
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
