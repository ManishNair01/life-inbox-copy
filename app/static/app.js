async function addNote() {
  const text = document.getElementById('noteText').value.trim();
  if (!text) return alert('Write a note first');

  const response = await fetch('/api/notes', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text})
  });
  const data = await response.json();
  console.log('Created note:', data);

  document.getElementById('noteText').value = '';
  await loadNotes();
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
  const root = document.getElementById('aiOutput');
  root.innerHTML = '<span class="muted">Analyzing the complete saved inbox...</span>';

  const response = await fetch('/api/analyze', { method: 'POST' });
  const data = await response.json();

  console.log('AI inbox analysis:', data);
  renderAnalysis(data);
}

async function loadNotes() {
  const response = await fetch('/api/notes');
  const notes = await response.json();
  const root = document.getElementById('notes');
  root.innerHTML = '';

  for (const note of notes) {
    const div = document.createElement('div');
    div.className = 'note';
    div.innerHTML = `<div>${esc(note.text)}</div><div class="time">#${note.id} · ${esc(note.created_at)}</div>`;
    root.appendChild(div);
  }
}

loadNotes();
