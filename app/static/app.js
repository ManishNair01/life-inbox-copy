let isSavingNote = false;
let isAnalyzingInbox = false;

function setStatus(elementId, message, isError = false) {
  const element = document.getElementById(elementId);
  element.textContent = message;
  element.classList.toggle('error', isError);
}

function setButtonBusy(buttonId, busy, busyLabel, idleLabel) {
  const button = document.getElementById(buttonId);
  button.disabled = busy;
  button.textContent = busy ? busyLabel : idleLabel;
  button.setAttribute('aria-busy', String(busy));
}

async function fetchJson(url, options, friendlyError) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error(friendlyError);
  }

  if (!response.ok) {
    throw new Error(friendlyError);
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
    await fetchJson(
      '/api/notes',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text})
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

function esc(str) {
  return String(str ?? '').replace(/[&<>'"]/g, tag => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'
  }[tag]));
}

function renderAnalysis(data) {
  const root = document.getElementById('aiOutput');

  const bucketHtml = (data.buckets || []).map(bucket => `
    <div class="panel">
      <h3>${esc(bucket.name)}</h3>
      <ul>
        ${(bucket.notes || []).map(n =>
          `<li>${esc(n.title)} <span class="pill">${esc(n.priority)}</span></li>`
        ).join('')}
      </ul>
    </div>
  `).join('');

  const todoHtml = (data.todos || []).map(t =>
    `<li><strong>${esc(t.task)}</strong> <span class="pill">${esc(t.priority)}</span>${t.when ? ` · ${esc(t.when)}` : ''}</li>`
  ).join('');

  const pv = data.priority_view || {High: [], Medium: [], Low: []};
  const priorityHtml = ['High', 'Medium', 'Low'].map(level => `
    <div class="panel">
      <h3>${level} priority (${(pv[level] || []).length})</h3>
      <ul>
        ${(pv[level] || []).map(n => `<li>${esc(n.title)}</li>`).join('') || '<li class="muted">None</li>'}
      </ul>
    </div>
  `).join('');

  root.innerHTML = `
    <h3>Buckets</h3>
    ${bucketHtml || '<p class="muted">No notes yet.</p>'}

    <h3>ToDos</h3>
    <ul>${todoHtml || '<li class="muted">No concrete ToDos detected.</li>'}</ul>

    <h3>Priority view</h3>
    ${priorityHtml}

    <p class="muted">Mode: ${esc(data.mode || 'unknown')}</p>
  `;
}

async function analyzeInbox() {
  if (isAnalyzingInbox) return;

  isAnalyzingInbox = true;
  setButtonBusy(
    'analyzeButton',
    true,
    'Analyzing…',
    'Analyze Entire Inbox with AI'
  );
  setStatus('analysisStatus', 'Analyzing your saved notes…');

  try {
    const data = await fetchJson(
      '/api/analyze',
      {method: 'POST'},
      'Unable to analyze inbox.'
    );
    renderAnalysis(data);
    setStatus('analysisStatus', 'Analysis complete.');
  } catch {
    setStatus(
      'analysisStatus',
      'We could not analyze your inbox. Your notes are still here—please try again.',
      true
    );
  } finally {
    isAnalyzingInbox = false;
    setButtonBusy(
      'analyzeButton',
      false,
      'Analyzing…',
      'Analyze Entire Inbox with AI'
    );
  }
}

async function loadNotes(
  failureMessage = 'We could not load your notes. Reload to try again.'
) {
  try {
    const notes = await fetchJson(
      '/api/notes',
      undefined,
      'Unable to load notes.'
    );
    const root = document.getElementById('notes');
    root.innerHTML = '';

    for (const note of notes) {
      const div = document.createElement('div');
      div.className = 'note';
      div.innerHTML = `<div>${esc(note.text)}</div><div class="time">#${note.id} · ${esc(note.created_at)}</div>`;
      root.appendChild(div);
    }
    return true;
  } catch {
    setStatus('noteStatus', failureMessage, true);
    return false;
  }
}

loadNotes();
