/* Life Inbox: the three-pane app (changes 009 to 012).
 *
 * Draws the shell around the v1 screens: views, the lens, header search, the
 * life areas panel, pinned topics, Home, area pages and the shared note page.
 * Decisions live in shell_logic.js; data comes from the API. app.js keeps the
 * v1 screens working and reads the lens through window.LifeInboxLens, so this
 * file loads before app.js.
 */
(function () {
  'use strict';

  const L = window.LifeInboxShellLogic;

  const state = {
    view: 'home',
    query: '',
    bots: [],
    botsByKey: {},
    topics: [],
    topicsById: {},
    user: null,
    needsYou: {cards: [], total: 0},
    needAnswer: null,
    openNoteId: null,
    sheetMessage: '',
    dayPopup: null,
    captureReturnFocus: null,
    datePicker: null,
    lastFocus: null,
    memoryEdit: null,
    memoryForget: null,
    editingContext: null,
    revealed: new Set(),
    scout: null,
    scoutDrop: null,
    scoutBulk: null,
    scoutDate: null,
  };
  let homeToken = 0;
  let timelineToken = 0;
  let searchToken = 0;
  let noteToken = 0;

  // --- the lens: which life area every view is filtered by ------------------
  const Lens = {
    key: L.lensFromSearch(window.location.search),
    get name() {
      const bot = state.botsByKey[this.key];
      return bot ? bot.name : '';
    },
  };
  window.LifeInboxLens = Lens;

  // --- small helpers ----------------------------------------------------------
  const $ = id => document.getElementById(id);
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
  const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;
  const TYPE_LABELS = {text: 'Note', url: 'Link', pdf: 'PDF', image: 'Image', voice: 'Voice'};
  const typeLabel = type => TYPE_LABELS[type] || 'Note';

  const ICONS = {
    learn: 'M2 9l10-5 10 5-10 5zM6 11v5c3 2 9 2 12 0v-5',
    money: 'M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2zM9 8h6M9 12h6',
    health: 'M3 12h4l2-5 4 10 2-5h6',
    people: 'M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2 20c0-4 3-6 6-6s6 2 6 6M17 11a3 3 0 1 0 0-6M17 14c3 0 5 2 5 6',
    fun: 'M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.8-5.2 2.8 1-5.8-4.3-4.1 5.9-.9z',
    captain: 'M3 8l4 4 5-7 5 7 4-4-2 11H5z',
    timeline: 'M3 12h18M7 12V7M12 12V5M17 12V9',
    flag: 'M5 21V4h11l-2 4 2 4H5',
    calendar: 'M4 6h16v14H4zM4 10h16M8 3v5M16 3v5',
    topics: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
    spark: 'M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2 2M16 16l2 2M6 18l2-2M16 8l2-2',
    lock: 'M6 11h12v9H6zM8 11V8a4 4 0 0 1 8 0v3',
    scout: 'M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18zM15.5 8.5l-2 5-5 2 2-5z',
  };
  function icon(name, size = 18) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${ICONS[name] || ''}"/></svg>`;
  }

  async function api(url, options) {
    const response = await fetch(url, {credentials: 'same-origin', ...options});
    if (response.status === 401) {
      window.location.href = '/login';
      throw new Error('Signed out.');
    }
    if (!response.ok) {
      let detail = '';
      try { detail = (await response.json()).detail || ''; } catch { /* no body */ }
      const error = new Error(detail || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return response.status === 204 ? null : response.json();
  }

  function withLens(url, key = Lens.key) {
    if (!key) return url;
    return `${url}${url.includes('?') ? '&' : '?'}bot=${encodeURIComponent(key)}`;
  }

  function changed() {
    window.dispatchEvent(new CustomEvent('lifeinbox:changed'));
  }

  function itemTitle(item, insight) {
    return (insight && insight.effective_title) || L.noteTitle(item);
  }

  // Shows the view right away (so a scroll that follows lands in the new view), then
  // records the address with pushState. Assigning location.hash instead would fire
  // popstate, and app.js reloads its lists on popstate, racing the caller's own reload
  // (a "Failed captures" click lost its filter that way). Back and Forward still fire
  // hashchange, which routeFromLocation handles.
  function goTo(view, query) {
    const hash = L.hashFor(view, query);
    showView(view, query);
    if (window.location.hash !== hash) window.history.pushState(window.history.state, '', hash);
  }

  // --- views ------------------------------------------------------------------
  function showView(view, query) {
    const before = `${state.view}|${state.query}`;
    state.view = L.VIEWS.includes(view) ? view : 'home';
    state.query = query || '';
    document.body.dataset.view = state.view;
    if (state.view === 'home') closeCapture({restoreFocus: false});
    closeHover();
    // A new view starts at its top, not where the last one was scrolled to.
    if (`${state.view}|${state.query}` !== before) $('centerPane').scrollTop = 0;
    for (const section of document.querySelectorAll('.view')) {
      section.hidden = section.dataset.view !== state.view;
    }
    const navView = state.view === 'topic' ? 'topics' : state.view;
    for (const link of document.querySelectorAll('[data-view-link]')) {
      const on = link.dataset.viewLink === navView;
      link.classList.toggle('is-active', on);
      if (on) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    }
    renderCurrentView();
  }

  function renderCurrentView() {
    if (state.view === 'home') renderHome();
    if (state.view === 'topics') renderTopics();
    if (state.view === 'topic') renderTopicPage();
    if (state.view === 'timeline') renderTimeline();
    if (state.view === 'priority') renderPriority();
    if (state.view === 'dashboard') renderGlance();
    if (state.view === 'search') renderSearch();
    if (state.view === 'memory') renderMemory();
    if (state.view === 'scout') renderScout();
    if (state.view === 'welcome') renderWelcome();
    if (state.view === 'settings') renderScoutSettings();
  }

  function routeFromLocation({force = false} = {}) {
    const route = L.routeFromHash(window.location.hash);
    const view = L.VIEWS.includes(route.view) ? route.view : 'home';
    if (!force && view === state.view && (route.query || '') === state.query) return;
    showView(route.view, route.query);
  }

  // --- the lens ----------------------------------------------------------------
  function setLens(key, {toggle = true} = {}) {
    const next = key && (!toggle || key !== Lens.key) ? key : null;
    if (next === Lens.key) return;
    Lens.key = next;
    const url = new URL(window.location.href);
    if (next) url.searchParams.set('bot', next);
    else url.searchParams.delete('bot');
    window.history.pushState({}, '', url);
    applyLens();
  }

  function applyLens() {
    renderLensChip();
    renderBots();
    renderPinned();
    if (typeof loadNotes === 'function') loadNotes();
    if (typeof loadTasks === 'function') loadTasks();
    if (typeof loadCalendarEvents === 'function') loadCalendarEvents();
    renderCurrentView();
  }

  function renderLensChip() {
    const on = Boolean(Lens.key);
    $('lensChip').hidden = !on;
    $('lensNone').hidden = on;
    $('lensName').textContent = Lens.name || Lens.key || '';
    for (const note of document.querySelectorAll('[data-lens-note]')) note.hidden = !on;
  }

  // --- right pane: Captain and the five areas --------------------------------------
  async function refreshBots() {
    try {
      state.bots = await api('/api/bots');
    } catch {
      state.bots = [];
    }
    state.botsByKey = Object.fromEntries(state.bots.map(bot => [bot.key, bot]));
    renderBots();
    renderLensChip();
  }

  function renderBots() {
    const root = $('lifeBots');
    if (!root) return;
    root.innerHTML = state.bots.map(bot => `
      <button type="button" class="bot-item bot-${escapeHtml(bot.key)}${bot.key === Lens.key ? ' is-active' : ''}"
              data-bot="${escapeHtml(bot.key)}" aria-pressed="${bot.key === Lens.key}">
        <span class="bot-icon">${icon(bot.key)}</span>
        <span class="bot-text"><b>${escapeHtml(bot.name)}</b><span class="status-line">${escapeHtml(bot.status)}</span></span>
      </button>`).join('') || '<p class="muted small">Life areas are loading…</p>';
  }

  function needsCount() {
    return state.needsYou.total;
  }

  // Captain's "Needs you" list (change 013): one place for every quick
  // question, ranked by the server, at most one per note.
  async function refreshNeeds() {
    state.needsYou = await api('/api/captain/needs-you').catch(() => state.needsYou);
    renderCaptain();
  }

  function renderCaptain() {
    const count = needsCount();
    $('captainStatus').textContent = count
      ? `${plural(count, 'thing')} ${count === 1 ? 'needs' : 'need'} you`
      : 'All clear';
    const badge = $('captainBadge');
    badge.hidden = !count;
    badge.textContent = String(count);
    $('captainLink').classList.toggle('is-active', state.view === 'home' && !Lens.key);
    renderScoutLink();
  }

  // --- Scout, the catch-up helper (change 018) -------------------------------------------
  async function refreshScout() {
    state.scout = await api('/api/scout').catch(() => state.scout);
    renderScoutLink();
  }

  function renderScoutLink() {
    const link = $('scoutLink');
    if (!link) return;
    const scout = state.scout;
    const count = scout ? scout.questions.length : 0;
    $('scoutStatus').textContent = !scout ? 'Checks in on your plans'
      : !count ? 'All caught up'
        : scout.mode === 'away' ? `Back after ${scout.away_days} days?`
          : scout.mode === 'weekly' ? 'Your weekly catch-up' : `${plural(count, 'quick question')}`;
    const badge = $('scoutBadge');
    badge.hidden = !count;
    badge.textContent = String(count);
    link.classList.toggle('is-active', state.view === 'scout');
  }

  const SCOUT_HEADINGS = {past: 'Was it done?', undated: 'No date yet', someday: 'Still someday?'};

  function scoutCard(question) {
    const dropping = state.scoutDrop === question.id;
    const opener = question.item_id
      ? `<button type="button" class="row-link need-title" data-open-note="${question.item_id}">${escapeHtml(question.title)}</button>`
      : `<b class="need-title">${escapeHtml(question.title)}</b>`;
    const reasons = (state.scout && state.scout.drop_reasons) || [];
    return `<div class="need scout-q scout-${escapeHtml(question.kind)}" data-scout-card="${escapeHtml(question.id)}">
      <p class="need-heading">${escapeHtml(SCOUT_HEADINGS[question.kind] || 'A quick question')}</p>
      ${opener}
      <p class="muted">${escapeHtml(question.text)}</p>
      ${dropping
        ? `<form class="need-note" data-scout-drop-form="${escapeHtml(question.id)}">
            <p class="small">Why drop it? <span class="muted">(optional)</span></p>
            <div class="chips">${reasons.map(reason => `<button type="button" class="chip chip-muted" data-scout-reason="${escapeHtml(reason)}">${escapeHtml(reason)}</button>`).join('')}</div>
            <label class="visually-hidden" for="scoutReason">Your reason</label>
            <input id="scoutReason" name="reason" maxlength="200" placeholder="Or say why, in a few words" />
            <div class="need-actions"><button type="submit" class="small-btn">Drop it</button>
            <button type="button" class="small-btn secondary" data-scout-cancel>Keep it</button></div>
          </form>`
        : `<div class="need-actions">${question.actions.map(action => `<button type="button"
              class="small-btn${action.primary ? '' : ' secondary'}" data-scout-id="${escapeHtml(question.id)}"
              data-scout-action="${escapeHtml(action.action)}">${escapeHtml(action.label)}</button>`).join('')}
            <button type="button" class="small-btn link-btn" data-scout-id="${escapeHtml(question.id)}" data-scout-action="skip">Skip</button></div>`}
    </div>`;
  }

  let scoutToken = 0;
  async function renderScout() {
    const root = $('scoutView');
    if (!root) return;
    const token = ++scoutToken;
    const scout = await api('/api/scout').catch(() => null);
    if (token !== scoutToken) return;
    if (!scout) {
      root.innerHTML = '<p class="status error">Could not load Scout. Try again in a moment.</p>';
      return;
    }
    state.scout = scout;
    renderScoutLink();
    const next = new Date(scout.next_catchup);
    const nextText = Number.isNaN(next.getTime()) ? '' : `${L.formatDay(L.isoDate(next))} at ${String(next.getHours()).padStart(2, '0')}:${String(next.getMinutes()).padStart(2, '0')}`;
    const bulk = scout.bulk;
    const bulkRows = [
      ['old_to_someday', bulk.old_to_someday.length, `Move ${plural(bulk.old_to_someday.length, 'task')} older than 30 days to Someday`],
      ['past_to_next_week', bulk.past_to_next_week.length, `Snooze ${plural(bulk.past_to_next_week.length, 'past task')} to next week`],
    ].filter(row => row[1]);
    root.innerHTML = `
      <article class="card card-wide scout-intro" aria-labelledby="scoutIntroHeading">
        <div class="card-head"><span class="crew-icon">${icon('scout')}</span><h2 id="scoutIntroHeading">${escapeHtml(scout.intro)}</h2></div>
        <p class="muted small">Scout asks the day after a task's date, and in a weekly catch-up${nextText ? ` (next: ${escapeHtml(nextText)}; change it in <a href="#/settings">Settings</a>)` : ''}. No AI is used. Your answers update what Life Inbox remembers.</p>
      </article>
      ${scout.questions.length ? `<div class="needs scout-questions">${scout.questions.map(scoutCard).join('')}</div>` : ''}
      ${scout.total > scout.questions.length ? `<p class="muted small">${plural(scout.total - scout.questions.length, 'more question')} next time. A few at a time is plenty.</p>` : ''}
      ${bulkRows.length ? `<article class="card card-wide" aria-labelledby="scoutBulkHeading">
        <div class="card-head">${icon('flag')}<h2 id="scoutBulkHeading">Tidy up in one go</h2></div>
        ${bulkRows.map(([which, count, label]) => state.scoutBulk === which
          ? `<p class="scout-bulk" role="group" aria-label="${escapeHtml(label)}?"><span>${escapeHtml(label)}?</span>
              <button type="button" class="small-btn" data-scout-bulk-yes="${which}">Yes, move ${count}</button>
              <button type="button" class="small-btn secondary" data-scout-bulk-cancel>Cancel</button></p>`
          : `<p class="scout-bulk"><button type="button" class="small-btn secondary" data-scout-bulk="${which}">${escapeHtml(label)}</button></p>`).join('')}
        <p class="muted small">Someday tasks keep no date: they leave your calendar, Timeline and reminders, and wait in Priority › Someday.</p>
      </article>` : ''}
      ${scout.catchup_due ? `<p><button type="button" class="secondary" data-scout-finish>Done for now</button></p>` : ''}`;
  }

  async function scoutAnswer(questionId, action, extra = {}) {
    try {
      const result = await api(`/api/scout/${encodeURIComponent(questionId)}/answer`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action, ...extra}),
      });
      state.scout = result.scout;
      state.scoutDrop = null;
      showToast(result.said);
      changed();
    } catch (error) {
      showToast(error.message || 'Could not answer that. Try again.');
    }
    if (state.view === 'scout') await renderScout();
    else renderScoutLink();
  }

  async function scoutClick(button) {
    const data = button.dataset;
    if (data.scoutAction) {
      const question = ((state.scout && state.scout.questions) || []).find(q => q.id === data.scoutId);
      if (!question) return;
      if (data.scoutAction === 'drop') {
        state.scoutDrop = question.id;
        await renderScout();
        if ($('scoutReason')) $('scoutReason').focus();
      } else if (data.scoutAction === 'reschedule') {
        // Opening the picker first closes any other (which forgets a Scout
        // date), so the marker is set once it's open.
        const opened = await openDatePicker(question.task_id, button);
        if (opened !== false) state.scoutDate = {questionId: question.id, taskId: question.task_id};
      } else {
        scoutAnswer(question.id, data.scoutAction);
      }
    } else if (data.scoutReason) {
      const form = button.closest('[data-scout-drop-form]');
      if (form) scoutAnswer(form.dataset.scoutDropForm, 'drop', {reason: data.scoutReason});
    } else if (data.scoutCancel !== undefined) {
      state.scoutDrop = null;
      renderScout();
    } else if (data.scoutBulk) {
      state.scoutBulk = data.scoutBulk;
      await renderScout();
      const yes = document.querySelector('[data-scout-bulk-yes]');
      if (yes) yes.focus();
    } else if (data.scoutBulkCancel !== undefined) {
      state.scoutBulk = null;
      renderScout();
    } else if (data.scoutBulkYes) {
      try {
        const result = await api('/api/scout/bulk', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({which: data.scoutBulkYes})});
        showToast(result.said);
        changed();
      } catch (error) {
        showToast(error.message || 'Could not move them.');
      }
      state.scoutBulk = null;
      renderScout();
    } else if (data.scoutFinish !== undefined) {
      try {
        state.scout = await api('/api/scout/finish', {method: 'POST'});
        showToast('Thanks. Scout will check in again next week.');
      } catch (error) {
        showToast(error.message || 'Could not finish the catch-up.');
      }
      renderScout();
    } else if (data.somedayOn || data.somedayOff) {
      const id = data.somedayOn || data.somedayOff;
      try {
        await api(`/api/tasks/${id}/someday`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({someday: Boolean(data.somedayOn)})});
        showToast(data.somedayOn ? 'Moved to Someday. Its date is gone, so it stays off your calendar.' : 'Back on your list. Give it a date when you\'re ready.');
        reloadV1Lists();
        changed();
      } catch (error) {
        showToast(error.message || 'Could not move it.');
      }
    }
  }

  async function renderScoutSettings() {
    const form = $('scoutSettingsForm');
    if (!form || form.dataset.loaded) return;
    const settings = await api('/api/settings').catch(() => null);
    if (!settings) return;
    $('catchupDay').value = settings.catchup_day;
    $('catchupTime').value = settings.catchup_time;
    if ($('aiProcessing')) $('aiProcessing').checked = settings.ai_processing;
    form.dataset.loaded = '1';
  }

  // --- The AI switch and account deletion (change 025) ------------------------------------
  async function setAiProcessing(input) {
    const on = input.checked;
    try {
      await api('/api/settings', {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ai_processing: on})});
      $('aiSettingsStatus').textContent = on ? 'AI is on for your notes.' : 'AI is off: nothing is sent to an AI provider.';
    } catch (error) {
      input.checked = !on;
      $('aiSettingsStatus').textContent = error.message || 'Could not change it.';
    }
  }

  async function deleteAccount(event) {
    event.preventDefault();
    const status = $('deleteAccountStatus');
    if ($('deleteConfirm').value.trim() !== 'DELETE') {
      status.textContent = 'Type DELETE (in capitals) to confirm.';
      $('deleteConfirm').focus();
      return;
    }
    try {
      await api('/api/auth/account/delete', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({password: $('deletePassword').value, confirm: 'DELETE'})});
      window.location.replace('/login?deleted=1');
    } catch (error) {
      status.textContent = error.message || 'Could not delete the account.';
      $('deletePassword').value = '';
      $('deletePassword').focus();
    }
  }

  // --- "Create New Life": the setup questions (change 024) -----------------------------------
  let welcomeToken = 0;
  async function renderWelcome() {
    const root = $('welcomeView');
    if (!root) return;
    const token = ++welcomeToken;
    const info = await api('/api/onboarding').catch(() => null);
    if (token !== welcomeToken || !info) return;
    const roles = [['student', 'I study'], ['working', 'I work'], ['both', 'Both'], ['home', 'I run a home'], ['other', 'Something else']];
    root.innerHTML = `
      <article class="card card-wide" aria-labelledby="welcomeIntro">
        <div class="card-head">${icon('captain')}<h2 id="welcomeIntro">A few questions, all optional</h2></div>
        <p>Your answers help Life Inbox file your notes from day one. They're kept as facts about you that you can see, change or delete under <a href="#/memory">What I learned about you</a>. Skip any, or all.</p>
      </article>
      <form id="welcomeForm" class="card card-wide welcome-form">
        <fieldset><legend>What do you do?</legend>
          <div class="chips">${roles.map(([key, label]) => `<label class="chip chip-muted"><input type="radio" name="role" value="${key}" /> ${escapeHtml(label)}</label>`).join('')}</div>
          <label class="small">If something else, in a few words <input name="role_other" maxlength="80" /></label>
        </fieldset>
        <label>Where are you based? <span class="muted small">(a city is plenty)</span> <input name="city" maxlength="60" /></label>
        <fieldset><legend>What fills your days? <span class="muted small">(pick any)</span></legend>
          <div class="chips">${Object.entries(info.focus).map(([key, label]) => `<label class="chip chip-muted"><input type="checkbox" name="focus" value="${key}" /> ${escapeHtml(label)}</label>`).join('')}</div>
        </fieldset>
        <label>Anyone you look after? <span class="muted small">(for example "my parents", "my younger brother")</span> <input name="care" maxlength="80" /></label>
        <label class="toggle memory-consent"><input type="checkbox" name="health_memory_consent"${info.health_memory_consent ? ' checked' : ''} /> Remember health facts</label>
        <p class="muted small">About you and the people you care for, such as family members: medicines, doctors, appointments. Off unless you switch it on; switching it off later deletes them.</p>
        <div class="need-actions"><button type="submit">Save and start</button>
          <button type="button" class="secondary" data-welcome-skip>Skip for now</button></div>
      </form>`;
  }

  async function saveWelcome(form) {
    const data = new FormData(form);
    const body = {
      role: data.get('role') || undefined, role_other: data.get('role_other') || undefined,
      city: data.get('city') || undefined, focus: data.getAll('focus'), care: data.get('care') || undefined,
      health_memory_consent: data.get('health_memory_consent') === 'on',
    };
    try {
      const result = await api('/api/onboarding', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      showToast(result.facts.length ? `Saved ${plural(result.facts.length, 'fact')} about you. Welcome to your new Life.` : 'All set. Welcome to your new Life.');
      goTo('home');
    } catch (error) {
      showToast(error.message || 'Could not save your answers.');
    }
  }

  async function maybeWelcome() {
    const info = await api('/api/onboarding').catch(() => null);
    if (info && info.show && state.view === 'home') goTo('welcome');
  }

  async function saveScoutSettings(event) {
    event.preventDefault();
    try {
      await api('/api/settings', {method: 'PATCH', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({catchup_day: $('catchupDay').value, catchup_time: $('catchupTime').value})});
      $('scoutSettingsStatus').textContent = 'Saved. Scout checks in then each week.';
      refreshScout();
    } catch (error) {
      $('scoutSettingsStatus').textContent = error.message || 'Could not save it.';
    }
  }

  // --- left pane: pinned topics and the account --------------------------------------
  async function refreshTopics() {
    try {
      state.topics = await api('/api/topics');
    } catch {
      state.topics = [];
    }
    state.topicsById = Object.fromEntries(state.topics.map(topic => [topic.id, topic]));
    renderPinned();
  }

  function renderPinned() {
    const root = $('pinnedTopics');
    if (!root) return;
    const scope = Lens.key ? state.topics.filter(topic => topic.bot_key === Lens.key) : state.topics;
    const pins = L.pinnedTopics(scope);
    root.innerHTML = pins.length
      ? pins.map(topic => `
        <button type="button" class="pinned-topic" data-open-topic="${topic.id}">
          <span class="dot dot-${escapeHtml(topic.bot_key || 'none')}" aria-hidden="true"></span>
          <span class="pinned-name">${escapeHtml(topic.name)}</span>
          <span class="count">${topic.item_count}</span>
        </button>`).join('')
      : '<p class="muted small">Your busiest topics will show here.</p>';
  }

  async function refreshAccount() {
    try {
      state.user = await api('/api/auth/me');
    } catch {
      state.user = null;
    }
    const user = (state.user && state.user.user) || state.user || {};
    const name = user.display_name || user.email || 'You';
    $('accountName').textContent = name;
    $('accountInitial').textContent = (name.trim()[0] || '·').toUpperCase();
  }

  function firstName() {
    const user = (state.user && state.user.user) || state.user || {};
    const name = (user.display_name || '').trim();
    return name ? name.split(/\s+/)[0] : '';
  }

  // --- shared pieces ---------------------------------------------------------------------
  function weekChart(tasks, options = {}) {
    return dayChart(tasks, L.weekDays(new Date()), options);
  }

  function dayChart(tasks, days, {large = false, compact = false, done = null} = {}) {
    const today = L.isoDate(new Date());
    const spikes = L.weekSpikes(tasks, days);
    const label = compact ? `${L.formatDay(days[0])} to ${L.formatDay(days[days.length - 1])}` : 'The week, Monday to Sunday';
    return `<div class="week-chart${large ? ' week-chart-large' : ''}${compact ? ' month-chart' : ''}" role="list" aria-label="${escapeHtml(label)}">${spikes.map(spike => {
      const [weekday, day] = L.formatDay(spike.day).split(' ');
      const bars = spike.tasks.map(task => `
        <button type="button" class="week-bar${task.priority === 'High' ? ' is-high' : ''}${task.confirmed ? ' is-confirmed' : ' is-suggested'}"
          ${task.sourceItemId ? `data-open-note="${task.sourceItemId}"` : 'data-go-view="priority"'}
          aria-label="${escapeHtml(task.text)}, ${escapeHtml(L.formatDay(spike.day))}${task.confirmed ? '' : ' (date not confirmed)'}"></button>`).join('');
      const weekend = compact && (weekday === 'Sat' || weekday === 'Sun');
      const doneThatDay = (done && done[spike.day]) || [];
      const ticks = doneThatDay.length
        ? `<span class="week-done" title="Done: ${escapeHtml(doneThatDay.map(task => task.text).join(', '))}">✓${doneThatDay.length > 1 ? doneThatDay.length : ''}<span class="visually-hidden"> ${plural(doneThatDay.length, 'task')} done: ${escapeHtml(doneThatDay.map(task => task.text).join(', '))}</span></span>`
        : '';
      return `<div class="week-day${spike.day === today ? ' is-today' : ''}${weekend ? ' is-weekend' : ''}" role="listitem">
        <div class="week-bars">${bars}</div>${ticks}
        <span class="week-label">${compact ? day : `${weekday}${large ? ` ${day}` : ''}`}${spike.day === today ? '<span class="visually-hidden"> (today)</span>' : ''}</span>
      </div>`;
    }).join('')}</div>`;
  }

  function taskRow(task, {showDate = true} = {}) {
    const source = (task.source_item_ids || [])[0];
    const date = dateChip(task);
    return `<div class="row row-stack">
      <button type="button" class="row-link" ${source ? `data-open-note="${source}"` : 'data-go-view="priority"'}>${escapeHtml(task.text)}</button>
      <div class="row-meta">
        <span class="pri pri-${escapeHtml((task.priority || 'Medium').toLowerCase())}">${escapeHtml(task.priority || 'Medium')}</span>
        ${showDate ? date : ''}
      </div>
    </div>`;
  }

  function topicChip(topicId, insight = null) {
    const topic = state.topicsById[topicId];
    // Filing wasn't sure (change 014): it waits for your pick in Needs you.
    if (!topic && insight && insight.filing_pending) return '<span class="chip chip-dashed" title="Life Inbox wasn\'t sure; Captain asks you which topic">Waiting for you</span>';
    if (!topic) return '<span class="chip chip-muted">Not filed yet</span>';
    return `<button type="button" class="chip chip-topic dot-${escapeHtml(topic.bot_key || 'none')}-chip" data-open-topic="${topic.id}">${escapeHtml(topic.name)}</button>`;
  }

  // --- Captain's "Needs you" cards (change 013) -------------------------------------------
  const NEEDS_SHOWN = 5;

  function needCard(card) {
    const writing = state.needAnswer && state.needAnswer.id === card.id && state.needAnswer.kind !== 'rename';
    const renaming = state.needAnswer && state.needAnswer.id === card.id && state.needAnswer.kind === 'rename';
    const buttons = card.actions.map(action => `<button type="button"
        class="small-btn${action.primary ? '' : ' secondary'}${action.action === 'not_now' || action.action === 'ignore' ? ' link-btn' : ''}"
        data-need-id="${escapeHtml(card.id)}" data-need-action="${escapeHtml(action.action)}"
        ${action.value === null || action.value === undefined ? '' : `data-need-value="${escapeHtml(String(action.value))}"`}>${escapeHtml(action.label)}</button>`).join('');
    const opener = card.item_id && card.kind !== 'clash'
      ? `<button type="button" class="row-link need-title" data-open-note="${card.item_id}">${escapeHtml(card.title)}</button>`
      : `<b class="need-title">${escapeHtml(card.title)}</b>`;
    return `<div class="need need-${escapeHtml(card.kind)}" data-need-card="${escapeHtml(card.id)}">
      <p class="need-heading">${escapeHtml(card.heading)}</p>
      ${opener}
      <p class="muted">${escapeHtml(card.text)}</p>
      ${writing ? `<form class="need-note" data-need-note="${escapeHtml(card.id)}">
          <label class="muted small" for="needNote">What was it? Your words are used to file it.</label>
          <textarea id="needNote" rows="2" maxlength="2000" required></textarea>
          <div class="need-actions"><button type="submit" class="small-btn">Save note</button>
          <button type="button" class="small-btn secondary" data-need-cancel>Cancel</button></div>
        </form>`
        : renaming ? `<form class="need-note" data-need-rename="${escapeHtml(card.id)}">
          <label class="muted small" for="needName">The topic's name</label>
          <input id="needName" maxlength="60" required value="${escapeHtml(card.title)}" />
          <div class="need-actions"><button type="submit" class="small-btn">Create it</button>
          <button type="button" class="small-btn secondary" data-need-cancel>Cancel</button></div>
        </form>`
        : `<div class="need-actions">${buttons}</div>`}
    </div>`;
  }

  function needById(id) {
    return state.needsYou.cards.find(card => card.id === id) || null;
  }

  async function resolveNeed(card, action, value) {
    const body = value === undefined || value === null ? {action} : {action, value};
    state.needsYou = await api(`/api/captain/needs-you/${encodeURIComponent(card.id)}/resolve`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    state.needAnswer = null;
    renderCaptain();
  }

  async function answerNeed(button) {
    const card = needById(button.dataset.needId);
    if (!card) return;
    const {needAction: action} = button.dataset;
    const raw = button.dataset.needValue;
    const value = raw === undefined ? undefined : (/^\d+$/.test(raw) ? Number(raw) : raw);
    try {
      if (action === 'check' && (card.kind === 'date' || card.kind === 'moved')) {
        queueDateQuestion(card.kind === 'moved'
          ? {kind: 'moved', taskId: card.task_id, to: card.data.to, from: card.data.from, fromTime: card.data.from_time}
          : {kind: 'new', taskId: card.task_id});
      } else if (action === 'check' && card.kind === 'clash') {
        goTo('timeline');
        setTimeline({mode: 'week', anchor: card.data.day});
      } else if (action === 'set_date') {
        openDatePicker(card.task_id, button);
      } else if (action === 'retry') {
        button.disabled = true;
        button.textContent = 'Reading…';
        const item = await api(`/api/items/${card.item_id}/retry`, {method: 'POST'});
        if (item.processing_status === 'ready') {
          showToast('Read it this time. Filing it now.');
          if (typeof autoAnalyzeInbox === 'function') autoAnalyzeInbox(card.item_id);
        } else {
          showToast('Still couldn\'t read it. You can add a note about it instead.');
        }
        changed();
      } else if (action === 'add_note') {
        state.needAnswer = {id: card.id};
        renderHome().then(() => { if ($('needNote')) $('needNote').focus(); });
      } else if (action === 'delete' && !button.dataset.armed) {
        // Deleting can't be undone: ask once more on the same button.
        button.dataset.armed = '1';
        button.textContent = 'Yes, delete';
        button.classList.remove('secondary');
        button.classList.add('danger');
      } else if (action === 'file') {
        if (typeof autoAnalyzeInbox === 'function') autoAnalyzeInbox(card.item_id);
        showToast('Filing it now.');
      } else if (action === 'open' || action === 'other') {
        openNote(card.item_id);
      } else if (action === 'rename') {
        state.needAnswer = {id: card.id, kind: 'rename'};
        renderHome().then(() => { if ($('needName')) { $('needName').focus(); $('needName').select(); } });
      } else if (action === 'edit' && card.kind === 'fact') {
        state.memoryEdit = card.data.fact_id;
        goTo('memory');
      } else {
        await resolveNeed(card, action, value);
        const said = {
          not_now: 'OK, not now. It won\'t ask again.',
          ignore: 'OK, ignored.',
          drop: 'Dropped. It\'s gone from your lists.',
          delete: 'Deleted.',
          done: 'Done reviewing.',
          pick: `Filed under ${button.textContent.trim()}.`,
          create: `Created “${card.title}”. Its notes moved in.`,
          never: 'OK. It won\'t suggest that topic again.',
          yes: 'Confirmed. Life Inbox will remember it.',
          no: 'Forgotten. It won\'t be suggested again.',
          move: 'Moved. Its new day is set as yours.',
          different: 'OK, kept apart: the note got its own task.',
        }[action];
        if (card.kind === 'topic_area' && action === 'pick') showToast(`“${card.title}” is now in ${button.textContent.trim()}.`);
        else if (said) showToast(said);
        if (action !== 'not_now' && action !== 'ignore') changed();
        else renderHome();
      }
    } catch (error) {
      showToast(error.message || 'Could not answer that. Try again.');
      button.disabled = false;
    }
  }

  async function saveNeedRename(form) {
    const card = needById(form.dataset.needRename);
    const name = $('needName').value.trim();
    if (!card || !name) return;
    try {
      await resolveNeed(card, 'create', name);
      state.needAnswer = null;
      showToast(`Created “${name}”. Its notes moved in.`);
      changed();
    } catch (error) {
      showToast(error.message || 'Could not create the topic.');
    }
  }

  async function saveNeedNote(form) {
    const card = needById(form.dataset.needNote);
    const note = $('needNote').value.trim();
    if (!card || !note) return;
    try {
      await resolveNeed(card, 'add_note', note);
      showToast('Saved your note. Filing it from your words.');
      if (typeof autoAnalyzeInbox === 'function') autoAnalyzeInbox(card.item_id);
      changed();
    } catch (error) {
      showToast(error.message || 'Could not save the note.');
    }
  }

  // --- Home -----------------------------------------------------------------------------
  async function renderHome() {
    renderCaptain();
    const root = $('homeView');
    const token = ++homeToken;
    if (Lens.key) {
      await renderBotPage(root, token);
      return;
    }
    const todayIso = L.isoDate(new Date());
    const [tasks, recent, briefing, greeting] = await Promise.all([
      api('/api/tasks?status=open').catch(() => []),
      api('/api/items?order=desc&limit=4').catch(() => []),
      api('/api/briefing').catch(() => null),
      api('/api/captain/greeting').catch(() => null),
    ]);
    const insights = await Promise.all(
      recent.map(item => api(`/api/items/${item.id}/insight`).catch(() => null))
    );
    if (token !== homeToken) return;

    const count = needsCount();
    const name = firstName();
    const shownNeeds = state.needsYou.cards.slice(0, NEEDS_SHOWN);
    const needCards = shownNeeds.map(needCard);
    const moreNeeds = state.needsYou.total - shownNeeds.length;

    const focus = L.todaysFocus(tasks, todayIso);
    const next = L.nextUp(tasks, todayIso);

    root.innerHTML = `
      <article class="card card-wide card-captain" aria-labelledby="captainCardHeading">
        <div class="card-head">
          <span class="crew-icon">${icon('captain')}</span>
          <h2 id="captainCardHeading">${escapeHtml(L.greeting(new Date()))}${name ? `, ${escapeHtml(name)}` : ''}</h2>
          ${count ? `<span class="badge">${count} need you</span>` : ''}
          <a class="card-link" href="#/memory">What I learned ›</a>
        </div>
        ${greeting && greeting.ai ? `<p class="captain-greeting">${escapeHtml(greeting.text)}</p>` : ''}
        <p class="captain-summary">${escapeHtml(L.captainSummary(briefing && briefing.counts, count))}</p>
        ${needCards.length ? `<div class="needs">${needCards.join('')}</div>` : ''}
        ${moreNeeds > 0 ? `<p class="muted small">${plural(moreNeeds, 'more question')} after these. Answer one and the next shows.</p>` : ''}
      </article>
      <div class="home-row">
      <article class="card" aria-labelledby="weekCardHeading">
        <div class="card-head">${icon('timeline')}<h2 id="weekCardHeading">This week</h2><a class="card-link" href="#/timeline">Open timeline ›</a></div>
        ${weekChart(tasks)}
        <h3 class="mini-heading">Next up</h3>
        ${next.length ? next.map(task => taskRow(task)).join('') : '<p class="muted">Nothing dated yet.</p>'}
      </article>
      <article class="card" aria-labelledby="focusCardHeading">
        <div class="card-head">${icon('flag')}<h2 id="focusCardHeading">Today's focus</h2><a class="card-link" href="#/priority">All priorities ›</a></div>
        ${focus.items.length ? focus.items.map(task => taskRow(task)).join('') : '<p class="muted">Nothing urgent today.</p>'}
        <p class="muted small card-foot">${focus.waiting ? `${plural(focus.waiting, 'more task')} waiting. Captain keeps this list to 3.` : 'Captain keeps this list to 3.'}</p>
      </article>
      <article class="card" aria-labelledby="recentCardHeading">
        <div class="card-head">${icon('topics')}<h2 id="recentCardHeading">Recently captured</h2><a class="card-link" href="#/topics">All notes ›</a></div>
        ${recent.length ? recent.map((item, index) => `<div class="row row-stack">
          <button type="button" class="row-link" data-open-note="${item.id}">${escapeHtml(itemTitle(item, insights[index]))}</button>
          <div class="row-meta">
            <span class="chip">${escapeHtml(typeLabel(item.item_type))}</span>
            ${topicChip(insights[index] && insights[index].effective_topic_id, insights[index])}
          </div>
        </div>`).join('') : '<p class="muted">Nothing captured yet. Write your first note above.</p>'}
      </article>
      </div>`;
  }

  async function renderBotPage(root, token) {
    const bot = state.botsByKey[Lens.key];
    if (!bot) {
      root.innerHTML = '<p class="muted">Loading this area…</p>';
      return;
    }
    const [tasks, memory, summary] = await Promise.all([
      api(withLens('/api/tasks?status=open')).catch(() => []),
      api(`/api/memory?bot=${encodeURIComponent(bot.key)}`).catch(() => null),
      api(`/api/bots/${encodeURIComponent(bot.key)}/summary`).catch(() => null),
    ]);
    if (token !== homeToken) return;
    const group = L.topicGroups(state.bots, state.topics, bot.key)[0];
    const topicRows = group ? topicEntryRows(group.entries) : '';
    const todo = tasks.slice(0, 6);

    root.innerHTML = `
      <article class="card card-wide bot-page bot-${escapeHtml(bot.key)}" aria-labelledby="botPageHeading">
        <div class="card-head">
          <span class="bot-icon bot-icon-large">${icon(bot.key, 22)}</span>
          <div><h2 id="botPageHeading">${escapeHtml(bot.name)}</h2><p class="muted">${escapeHtml(bot.description)}</p></div>
        </div>
        <p class="bot-summary">${escapeHtml(summary && summary.ai ? summary.summary : L.botSummary(bot))}</p>
      </article>
      <div class="home-row">
      <article class="card" aria-labelledby="botTopicsHeading">
        <div class="card-head">${icon('topics')}<h2 id="botTopicsHeading">Its topics</h2></div>
        ${topicRows || '<p class="muted">No topics in this area.</p>'}
      </article>
      <article class="card" aria-labelledby="botTodoHeading">
        <div class="card-head">${icon('flag')}<h2 id="botTodoHeading">What to do</h2><a class="card-link" href="#/priority">All ›</a></div>
        ${todo.length ? todo.map(task => taskRow(task)).join('') : '<p class="muted">Nothing to do here right now.</p>'}
        ${tasks.length > todo.length ? `<p class="muted small">${plural(tasks.length - todo.length, 'more task')} in Priority.</p>` : ''}
      </article>
      <article class="card" aria-labelledby="botWeekHeading">
        <div class="card-head">${icon('timeline')}<h2 id="botWeekHeading">Its week</h2></div>
        ${weekChart(tasks)}
      </article>
      <article class="card" aria-labelledby="botMemoryHeading">
        <div class="card-head">${icon('spark')}<h2 id="botMemoryHeading">What I learned about you</h2><a class="card-link" href="#/memory">All ›</a></div>
        ${bot.key === 'health' && memory ? healthToggle(memory.health_memory_consent) : ''}
        ${memory ? memoryList(memory.facts.slice(0, 5), {empty: bot.key === 'health' && !memory.health_memory_consent
          ? 'Health memory is off, so nothing about health is remembered.'
          : `Nothing learned in ${bot.name} yet. It starts when you move a note, set a priority or a date, or your own words say something lasting about you.`})
          : '<p class="muted">Could not load what Life Inbox learned.</p>'}
        ${memory && memory.facts.length > 5 ? `<p class="muted small">${plural(memory.facts.length - 5, 'more fact')} on the full list.</p>` : ''}
      </article>
      </div>`;
  }

  // --- What I learned about you (change 016) -------------------------------------------
  const SOURCE_KIND = {
    your_words: 'From your words', correction: 'From a change you made', needs_you: 'From your answer to Captain',
    scout: 'From Scout', onboarding: 'From your setup answers', weekly_review: 'From your weekly review', you: 'Added by you',
  };

  function memoryRow(fact) {
    if (state.memoryEdit === fact.id) {
      return `<li class="memory-row is-editing"><form class="memory-form" data-memory-form="${fact.id}">
        <label class="visually-hidden" for="memoryText${fact.id}">Edit this fact</label>
        <input id="memoryText${fact.id}" name="text" maxlength="200" required value="${escapeHtml(fact.text)}" />
        <span class="memory-actions"><button type="submit">Save</button>
        <button type="button" class="secondary" data-memory-cancel>Cancel</button></span></form></li>`;
    }
    const status = L.memoryStatus(fact);
    const source = (fact.source_item_ids || [])[0];
    const forgetting = state.memoryForget === fact.id;
    return `<li class="memory-row${fact.status === 'suggested' ? ' is-suggested' : ''}">
      <p class="memory-text">${escapeHtml(fact.text)}</p>
      <div class="row-meta">
        ${status ? `<span class="chip ${fact.status === 'suggested' ? 'chip-dashed' : 'chip-muted'}">${escapeHtml(status)}</span>` : ''}
        ${fact.core_profile ? '<span class="chip">About you</span>' : ''}
        <span class="muted small">${escapeHtml(SOURCE_KIND[fact.source_kind] || '')}${fact.times_seen > 1 ? ` · seen ${fact.times_seen} times` : ''}</span>
        ${source ? `<button type="button" class="link-btn small" data-open-note="${source}">Open the note</button>` : ''}
        ${forgetting
          ? `<span class="memory-actions" role="group" aria-label="Forget this fact?"><span class="small">Forget it for good?</span>
              <button type="button" class="link-btn small danger-link" data-memory-forget="${fact.id}">Forget</button>
              <button type="button" class="link-btn small" data-memory-cancel>Keep</button></span>`
          : `<span class="memory-actions">
              ${fact.status === 'suggested' ? `<button type="button" class="link-btn small" data-memory-confirm="${fact.id}">Confirm</button>` : ''}
              <button type="button" class="link-btn small" data-memory-edit="${fact.id}">Edit</button>
              <button type="button" class="link-btn small" data-memory-delete="${fact.id}">Delete</button></span>`}
      </div></li>`;
  }

  function memoryList(facts, {empty = 'Nothing learned yet.'} = {}) {
    return facts.length
      ? `<ul class="memory-list">${facts.map(memoryRow).join('')}</ul>`
      : `<p class="muted">${escapeHtml(empty)}</p>`;
  }

  function healthToggle(on) {
    return `<label class="toggle memory-consent"><input type="checkbox" data-health-consent${on ? ' checked' : ''} />
      Remember health facts</label>
      <p class="muted small">Off until you switch it on. Covers everything in Health (medicines, fitness, mood) and medical notes about people you care for. Switching it off deletes what it remembered.</p>`;
  }

  let memoryToken = 0;
  async function renderMemory() {
    const root = $('memoryView');
    if (!root) return;
    const token = ++memoryToken;
    const memory = await api('/api/memory').catch(() => null);
    if (token !== memoryToken) return;
    if (!memory) {
      root.innerHTML = '<p class="status error">Could not load what Life Inbox learned. Try again in a moment.</p>';
      return;
    }
    const groups = L.memoryGroups(memory.facts, state.bots);
    root.innerHTML = `
      <article class="card card-wide" aria-labelledby="memoryAboutHeading">
        <div class="card-head">${icon('spark')}<h2 id="memoryAboutHeading">How Life Inbox learns</h2></div>
        <p>From what you do (a note you move, a priority or date you set, an answer to Captain) and from what your own words say. Never from the text of a link, PDF or image, and never from a note that holds a secret. Each fact is used only to file your notes better: when memory in filing is on, the confirmed facts that relate to a new note go with it to the AI.</p>
        <p class="muted small">Confirm what's right. Edit or delete the rest: a deleted fact is erased and not suggested again. <a href="/privacy" target="_blank" rel="noopener">Privacy</a></p>
        ${healthToggle(memory.health_memory_consent)}
      </article>
      <article class="card card-wide" aria-labelledby="memoryComingHeading">
        <div class="card-head">${icon('calendar')}<h2 id="memoryComingHeading">Coming up</h2></div>
        ${memory.coming_up.length ? `<ul class="memory-list">${memory.coming_up.map(plan => `<li class="memory-row">
          <p class="memory-text">${escapeHtml(plan.text)}</p>
          <div class="row-meta"><span class="chip">${escapeHtml(L.formatDay(plan.due_on))}${plan.due_time ? ` · ${escapeHtml(plan.due_time)}` : ''}</span>
          ${plan.confirmed ? '' : '<span class="chip chip-dashed">Date not confirmed</span>'}</div></li>`).join('')}</ul>
          <p class="muted small">From your dated tasks. Change a date in Timeline or Priority.</p>`
          : '<p class="muted">Nothing dated in the next two weeks.</p>'}
      </article>
      ${groups.length ? groups.map(group => `<article class="card card-wide" aria-labelledby="memoryGroup${group.key || 'captain'}">
        <div class="card-head">${icon(group.key || 'captain')}<h2 id="memoryGroup${group.key || 'captain'}">${escapeHtml(group.name)}</h2></div>
        ${memoryList(group.facts)}
      </article>`).join('')
        : `<article class="card card-wide"><p class="muted">Nothing learned yet. It starts when you move a note, set a priority or a date, answer Captain, or your own words say something lasting about you.</p></article>`}`;
  }

  async function memoryAction(button) {
    const data = button.dataset;
    try {
      if (data.memoryConfirm) {
        await api(`/api/memory/${data.memoryConfirm}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({status: 'confirmed'})});
        showToast('Confirmed.');
      } else if (data.memoryEdit) {
        Object.assign(state, {memoryEdit: Number(data.memoryEdit), memoryForget: null});
      } else if (data.memoryDelete) {
        Object.assign(state, {memoryForget: Number(data.memoryDelete), memoryEdit: null});
      } else if (data.memoryForget) {
        await api(`/api/memory/${data.memoryForget}`, {method: 'DELETE'});
        state.memoryForget = null;
        showToast('Forgotten. It won\'t be suggested again.');
      } else if (data.memoryCancel !== undefined) {
        Object.assign(state, {memoryEdit: null, memoryForget: null});
      }
    } catch (error) {
      showToast(error.message || 'Could not change that.');
    }
    await redrawMemory();
    // Keyboard focus follows: into the edit box, or onto "Keep" (the safe choice).
    const next = state.memoryEdit ? $(`memoryText${state.memoryEdit}`)
      : state.memoryForget ? document.querySelector('[data-memory-forget] + [data-memory-cancel]') : null;
    if (next) next.focus();
  }

  // The memory page, or the area page's memory card, drawn again (awaitable).
  function redrawMemory() {
    if (state.view === 'memory') return renderMemory();
    if (state.view === 'home') return renderHome();
    renderCurrentView();
    return Promise.resolve();
  }

  async function saveMemoryEdit(form) {
    const text = form.elements.text.value.trim();
    if (!text) return;
    try {
      await api(`/api/memory/${form.dataset.memoryForm}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text})});
      state.memoryEdit = null;
      showToast('Saved.');
      await redrawMemory();
    } catch (error) {
      showToast(error.message || 'Could not save it.');
    }
  }

  async function setHealthConsent(input) {
    const on = input.checked;
    if (!on && !window.confirm('Switch off health memory? What it remembered about health is deleted.')) {
      input.checked = true;
      return;
    }
    try {
      await api('/api/settings', {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({health_memory_consent: on})});
      showToast(on ? 'Health memory is on.' : 'Health memory is off. What it remembered is deleted.');
    } catch (error) {
      input.checked = !on;
      showToast(error.message || 'Could not change it.');
    }
    await redrawMemory();
  }

  // --- Timeline: a week or a month of spikes (change 011) ------------------------------
  const MONTH_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
    'August', 'September', 'October', 'November', 'December'];
  const timeline = {mode: 'week', anchor: null};
  const dateOf = iso => new Date(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)));

  async function renderTimeline() {
    const root = $('timelineView');
    const token = ++timelineToken;
    const [tasks, completed] = await Promise.all([
      api(withLens('/api/tasks?status=open')).catch(() => []),
      api(withLens('/api/tasks?status=completed')).catch(() => []),
    ]);
    if (token !== timelineToken) return;
    const todayIso = L.isoDate(new Date());
    const anchorIso = timeline.anchor || todayIso;
    const month = timeline.mode === 'month';
    const days = month ? L.monthDays(dateOf(anchorIso)) : L.weekDays(dateOf(anchorIso));
    const due = tasks
      .filter(task => days.includes(L.taskDay(task)))
      .sort((first, second) => L.taskDay(first).localeCompare(L.taskDay(second))
        || (first.due_time || '').localeCompare(second.due_time || ''));
    const undated = tasks.filter(task => !L.taskDay(task)).length;
    const anchor = dateOf(anchorIso);
    const title = month
      ? `${MONTH_LONG[anchor.getMonth()]} ${anchor.getFullYear()}`
      : `${L.formatDay(days[0])} – ${L.formatDay(days[6])}`;
    const span = month ? 'month' : 'week';
    root.innerHTML = `
      <div class="timeline-bar">
        <div class="segmented" role="group" aria-label="Show a week or a month">
          <button type="button" class="${month ? '' : 'is-on'}" aria-pressed="${!month}" data-timeline-mode="week">Week</button>
          <button type="button" class="${month ? 'is-on' : ''}" aria-pressed="${month}" data-timeline-mode="month">Month</button>
        </div>
        <div class="timeline-nav">
          <button type="button" class="secondary small-btn" data-timeline-shift="-1" aria-label="Previous ${span}">‹</button>
          <span class="timeline-title" aria-live="polite">${escapeHtml(title)}</span>
          <button type="button" class="secondary small-btn" data-timeline-shift="1" aria-label="Next ${span}">›</button>
          <button type="button" class="secondary small-btn" data-timeline-today>Today</button>
        </div>
        <button type="button" class="chip chip-muted undated-chip" data-open-backlog>Undated: ${undated}</button>
      </div>
      <article class="card card-wide">${dayChart(tasks, days, {large: !month, compact: month, done: L.doneByDay(completed, days, todayIso)})}
        <p class="legend"><span class="legend-bar is-confirmed"></span> Date set <span class="legend-bar is-suggested"></span> Suggested, waiting for your OK <span class="legend-bar is-high is-confirmed"></span> High priority <span class="week-done-legend" aria-hidden="true">✓</span> Done that day</p>
      </article>
      <article class="card card-wide">
        <h2>Due this ${span}</h2>
        ${due.length ? due.map(task => taskRow(task)).join('') : `<p class="muted">Nothing dated this ${span}${Lens.key ? ` in ${escapeHtml(Lens.name)}` : ''}.</p>`}
        <p class="muted small">${undated ? `${plural(undated, 'open task')} ${undated === 1 ? 'has' : 'have'} no date yet. <button type="button" class="link-btn" data-open-backlog>Give ${undated === 1 ? 'it' : 'them'} a date in Priority</button>.` : 'Every open task has a date.'}</p>
      </article>`;
  }

  function setTimeline(changes) {
    Object.assign(timeline, changes);
    renderTimeline();
  }

  // --- Calendar: the day's list opens as a pop-up by the day (change 011) ----------------
  function openDayPopup(date) {
    const panel = $('inAppCalendar');
    const details = $('calendarDayDetails');
    const cell = $('calendarGrid').querySelector(`.cal-day-cell[data-date="${date}"]`);
    if (!panel || !details || !cell) return;
    state.dayPopup = date;
    details.hidden = false;
    details.classList.add('is-popup');
    if (window.matchMedia('(max-width: 900px)').matches) {
      details.style.left = '';
      details.style.top = '';
      details.style.width = '';
    } else {
      const box = panel.getBoundingClientRect();
      const at = cell.getBoundingClientRect();
      const width = Math.min(360, box.width - 24);
      details.style.width = `${width}px`;
      details.style.left = `${Math.max(12, Math.min(at.left - box.left, box.width - width - 12))}px`;
      details.style.top = `${at.bottom - box.top + 6}px`;
    }
    details.querySelector('.panel-close').focus();
  }

  function closeDayPopup({restoreFocus = true} = {}) {
    const details = $('calendarDayDetails');
    if (!details || details.hidden) return false;
    details.hidden = true;
    const cell = restoreFocus && $('calendarGrid').querySelector(`.cal-day-cell[data-date="${state.dayPopup}"]`);
    if (cell) cell.focus();
    return true;
  }

  function watchCalendarDays() {
    const grid = $('calendarGrid');
    if (!grid) return;
    // app.js's own handlers run first: they select the day and draw its list
    // (and redraw the grid, so the cell is found again by its date).
    const open = target => {
      const cell = target.closest('.cal-day-cell');
      if (!cell || cell.classList.contains('cal-day-other')) return;
      const date = cell.dataset.date;
      requestAnimationFrame(() => openDayPopup(date));
    };
    grid.addEventListener('click', event => open(event.target));
    grid.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') open(event.target);
      else if (event.key.startsWith('Arrow')) closeDayPopup({restoreFocus: false});
    });
    for (const id of ['calPrevBtn', 'calNextBtn', 'calTodayBtn']) {
      const button = $(id);
      if (button) button.addEventListener('click', () => closeDayPopup({restoreFocus: false}));
    }
    document.addEventListener('click', event => {
      const details = $('calendarDayDetails');
      if (!details || details.hidden) return;
      if (details.contains(event.target) || event.target.closest('.cal-day-cell')) return;
      closeDayPopup({restoreFocus: false});
    });
  }

  // --- Priority: High, Medium and Low columns; drag to change (change 011) ----------------
  const priorityView = {groupByArea: false};
  let priorityToken = 0;

  async function renderPriority() {
    const token = ++priorityToken;
    const tasks = await api(withLens('/api/tasks?status=open')).catch(() => null);
    if (token !== priorityToken) return;
    if (!tasks) {
      $('priorityBoard').innerHTML = '<p class="status error">Could not load your tasks. Try again.</p>';
      return;
    }
    const today = L.isoDate(new Date());
    const shown = tasks.map(task => ({...task, ...L.boardPriority(task, today)}));
    const split = L.prioritySplit(shown, today);
    const where = Lens.key ? ` in ${escapeHtml(Lens.name)}` : '';
    $('prioritySummary').innerHTML = split.board.length
      ? `${plural(split.board.length, 'task')} for today and the next few days${where}. Drag a card to another column to change its priority.`
      : `Nothing due today or soon${where}. Later, undated and snoozed tasks wait in the backlog.`;
    $('priorityBoard').innerHTML = priorityBoardHtml(split.board, 'board');
    $('priorityBacklogBoard').innerHTML = priorityBoardHtml(split.backlog, 'backlog');
    $('priorityBacklogHeading').textContent = `Backlog (${split.backlog.length})`;
    $('priorityBacklog').hidden = !split.backlog.length;
    const someday = L.somedayTasks(tasks);
    $('prioritySomedayHeading').textContent = `Someday (${someday.length})`;
    $('prioritySomeday').hidden = !someday.length;
    $('prioritySomedayList').innerHTML = someday.map(task => `<div class="row">
        ${(task.source_item_ids || [])[0]
          ? `<button type="button" class="row-link" data-open-note="${task.source_item_ids[0]}">${escapeHtml(task.text)}</button>`
          : `<span class="row-link">${escapeHtml(task.text)}</span>`}
        <button type="button" class="link-btn small" data-someday-off="${task.id}">Back to my list</button>
      </div>`).join('');
  }

  function priorityBoardHtml(tasks, where) {
    return L.priorityColumns(tasks).map(column => {
      const cards = priorityView.groupByArea
        ? L.groupByArea(column.tasks, state.bots).map(group => `
            <h4 class="mini-heading">${escapeHtml(group.name)}</h4>${group.tasks.map(priorityCard).join('')}`).join('')
        : column.tasks.map(priorityCard).join('');
      return `<section class="pcol" data-drop-priority="${column.priority}" aria-labelledby="pcol-${where}-${column.priority}">
        <h3 id="pcol-${where}-${column.priority}" class="pcol-head"><span class="pri pri-${column.priority.toLowerCase()}">${column.priority}</span><span class="count">${column.tasks.length}</span></h3>
        ${cards || '<p class="muted small pcol-empty">Nothing here.</p>'}
      </section>`;
    }).join('');
  }

  function priorityCard(task) {
    const source = (task.source_item_ids || [])[0];
    const bot = state.botsByKey[task.bot_key];
    const date = dateChip(task);
    return `<article class="pcard" draggable="true" data-task-id="${task.id}" data-priority="${escapeHtml(task.priority)}">
      ${source
        ? `<button type="button" class="row-link" data-open-note="${source}">${escapeHtml(task.text)}</button>`
        : `<span class="pcard-title">${escapeHtml(task.text)}</span>`}
      <div class="row-meta">
        ${bot ? `<span class="chip bot-chip bot-${escapeHtml(bot.key)}">${escapeHtml(bot.name)}</span>` : ''}
        ${date}
        ${task.snoozed_until ? `<span class="chip chip-muted" title="The date stays; it reminds you again that day">Reminds you ${escapeHtml(L.formatDay(task.snoozed_until))}</span>` : ''}
        ${task.user_priority ? '<span class="chip chip-muted" title="You chose this priority">Your pick</span>' : ''}
        ${task.raised ? `<span class="chip chip-soon" title="Raised from ${escapeHtml(task.ai_priority || 'its priority')} because it's due soon">↑ Due soon</span>` : ''}
      </div>
      ${task.reason ? `<p class="muted small pcard-why">Why: ${escapeHtml(task.reason)}</p>` : ''}
      <div class="pcard-foot">
        <label class="visually-hidden" for="pmove-${task.id}">Priority for ${escapeHtml(task.text)}</label>
        <select id="pmove-${task.id}" class="pmove" data-task-priority="${task.id}">${['High', 'Medium', 'Low'].map(value => `<option${value === task.priority ? ' selected' : ''}>${value}</option>`).join('')}</select>
        ${task.user_priority && task.ai_priority && task.ai_priority !== task.user_priority
          ? `<button type="button" class="link-btn small" data-reset-priority="${task.id}">Back to Life Inbox's (${escapeHtml(task.ai_priority)})</button>` : ''}
        ${!L.taskDay(task) ? `<button type="button" class="link-btn small" data-someday-on="${task.id}">Someday</button>` : ''}
      </div>
    </article>`;
  }

  function taskMessage(text) {
    const status = $('taskStatus');
    if (status) status.textContent = text;
  }

  async function setTaskPriority(taskId, priority) {
    const card = document.querySelector(`.pcard[data-task-id="${taskId}"]`);
    if (card && priority && card.dataset.priority === priority) return;
    const title = card ? (card.querySelector('.row-link, .pcard-title') || {}).textContent : 'The task';
    try {
      await api(`/api/tasks/${taskId}`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({priority}),
      });
      taskMessage(priority
        ? `Moved “${title}” to ${priority}. Life Inbox will keep your choice.`
        : `“${title}” follows Life Inbox's priority again.`);
      reloadV1Lists();
      changed();
    } catch (error) {
      taskMessage(error.message || 'Could not change the priority.');
      renderPriority();
    }
  }

  function watchPriorityDrag() {
    const cardOf = target => (target instanceof Element ? target.closest('.pcard') : null);
    const columnOf = target => (target instanceof Element ? target.closest('[data-drop-priority]') : null);
    document.addEventListener('dragstart', event => {
      const card = cardOf(event.target);
      if (!card) return;
      event.dataTransfer.setData('text/plain', card.dataset.taskId);
      event.dataTransfer.effectAllowed = 'move';
      card.classList.add('is-dragging');
    });
    document.addEventListener('dragend', event => {
      const card = cardOf(event.target);
      if (card) card.classList.remove('is-dragging');
      for (const column of document.querySelectorAll('.pcol.is-over')) column.classList.remove('is-over');
    });
    document.addEventListener('dragover', event => {
      const column = columnOf(event.target);
      if (!column) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      column.classList.add('is-over');
    });
    document.addEventListener('dragleave', event => {
      const column = columnOf(event.target);
      if (column && !column.contains(event.relatedTarget)) column.classList.remove('is-over');
    });
    document.addEventListener('drop', event => {
      const column = columnOf(event.target);
      if (!column) return;
      event.preventDefault();
      column.classList.remove('is-over');
      const id = Number(event.dataTransfer.getData('text/plain'));
      if (id) setTaskPriority(id, column.dataset.dropPriority);
    });
  }

  // --- Dashboard: your life at a glance (change 011) ---------------------------------------
  let glanceToken = 0;

  async function renderGlance() {
    const root = $('glanceView');
    const token = ++glanceToken;
    let glance;
    try {
      const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
      glance = await api(withLens(`/api/dashboard/glance${zone ? `?tz=${encodeURIComponent(zone)}` : ''}`));
    } catch {
      if (token === glanceToken) root.innerHTML = '<p class="status error">Could not load the dashboard. Try again.</p>';
      return;
    }
    if (token !== glanceToken) return;
    $('glanceSub').textContent = Lens.key
      ? `${Lens.name} at a glance. Worked out from its notes and tasks.`
      : 'Your life at a glance. Worked out from your notes and tasks.';
    const most = Math.max(1, ...glance.attention.map(row => row.count));
    const attention = glance.attention.map(row => {
      const name = row.id != null
        ? `<button type="button" class="attn-name" data-open-topic="${row.id}">${escapeHtml(row.name)}</button>`
        : row.key
          ? `<button type="button" class="attn-name" data-bot="${escapeHtml(row.key)}">${escapeHtml(row.name)}</button>`
          : `<span class="attn-name">${escapeHtml(row.name)}</span>`;
      return `<div class="attn-row bot-${escapeHtml(row.key || 'none')}">${name}
        <span class="attn-bar" aria-hidden="true"><span data-share="${row.count / most}"></span></span>
        <span class="count">${row.count}</span></div>`;
    }).join('');
    const topicList = (rows, text) => rows.length
      ? rows.map(row => `<button type="button" class="row-link block" data-open-topic="${row.id}">${escapeHtml(row.name)} <span class="muted small">${escapeHtml(text(row))}</span></button>`).join('')
      : '';
    const growing = topicList(glance.growing, row => `${row.count} new in 2 weeks`);
    const quiet = topicList(glance.quiet, row => `nothing new for ${row.days} days`);
    const coming = glance.coming_up.map(task => taskRow({...task, source_item_ids: task.source_item_id ? [task.source_item_id] : []})).join('');
    const busiest = glance.busiest_day;
    root.innerHTML = `
      <div class="metrics">
        <div class="metric card"><span class="muted">Captured this week</span><b>${glance.captured_this_week}</b></div>
        <div class="metric card"><span class="muted">Tasks done this week</span><b>${glance.tasks_done_this_week}</b><span class="muted small">${plural(glance.open_tasks, 'open task')}</span></div>
        <div class="metric card"><span class="muted">Busiest day</span><b>${busiest ? escapeHtml(busiest.weekday) : '—'}</b><span class="muted small">${busiest ? plural(busiest.count, 'note') : 'Nothing captured yet this week'}</span></div>
      </div>
      <div class="home-row">
        <article class="card" aria-labelledby="attentionCardHeading">
          <div class="card-head">${icon('timeline')}<h2 id="attentionCardHeading">Where your attention went</h2></div>
          <p class="muted small">${Lens.key ? 'Notes per topic' : 'Notes per life area'}, last ${glance.attention_window_days} days</p>
          ${attention || '<p class="muted">No topics here yet.</p>'}
        </article>
        <article class="card" aria-labelledby="noticedCardHeading">
          <div class="card-head"><span class="crew-icon">${icon('captain')}</span><h2 id="noticedCardHeading">Captain noticed</h2></div>
          ${glance.noticed.map(line => `<p class="noticed">${icon('spark', 14)}<span>${escapeHtml(line)}</span></p>`).join('')}
        </article>
      </div>
      <div class="home-row">
        <article class="card" aria-labelledby="topicsMoveHeading">
          <div class="card-head">${icon('topics')}<h2 id="topicsMoveHeading">Growing and quiet topics</h2></div>
          <h3 class="mini-heading">Growing</h3>${growing || '<p class="muted small">No topic got 2 or more new notes in the last 2 weeks.</p>'}
          <h3 class="mini-heading">Quiet</h3>${quiet || '<p class="muted small">Every topic with notes got something new in the last 30 days.</p>'}
        </article>
        <article class="card" aria-labelledby="comingUpHeading">
          <div class="card-head">${icon('flag')}<h2 id="comingUpHeading">Coming up</h2><a class="card-link" href="#/timeline">Timeline ›</a></div>
          ${coming || '<p class="muted">Nothing dated from today on.</p>'}
        </article>
      </div>`;
    for (const bar of root.querySelectorAll('[data-share]')) {
      bar.style.width = `${Math.round(Number(bar.dataset.share) * 100)}%`;
    }
  }

  // --- Search (the header box; follows the lens) ------------------------------------------
  async function renderSearch() {
    const root = $('searchView');
    const query = state.query;
    const token = ++searchToken;
    $('globalSearch').value = query;
    if (!query) {
      root.innerHTML = '<p class="muted">Type in the search box at the top to find notes.</p>';
      return;
    }
    root.innerHTML = '<p class="muted">Searching…</p>';
    let hits;
    try {
      hits = await api(withLens(`/api/search?q=${encodeURIComponent(query)}&limit=25`));
    } catch {
      if (token === searchToken) root.innerHTML = '<p class="status error">Search failed. Try again.</p>';
      return;
    }
    if (token !== searchToken) return;
    const where = Lens.key ? ` in ${escapeHtml(Lens.name)}` : '';
    if (!hits.length) {
      root.innerHTML = `<p class="muted">No notes match “${escapeHtml(query)}”${where}.</p>${Lens.key ? '<button type="button" class="secondary" data-clear-lens>Search everything</button>' : ''}`;
      return;
    }
    root.innerHTML = `<p class="muted">${plural(hits.length, 'result')} for “${escapeHtml(query)}”${where}.</p>
      <div class="result-list">${hits.map(hit => `
        <button type="button" class="result-row" data-open-note="${hit.item_id}">
          <span class="chip">${escapeHtml(typeLabel(hit.item_type))}</span>
          <span class="result-text"><b>${escapeHtml(hit.title)}</b><span class="muted">${escapeHtml(hit.excerpt)}</span></span>
        </button>`).join('')}</div>`;
  }

  // --- Topics and spaces: cards by life area, packed into columns (change 010) -------------
  const MASONRY_ROW = 6;
  const MASONRY_GAP = 14;

  function topicEntryRows(entries) {
    return entries.map(({topic, subtopics}) => `
      <button type="button" class="topic-row${topic.total_item_count ? '' : ' is-empty'}" data-open-topic="${topic.id}">
        <span><b>${escapeHtml(topic.name)}</b><span class="muted">${escapeHtml(topic.description || '')}</span></span>
        <span class="count">${topic.total_item_count}</span>
      </button>
      ${subtopics.map(sub => `<button type="button" class="topic-row is-sub${sub.item_count ? '' : ' is-empty'}" data-open-topic="${sub.id}">
        <span>↳ ${escapeHtml(sub.name)}</span><span class="count">${sub.item_count}</span></button>`).join('')}`).join('');
  }

  function renderTopics() {
    const root = $('topicGroups');
    if (!root) return;
    const groups = L.topicGroups(state.bots, state.topics, Lens.key);
    const notes = groups.reduce((sum, group) => sum + group.count, 0);
    const shown = groups.reduce((sum, group) => sum + group.entries
      .reduce((inner, entry) => inner + 1 + entry.subtopics.length, 0), 0);
    $('topicsSummary').textContent = Lens.key
      ? `${plural(notes, 'note')} in ${plural(shown, 'topic')} in ${Lens.name}.`
      : `${plural(notes, 'note')} in ${plural(shown, 'topic')} · busiest areas first`;
    const cards = groups.map(group => `
      <article class="card topic-group bot-${escapeHtml(group.key || 'none')}" aria-label="${escapeHtml(group.name)}">
        <div class="card-head">
          <span class="bot-icon">${icon(group.key || 'topics')}</span>
          <div><h2>${escapeHtml(group.name)}</h2><p class="muted small">${plural(group.count, 'note')}</p></div>
        </div>
        ${topicEntryRows(group.entries) || '<p class="muted">No topics here yet.</p>'}
      </article>`);
    cards.push(`
      <article class="card topic-group ghost" aria-labelledby="addTopicCardHeading">
        <div class="card-head">${icon('spark')}<h2 id="addTopicCardHeading">Add your own topic</h2></div>
        <p class="muted">Every area starts with 3 topics. Add as many topics and subtopics as you like, such as Study › Python.</p>
        <button type="button" class="secondary small-btn" data-new-topic>+ New topic</button>
      </article>`);
    root.innerHTML = cards.join('');
    packMasonry(root);
  }

  // Each card spans as many 6 px rows as its height needs; with dense flow,
  // cards fill the shortest column, so no column ends in a long gap.
  function packMasonry(root) {
    if (!root || !root.offsetParent) return;
    const cards = [...root.children];
    for (const card of cards) card.style.gridRowEnd = 'auto';
    const heights = cards.map(card => card.getBoundingClientRect().height);
    cards.forEach((card, index) => {
      card.style.gridRowEnd = `span ${Math.ceil((heights[index] + MASONRY_GAP) / MASONRY_ROW)}`;
    });
  }

  function watchMasonry() {
    const root = $('topicGroups');
    if (!root || typeof ResizeObserver !== 'function') return;
    let width = 0;
    let frame = 0;
    new ResizeObserver(entries => {
      const next = Math.round(entries[0].contentRect.width);
      if (next === width) return;
      width = next;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => packMasonry(root));
    }).observe(root);
  }

  function openNewTopic() {
    if (state.view !== 'topics') goTo('topics');
    $('topicsStatus').textContent = '';
    const panel = $('newTopicPanel');
    panel.hidden = false;
    panel.scrollIntoView({block: 'nearest'});
    $('topicName').focus();
  }

  function closeNewTopic() {
    if (typeof resetTopicForm === 'function') resetTopicForm();
    $('newTopicPanel').hidden = true;
    $('newTopicButton').focus();
  }

  // --- the topic page: one topic, its notes, and what you can do with it --------------
  const TOPIC_PAGE_SIZE = 30;
  const topicPage = {id: null, type: '', items: [], more: false, editing: false, deleting: false, message: ''};
  let topicToken = 0;

  function openTopicNotes(topicId) {
    if (!Number(topicId)) return;
    closeSheet();
    goTo('topic', String(topicId));
  }

  async function fetchTopicItems(id, offset) {
    const type = topicPage.type ? `&item_type=${encodeURIComponent(topicPage.type)}` : '';
    const items = await api(`/api/items?topic_id=${id}&order=desc&limit=${TOPIC_PAGE_SIZE + 1}&offset=${offset}${type}`);
    return {items: items.slice(0, TOPIC_PAGE_SIZE), more: items.length > TOPIC_PAGE_SIZE};
  }

  async function renderTopicPage() {
    const root = $('topicPage');
    const id = Number(state.query);
    if (topicPage.id !== id) {
      Object.assign(topicPage, {id, type: '', items: [], more: false, editing: false, deleting: false, message: ''});
      root.innerHTML = '<p class="muted">Opening the topic…</p>';
    } else if (topicPage.editing || topicPage.deleting) {
      return; // don't wipe a form the user is filling in
    }
    const token = ++topicToken;
    let detail;
    let page;
    try {
      [detail, page] = await Promise.all([api(`/api/topics/${id}`), fetchTopicItems(id, 0)]);
    } catch {
      if (token === topicToken) {
        root.innerHTML = `<a class="back-link" href="#/topics">← All topics</a>
          <h1 id="topicPageTitle" class="view-title">Topic not found</h1>
          <p class="muted">It may have been deleted.</p>`;
      }
      return;
    }
    if (token !== topicToken) return;
    topicPage.items = page.items;
    topicPage.more = page.more;
    for (const item of page.items) noteCache.set(item.id, item);
    drawTopicPage(detail);
  }

  function drawTopicPage(topic) {
    const root = $('topicPage');
    const parent = topic.parent_topic_id ? state.topicsById[topic.parent_topic_id] : null;
    const subtopics = state.topics
      .filter(other => other.parent_topic_id === topic.id && !other.archived)
      .sort((first, second) => second.item_count - first.item_count || first.name.localeCompare(second.name));
    const bot = state.botsByKey[topic.bot_key];
    const builtIn = topic.is_built_in;
    const canMove = !builtIn && !topic.parent_topic_id;
    const filters = L.typeFilters(topic.type_counts);
    const areaOptions = (topic.bot_key ? '' : '<option value="" selected disabled>Choose an area</option>')
      + state.bots.map(option => `<option value="${escapeHtml(option.key)}"${option.key === topic.bot_key ? ' selected' : ''}>${escapeHtml(option.name)}</option>`).join('');
    const moveNote = builtIn
      ? 'Built-in topics stay in their life area.'
      : topic.parent_topic_id ? `It moves with ${escapeHtml(parent ? parent.name : 'its parent topic')}.` : '';

    root.innerHTML = `
      <a class="back-link" href="#/topics">← All topics</a>
      <nav class="breadcrumb" aria-label="Where this topic sits">
        ${bot ? `<button type="button" class="crumb" data-set-lens="${escapeHtml(bot.key)}">${escapeHtml(bot.name)}</button>` : '<span>Not in an area yet</span>'}
        ${parent ? `<span aria-hidden="true">›</span><button type="button" class="crumb" data-open-topic="${parent.id}">${escapeHtml(parent.name)}</button>` : ''}
      </nav>
      <div class="topic-head">
        <h1 id="topicPageTitle" class="view-title">${escapeHtml(topic.name)}</h1>
        ${builtIn ? '<span class="chip chip-muted">Built in</span>' : ''}
      </div>
      <p class="view-sub">${escapeHtml(topic.description || 'No description yet.')} · ${plural(topic.total_item_count, 'note')}</p>
      ${topic.proposed_by ? `<p class="muted small topic-history">Suggested by the ${escapeHtml((state.botsByKey[topic.proposed_by] || {}).name || topic.proposed_by)} bot from ${(topic.evidence_item_ids || []).map(id => `<button type="button" class="link-btn small" data-open-note="${Number(id)}">note #${Number(id)}</button>`).join(', ')}${topic.approved_at ? `; approved by you on ${escapeHtml(L.formatDay(L.isoDate(new Date(topic.approved_at))))}` : ''}.</p>` : ''}
      ${subtopics.length ? `<div class="chips topic-subtopics" aria-label="Subtopics">${subtopics.map(sub => `
        <button type="button" class="chip chip-topic" data-open-topic="${sub.id}">↳ ${escapeHtml(sub.name)} · ${sub.item_count}</button>`).join('')}</div>` : ''}

      <div class="topic-actions" id="topicActions">
        <button type="button" class="secondary small-btn" data-topic-edit>Rename or edit description</button>
        ${canMove ? `<label class="move-topic">Life area
          <select id="topicMoveArea" data-topic-move>${areaOptions}</select></label>` : `<span class="muted small">${moveNote}</span>`}
        ${builtIn ? '' : '<button type="button" class="secondary small-btn danger-text" data-topic-delete>Delete topic</button>'}
      </div>
      <div id="topicEditor"></div>
      <p id="topicPageStatus" class="status muted" role="status" aria-live="polite">${escapeHtml(topicPage.message)}</p>

      <section class="view-card topic-notes" aria-labelledby="topicNotesHeading">
        <div class="card-head"><h2 id="topicNotesHeading">Notes</h2></div>
        ${filters.length > 2 ? `<div class="chips type-filters" role="group" aria-label="Show">${filters.map(filter => `
          <button type="button" class="chip${filter.type === topicPage.type ? ' is-on' : ''}" aria-pressed="${filter.type === topicPage.type}" data-topic-type="${filter.type}">${escapeHtml(filter.label)} · ${filter.count}</button>`).join('')}</div>` : ''}
        <div id="topicItems">${topicItemRows(topicPage.items)}</div>
        ${topicPage.more ? '<button type="button" class="secondary small-btn" data-topic-more>Show more</button>' : ''}
      </section>`;
    root.dataset.topic = JSON.stringify({id: topic.id, item_count: topic.item_count, name: topic.name, parent_topic_id: topic.parent_topic_id, description: topic.description || ''});
  }

  function topicItemRows(items) {
    if (!items.length) {
      return topicPage.type
        ? '<p class="muted">None of this kind here.</p>'
        : '<p class="muted">Nothing here yet. Notes about this land here automatically.</p>';
    }
    return items.map(item => `<div class="row">
      <span class="chip">${escapeHtml(typeLabel(item.item_type))}</span>
      <button type="button" class="row-link" data-open-note="${item.id}">${escapeHtml(itemTitle(item))}</button>
      <span class="muted small">${escapeHtml(savedOn(item.created_at))}</span>
    </div>`).join('');
  }

  // Stored times are UTC; show the day it was in the user's own time zone.
  function savedOn(timestamp) {
    const when = new Date(timestamp);
    return Number.isNaN(when.getTime()) ? '' : L.formatDay(L.isoDate(when));
  }

  function currentTopic() {
    try { return JSON.parse($('topicPage').dataset.topic || 'null'); } catch { return null; }
  }

  async function showMoreTopicItems(button) {
    button.disabled = true;
    try {
      const page = await fetchTopicItems(topicPage.id, topicPage.items.length);
      topicPage.items = topicPage.items.concat(page.items);
      topicPage.more = page.more;
      $('topicItems').innerHTML = topicItemRows(topicPage.items);
      if (!page.more) button.remove();
      else button.disabled = false;
    } catch {
      button.disabled = false;
      setTopicMessage('Could not load more notes.');
    }
  }

  async function filterTopicItems(type) {
    topicPage.type = type;
    for (const chip of document.querySelectorAll('[data-topic-type]')) {
      const on = chip.dataset.topicType === type;
      chip.classList.toggle('is-on', on);
      chip.setAttribute('aria-pressed', String(on));
    }
    try {
      const page = await fetchTopicItems(topicPage.id, 0);
      topicPage.items = page.items;
      topicPage.more = page.more;
      $('topicItems').innerHTML = topicItemRows(page.items);
      const more = document.querySelector('[data-topic-more]');
      if (more && !page.more) more.remove();
    } catch {
      setTopicMessage('Could not load these notes.');
    }
  }

  function setTopicMessage(text) {
    topicPage.message = text;
    const status = $('topicPageStatus');
    if (status) status.textContent = text;
  }

  function startTopicEdit() {
    const topic = currentTopic();
    if (!topic) return;
    topicPage.editing = true;
    topicPage.deleting = false;
    setTopicMessage('');
    $('topicEditor').innerHTML = `
      <form id="topicEditForm" class="view-card topic-edit-form">
        <label>Name <input id="topicEditName" maxlength="80" required value="${escapeHtml(topic.name)}" /></label>
        <label>Description <textarea id="topicEditDescription" maxlength="400" rows="2">${escapeHtml(topic.description)}</textarea>
          <span class="muted small">Life Inbox uses this to decide which notes go into the topic.</span></label>
        <div class="topic-suggestion-actions">
          <button type="submit">Save</button>
          <button type="button" class="secondary" data-topic-edit-cancel>Cancel</button>
        </div>
      </form>`;
    $('topicEditForm').addEventListener('submit', saveTopicEdit);
    $('topicEditName').focus();
  }

  function stopTopicEdit() {
    topicPage.editing = false;
    topicPage.deleting = false;
    $('topicEditor').innerHTML = '';
  }

  async function saveTopicEdit(event) {
    event.preventDefault();
    const name = $('topicEditName').value.trim();
    const description = $('topicEditDescription').value.trim();
    if (!name) {
      setTopicMessage('Give the topic a name.');
      return;
    }
    try {
      await api(`/api/topics/${topicPage.id}`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, description}),
      });
      stopTopicEdit();
      setTopicMessage('Saved.');
      changed();
    } catch (error) {
      setTopicMessage(error.message || 'Could not save the topic.');
    }
  }

  async function moveTopicArea(select) {
    const key = select.value;
    const bot = state.botsByKey[key];
    try {
      await api(`/api/topics/${topicPage.id}`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({bot_key: key}),
      });
      setTopicMessage(`Moved to ${bot ? bot.name : 'that area'}, with its subtopics.`);
      changed();
    } catch (error) {
      setTopicMessage(error.message || 'Could not move the topic.');
    }
  }

  function askTopicDelete() {
    const topic = currentTopic();
    if (!topic || topicPage.deleting) return;
    topicPage.deleting = true;
    topicPage.editing = false;
    setTopicMessage('');
    const parent = topic.parent_topic_id ? state.topicsById[topic.parent_topic_id] : null;
    const subtopics = state.topics.filter(other => other.parent_topic_id === topic.id);
    const preview = typeof topicDeletePreview === 'function'
      ? topicDeletePreview(topic, parent, subtopics)
      : `Delete “${topic.name}”? This can't be undone.`;
    $('topicEditor').innerHTML = `
      <div class="danger-box" role="alertdialog" aria-labelledby="topicDeleteText">
        <p id="topicDeleteText">${escapeHtml(preview)}</p>
        <div class="topic-suggestion-actions">
          <button type="button" class="danger" data-topic-delete-yes>Yes, delete</button>
          <button type="button" class="secondary" data-topic-edit-cancel>Cancel</button>
        </div>
      </div>`;
    document.querySelector('[data-topic-edit-cancel]').focus();
  }

  async function deleteCurrentTopic(button) {
    const topic = currentTopic();
    if (!topic) return;
    button.disabled = true;
    button.textContent = 'Deleting…';
    setTopicMessage(`Deleting “${topic.name}” and moving its notes…`);
    try {
      const result = await api(`/api/topics/${topic.id}`, {method: 'DELETE'});
      topicPage.deleting = false;
      topicPage.id = null;
      goTo('topics');
      $('topicsStatus').textContent = typeof topicDeleteSummary === 'function'
        ? topicDeleteSummary(result) : `Deleted “${topic.name}”.`;
      changed();
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Yes, delete';
      setTopicMessage(error.message || 'Could not delete the topic.');
    }
  }

  // --- Dates (change 012) ----------------------------------------------------------------
  // Each date shows where it stands: "✓ Fri 13 Nov" confirmed by you, "Fri 13 Nov"
  // from your note's own words, "Sat 7 Nov? · confirm" a suggestion waiting for
  // your OK (it stays off the calendar until then). Any date chip, "Postpone" on
  // the Calendar pop-up and on task cards open the picker.
  // Questions about dates (a guess, or a date your edit moved) wait their turn here.
  const dateQuestions = [];

  function dateChip(task) {
    if (!task || !task.id) return '';
    const stand = L.dateState(task);
    const day = L.taskDay(task);
    const time = task.due_on ? task.due_time : task.suggested_due_time;
    const when = day ? `${L.formatDay(day)}${time ? ` · ${time}` : ''}` : '';
    // `tip` is the hover text: where the date came from, and what a click does.
    const view = {
      confirmed: {cls: 'chip chip-confirmed', label: `✓ ${when}`, aria: `${when}, confirmed by you. Change the date`, tip: 'Confirmed by you · click to change'},
      note: {cls: 'chip', label: when, aria: `${when}, from your note. Change the date`, tip: 'From your note · click to change'},
      suggested: {cls: 'chip chip-dashed', label: `${when}? · confirm`, aria: `Suggested ${when}, waiting for your OK. Confirm or change it`, tip: 'Suggested from your words, not on your calendar yet · click to confirm or change'},
      none: {cls: 'chip chip-muted', label: 'No date · set', aria: 'Set a date', tip: 'No date yet · click to set one'},
    }[stand];
    return `<button type="button" class="${view.cls} date-chip" data-date-task="${task.id}" aria-label="${escapeHtml(view.aria)}" title="${escapeHtml(view.tip)}">${escapeHtml(view.label)}</button>`;
  }

  async function openDatePicker(taskId, anchor, ask = null) {
    closeHover();
    const returnFocus = document.activeElement;
    if (!ask) closeDatePicker({restoreFocus: false, next: false});
    const tasks = await api('/api/tasks?status=all').catch(() => []);
    const task = tasks.find(other => other.id === taskId);
    if (!task) return false;
    if (ask) {
      if (!stillToAsk(task, ask)) return false;
      if (state.datePicker) {
        // A date was opened meanwhile: this question waits its turn.
        dateQuestions.unshift(ask);
        return false;
      }
    }
    const today = L.isoDate(new Date());
    const selected = L.taskDay(task) || L.addDays(today, 1);
    const time = (task.due_on ? task.due_time : task.suggested_due_time) || '';
    state.datePicker = {taskId, anchor, task, selected, month: selected, time, showTime: Boolean(time), ask, expanded: false, returnFocus};
    drawDatePicker();
    const picker = $('datePicker');
    picker.hidden = false;
    $('datePickerBackdrop').hidden = !ask;
    if (ask) $('toast').hidden = true;
    placeDatePicker(picker, anchor);
    if (ask) {
      // While you're typing, Yes isn't put under your fingers: Enter or Space
      // mustn't answer for you. Tab reaches the buttons.
      (isTyping(returnFocus) ? picker : picker.querySelector('[data-ask-yes]') || picker).focus();
    } else {
      const first = picker.querySelector('[data-confirm-date], [data-pick-date]') || picker.querySelector('.month-day.is-selected');
      if (first) first.focus();
    }
    return true;
  }

  function drawDatePicker(focusSelected = false) {
    const view = state.datePicker;
    if (!view) return;
    const {task} = view;
    const picker = $('datePicker');
    // A question asks first (Yes · Pick another day · Ask me later); "Pick
    // another day" opens this full picker in its place, on the same dimmed page.
    const asking = Boolean(view.ask && !view.expanded);
    picker.classList.toggle('is-question', asking);
    if (view.ask) picker.setAttribute('aria-modal', 'true');
    else picker.removeAttribute('aria-modal');
    if (asking) {
      drawDateQuestion(view, picker);
      return;
    }
    picker.removeAttribute('aria-describedby');
    const today = L.isoDate(new Date());
    const stand = L.dateState(task);
    const day = L.taskDay(task);
    const at = (task.due_on ? task.due_time : task.suggested_due_time) ? ` at ${task.due_on ? task.due_time : task.suggested_due_time}` : '';
    const now = {
      confirmed: `Now: ${L.formatDay(day)}${at} · confirmed by you`,
      note: `Now: ${L.formatDay(day)}${at} · from your note`,
      suggested: `Suggested: ${L.formatDay(day)}${at}${task.timing_text ? `, from “${task.timing_text}”` : ''}. It stays off the calendar until you confirm it.`,
      none: 'No date yet',
    }[stand];
    const grid = L.monthGrid(view.month);
    const choices = L.postponeChoices(task.due_on, today);
    picker.innerHTML = `
      <button type="button" class="panel-close" data-close-date aria-label="Close">&times;</button>
      <p class="mini-heading">${task.due_on ? 'Postpone or change the date' : stand === 'suggested' ? 'Confirm or change the date' : 'Set a date'}</p>
      <h3 id="datePickerTitle">${escapeHtml(task.text)}</h3>
      <p class="muted small">${escapeHtml(now)}</p>
      ${stand === 'suggested' ? `<button type="button" class="date-confirm" data-confirm-date>Confirm ${escapeHtml(L.formatDay(day))}</button>` : ''}
      <div class="chips date-quick">${choices.map(choice => `
        <button type="button" class="chip" data-pick-date="${choice.iso}">${escapeHtml(choice.label)} · ${escapeHtml(L.formatDay(choice.iso))}</button>`).join('')}</div>
      <div class="month">
        <div class="month-head">
          <button type="button" class="month-nav" data-picker-month="-1" aria-label="Previous month">‹</button>
          <span class="month-title" aria-live="polite">${escapeHtml(grid.title)}</span>
          <button type="button" class="month-nav" data-picker-month="1" aria-label="Next month">›</button>
        </div>
        <div class="month-grid" role="grid" aria-label="${escapeHtml(grid.title)}">
          <div class="month-row month-weekdays" role="row">${['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(name => `<span role="columnheader">${name}</span>`).join('')}</div>
          ${grid.weeks.map(week => `<div class="month-row" role="row">${week.map(cell => {
            const marks = [cell.iso === today ? 'today' : '', cell.iso === task.suggested_due_on ? 'suggested' : ''].filter(Boolean);
            return `<button type="button" role="gridcell" class="month-day${cell.inMonth ? '' : ' is-other'}${cell.iso === today ? ' is-today' : ''}${cell.iso === view.selected ? ' is-selected' : ''}${cell.iso === task.suggested_due_on ? ' is-suggested' : ''}"
              data-picker-day="${cell.iso}" aria-pressed="${cell.iso === view.selected}" tabindex="${cell.iso === view.selected ? 0 : -1}"
              aria-label="${escapeHtml(L.formatDay(cell.iso))}${marks.length ? `, ${marks.join(', ')}` : ''}">${cell.day}</button>`;
          }).join('')}</div>`).join('')}
        </div>
        ${task.suggested_due_on ? '<p class="muted small month-legend"><span class="legend-ring" aria-hidden="true"></span> suggested day</p>' : ''}
      </div>
      <div class="date-time">${view.showTime
        ? `<label>Time <input id="datePickerTime" type="time" value="${escapeHtml(view.time)}" /></label>
           <button type="button" class="link-btn small" data-picker-notime>All day</button>`
        : '<button type="button" class="link-btn small" data-picker-time>Add a time</button><span class="muted small"> · otherwise all day</span>'}</div>
      <div class="date-picker-actions">
        <button type="button" data-save-date>Save ${escapeHtml(L.formatDay(view.selected))}</button>
        <button type="button" class="secondary" data-close-date>Cancel</button>
      </div>`;
    const timeInput = $('datePickerTime');
    if (timeInput) timeInput.addEventListener('input', () => { view.time = timeInput.value; });
    if (focusSelected) {
      const cell = picker.querySelector('.month-day.is-selected');
      if (cell) cell.focus();
    }
  }

  function pickDay(iso) {
    const view = state.datePicker;
    if (!view || !iso) return;
    view.selected = iso;
    if (iso.slice(0, 7) !== view.month.slice(0, 7)) view.month = iso;
    drawDatePicker(true);
  }

  function pickerKeys(event) {
    const cell = event.target instanceof Element ? event.target.closest('.month-day') : null;
    if (!cell || !state.datePicker) return;
    const step = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7}[event.key];
    if (!step) return;
    event.preventDefault();
    pickDay(L.addDays(cell.dataset.pickerDay, step));
  }

  function placeDatePicker(picker, anchor) {
    // Phones: a sheet from the bottom. Wide screens: next to the chip you
    // clicked, or in the middle when it opens from a question (no chip).
    if (window.matchMedia('(max-width: 900px)').matches) {
      picker.classList.add('is-sheet');
      picker.style.left = '';
      picker.style.top = '';
      return;
    }
    picker.classList.remove('is-sheet');
    const width = picker.offsetWidth;
    const height = picker.offsetHeight;
    if (!anchor || !document.contains(anchor)) {
      picker.style.left = `${Math.round(Math.max(8, (window.innerWidth - width) / 2))}px`;
      picker.style.top = `${Math.round(Math.max(8, (window.innerHeight - height) / 2))}px`;
      return;
    }
    const box = anchor.getBoundingClientRect();
    const left = Math.max(8, Math.min(box.left, window.innerWidth - width - 8));
    let top = box.bottom + 8;
    if (top + height > window.innerHeight - 8) top = Math.max(8, box.top - height - 8);
    picker.style.left = `${Math.round(left)}px`;
    picker.style.top = `${Math.round(top)}px`;
  }

  function closeDatePicker({restoreFocus = true, next = true} = {}) {
    state.scoutDate = null;
    const picker = $('datePicker');
    if (!picker || picker.hidden) return false;
    picker.hidden = true;
    picker.classList.remove('is-question');
    picker.removeAttribute('aria-modal');
    picker.removeAttribute('aria-describedby');
    $('datePickerBackdrop').hidden = true;
    const view = state.datePicker;
    state.datePicker = null;
    const back = view && (view.ask ? view.returnFocus : view.anchor);
    if (restoreFocus && back && document.contains(back) && back !== document.body) back.focus();
    // Then the next date waiting for your OK, after a short pause.
    if (next && dateQuestions.length) setTimeout(askNextDate, 350);
    return true;
  }

  async function saveTaskDate(isoDay, time) {
    const current = state.datePicker;
    if (!current || !isoDay) return;
    const scout = state.scoutDate;
    if (scout && scout.taskId === current.task.id) {
      // Scout's "Not yet, new date": its answer sets the date and remembers it (018).
      state.scoutDate = null;
      closeDatePicker();
      await scoutAnswer(scout.questionId, 'reschedule', time ? {due_on: isoDay, due_time: time} : {due_on: isoDay});
      return;
    }
    await saveDateFor(current.task, isoDay, time);
  }

  async function saveDateFor(task, isoDay, time) {
    try {
      await api(`/api/tasks/${task.id}/date`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(time ? {due_on: isoDay, due_time: time} : {due_on: isoDay}),
      });
      closeDatePicker();
      const when = `${L.formatDay(isoDay)}${time ? ` at ${time}` : ''}`;
      const was = task.due_on;
      const verb = !was
        ? (task.suggested_due_on === isoDay ? 'Confirmed' : 'Set for')
        : isoDay > was || (isoDay === was && time > (task.due_time || '')) ? 'Postponed to' : isoDay === was ? 'Confirmed' : 'Moved to';
      const source = (task.source_item_ids || [])[0];
      showToast(`${verb} ${when}. The note keeps this in its updates.`,
        source ? {actions: [{label: 'Open note', run: () => openNote(source)}]} : {});
      reloadV1Lists();
      changed();
    } catch (error) {
      const picker = $('datePicker');
      const status = picker && picker.querySelector('.date-picker-error');
      if (picker && !picker.hidden && !status) {
        picker.insertAdjacentHTML('beforeend', `<p class="status error date-picker-error">${escapeHtml(error.message || 'Could not save the date.')}</p>`);
      } else if (!picker || picker.hidden) {
        showToast(error.message || 'Could not save the date.');
      }
    }
  }

  // --- The date question ----------------------------------------------------------------
  // A guessed date, or one your edit moved, needs your OK. It used to be a toast
  // at the bottom, which was easy to miss; now it's a card in the middle of a
  // dimmed page: "Is this the right day?" · Yes · Pick another day · Ask me
  // later. Several wait their turn. A guess left for later stays in Captain's
  // card on Home ("A date waits for your OK · Check it") until you answer.
  function queueDateQuestion(question) {
    if (dateQuestions.some(other => other.taskId === question.taskId)) return;
    if (state.datePicker && state.datePicker.ask && state.datePicker.taskId === question.taskId) return;
    dateQuestions.push(question);
    if (!state.datePicker) askNextDate();
    else showQuestionsLeft();
  }

  let askingDate = false;
  async function askNextDate() {
    if (askingDate) return;
    askingDate = true;
    try {
      while (dateQuestions.length && !state.datePicker) {
        const question = dateQuestions.shift();
        if (await openDatePicker(question.taskId, null, question)) break;
      }
    } finally {
      askingDate = false;
    }
  }

  /** Still worth asking: the guess is still a guess, or the moved date still waits. */
  function stillToAsk(task, ask) {
    if (!task || task.status !== 'open') return false;
    if (ask.kind === 'moved') return !task.timing_confirmed && L.taskDay(task) === ask.to;
    return L.dateState(task) === 'suggested';
  }

  function questionsLeftText() {
    const left = dateQuestions.length;
    if (!left) return '';
    return left === 1 ? 'One more date to check after this.' : `${left} more dates to check after this.`;
  }

  function showQuestionsLeft() {
    const line = $('dateAskLeft');
    if (!line) return;
    line.textContent = questionsLeftText();
    line.hidden = !dateQuestions.length;
  }

  function drawDateQuestion(view, picker) {
    const {task, ask} = view;
    const moved = ask.kind === 'moved';
    const day = moved ? L.taskDay(task) : task.suggested_due_on;
    const time = (task.due_on ? task.due_time : task.suggested_due_time) || '';
    const page = L.dayParts(day) || {month: '', day: '', weekdayLong: ''};
    const when = `${L.formatDay(day)}${time ? ` · ${time}` : ''}`;
    // The words the date was read from; offline they can be the whole sentence.
    const ownWords = task.timing_text && task.timing_text.trim().toLowerCase() !== String(task.text || '').trim().toLowerCase();
    const why = moved
      ? `Your edit moved it${ask.from ? ` from ${L.formatDay(ask.from)}${ask.fromTime ? ` at ${ask.fromTime}` : ''}` : ''} to ${when}.`
      : ownWords ? `You wrote “${L.clip(task.timing_text, 60)}”.` : 'Read from your note.';
    picker.setAttribute('aria-describedby', 'dateAskWhy');
    picker.innerHTML = `
      <p class="date-ask-band">${icon('calendar', 16)}<span>${moved ? 'Your edit moved a date' : 'Is this the right day?'}</span></p>
      <div class="date-ask-body">
        <div class="date-ask-page" aria-hidden="true">
          <span class="date-ask-month">${escapeHtml(page.month)}</span>
          <span class="date-ask-num">${escapeHtml(String(page.day))}</span>
          <span class="date-ask-dow">${escapeHtml(page.weekdayLong)}</span>
        </div>
        <div class="date-ask-text">
          <h3 id="datePickerTitle">${escapeHtml(task.text)}</h3>
          <p id="dateAskWhy">${escapeHtml(why)}</p>
          <p class="muted small">${moved ? 'Say yes to keep it, or pick the right day.' : 'It goes on your calendar once you say yes.'}</p>
        </div>
      </div>
      <div class="date-ask-actions">
        <button type="button" class="date-ask-yes" data-ask-yes>Yes, ${escapeHtml(when)}</button>
        <div class="date-ask-more">
          <button type="button" class="secondary" data-ask-change>Pick another day</button>
          <button type="button" class="link-btn" data-ask-later>Ask me later</button>
        </div>
      </div>
      <p id="dateAskLeft" class="muted small date-ask-left"${dateQuestions.length ? '' : ' hidden'}>${escapeHtml(questionsLeftText())}</p>`;
  }

  function answerDateQuestion() {
    const view = state.datePicker;
    if (!view || !view.ask) return;
    const {task} = view;
    const day = view.ask.kind === 'moved' ? L.taskDay(task) : task.suggested_due_on;
    saveDateFor(task, day, (task.due_on ? task.due_time : task.suggested_due_time) || '');
  }

  function expandDateQuestion() {
    const view = state.datePicker;
    if (!view || !view.ask) return;
    view.expanded = true;
    drawDatePicker();
    const picker = $('datePicker');
    placeDatePicker(picker, null);
    const cell = picker.querySelector('.month-day.is-selected');
    if (cell) cell.focus();
  }

  // A question is modal: Tab and Shift+Tab stay inside it.
  function trapDateFocus(event) {
    if (event.key !== 'Tab' || !state.datePicker || !state.datePicker.ask) return;
    const picker = $('datePicker');
    const items = [...picker.querySelectorAll('button, input')]
      .filter(item => !item.disabled && item.tabIndex >= 0 && item.getClientRects().length);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    const inside = picker.contains(document.activeElement) && document.activeElement !== picker;
    if (!inside || (event.shiftKey && document.activeElement === first) || (!event.shiftKey && document.activeElement === last)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    }
  }

  // After you edit a note: if the new text moved a date you had confirmed, the
  // question asks you to confirm the new one (or change it) once it's re-filed.
  const editedNotes = new Map();
  async function askAboutMovedDates(itemId) {
    const since = editedNotes.get(itemId);
    if (!since) return;
    editedNotes.delete(itemId);
    const updates = await api(`/api/items/${itemId}/updates`).catch(() => []);
    const moved = updates.filter(update => update.kind === 'note_edit' && update.needs_confirmation
      && new Date(update.created_at).getTime() >= since - 5000);
    for (const update of moved) {
      queueDateQuestion({kind: 'moved', taskId: update.task_id, to: update.to_due_on, from: update.from_due_on, fromTime: update.from_due_time});
    }
  }

  // Right after you save a note: each guessed date gets the question; a day
  // your words named just says where it went ("Added for Thu 12 Nov · Change").
  const capturedNotes = new Set();
  async function askAboutNewDates(itemId) {
    if (!capturedNotes.has(itemId)) return;
    capturedNotes.delete(itemId);
    const tasks = (await api('/api/tasks?status=open').catch(() => []))
      .filter(task => (task.source_item_ids || []).includes(itemId));
    const guesses = L.waitingDates(tasks);
    const named = tasks.find(task => L.dateState(task) === 'note');
    if (guesses.length) {
      for (const task of guesses) queueDateQuestion({kind: 'new', taskId: task.id});
    } else if (named) {
      showToast(`Added for ${L.formatDay(named.due_on)}${named.due_time ? ` at ${named.due_time}` : ''}.`, {
        actions: [{label: 'Change', run: () => openDatePicker(named.id, null)}],
      });
    }
  }

  // --- Capture from anywhere (change 011a) -----------------------------------------------
  // Home keeps the composer at the top. Elsewhere it stays out of the way: "+ New
  // note" in the header, the N key, or the "+" button on phones opens the same
  // composer as a panel over the view, and saving closes it with "Saved · Open".
  function captureIsFloating() {
    return $('captureCard').classList.contains('is-floating');
  }

  function openCapture() {
    closeHover();
    if (state.view === 'home') {
      $('centerPane').scrollTop = 0;
      $('noteText').focus();
      return;
    }
    const card = $('captureCard');
    if (!captureIsFloating()) {
      state.captureReturnFocus = document.activeElement;
      card.classList.add('is-floating');
      card.setAttribute('role', 'dialog');
      card.setAttribute('aria-label', 'New note');
      $('captureBackdrop').hidden = false;
      if (!$('addNoteButton').disabled) $('noteStatus').textContent = '';
    }
    $('noteText').focus();
  }

  function closeCapture({restoreFocus = true} = {}) {
    const card = $('captureCard');
    if (!captureIsFloating()) return false;
    card.classList.remove('is-floating');
    card.removeAttribute('role');
    card.removeAttribute('aria-label');
    $('captureBackdrop').hidden = true;
    const back = state.captureReturnFocus;
    state.captureReturnFocus = null;
    if (restoreFocus) {
      if (back && document.contains(back) && back !== document.body) back.focus();
      else $('newNoteButton').focus();
    }
    return true;
  }

  let toastTimer = 0;
  function showToast(text, {action, onAction, actions, sticky = false} = {}) {
    const toast = $('toast');
    const list = actions || (action && onAction ? [{label: action, run: onAction}] : []);
    toast.innerHTML = `<span>${escapeHtml(text)}</span>${list.map((item, index) => `<button type="button" class="toast-action" data-toast-action="${index}">${escapeHtml(item.label)}</button>`).join('')}${sticky ? '<button type="button" class="toast-action toast-close" data-toast-close aria-label="Dismiss">&times;</button>' : ''}`;
    toast.hidden = false;
    for (const button of toast.querySelectorAll('[data-toast-action]')) {
      button.addEventListener('click', () => {
        toast.hidden = true;
        list[Number(button.dataset.toastAction)].run();
      });
    }
    const close = toast.querySelector('[data-toast-close]');
    if (close) close.addEventListener('click', () => { toast.hidden = true; });
    clearTimeout(toastTimer);
    if (!sticky) toastTimer = setTimeout(() => { toast.hidden = true; }, 7000);
  }

  function isTyping(target) {
    return target instanceof Element
      && (target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]') !== null);
  }

  // --- Hover cards: a topic's count and description, a note's first lines (change 011a) ---
  const hoverState = {timer: 0, target: null};
  const noteCache = new Map();

  function closeHover() {
    clearTimeout(hoverState.timer);
    const card = $('hoverCard');
    if (card) card.hidden = true;
    if (hoverState.target) hoverState.target.removeAttribute('aria-describedby');
    hoverState.target = null;
  }

  function topicHoverHtml(info) {
    return `<b>${escapeHtml(info.name)}</b><span class="muted small"> · ${escapeHtml(info.area)}</span>
      <p class="hover-count">${escapeHtml(info.count)}</p>
      ${info.description ? `<p>${escapeHtml(info.description)}</p>` : '<p class="muted">No description yet.</p>'}
      ${info.subtopics.length ? `<p class="muted small">Subtopics: ${escapeHtml(info.subtopics.join(', '))}</p>` : ''}
      <p class="muted small">${info.builtIn ? 'Built in · ' : ''}Click to open</p>`;
  }

  function noteHoverHtml(info) {
    return `<div class="hover-meta"><span class="chip">${escapeHtml(typeLabel(info.kind))}</span>${info.savedOn ? `<span class="muted small">Saved ${escapeHtml(info.savedOn)}</span>` : ''}</div>
      ${info.title ? `<b>${escapeHtml(info.title)}</b>` : ''}
      ${info.note ? `<p class="hover-note">Your note: ${escapeHtml(info.note)}</p>` : ''}
      ${info.excerpt ? `<p${info.title ? ' class="muted"' : ''}>${escapeHtml(info.excerpt)}</p>` : ''}
      ${info.failed ? '<p class="status error">This capture couldn\'t be read.</p>' : ''}
      <p class="muted small">Click to open</p>`;
  }

  function placeHover(card, target) {
    const box = target.getBoundingClientRect();
    card.hidden = false;
    const width = card.offsetWidth;
    const height = card.offsetHeight;
    const gap = 10;
    let left = box.right + gap;
    if (left + width > window.innerWidth - 8) left = box.left - gap - width;
    if (left < 8) left = Math.min(Math.max(8, box.left), window.innerWidth - width - 8);
    let top = left === box.right + gap || left === box.left - gap - width ? box.top : box.bottom + gap;
    top = Math.max(8, Math.min(top, window.innerHeight - height - 8));
    card.style.left = `${Math.round(left)}px`;
    card.style.top = `${Math.round(top)}px`;
  }

  async function showHover(target) {
    const card = $('hoverCard');
    if (!card || hoverState.target !== target || !document.contains(target)) return;
    let html = '';
    if (target.dataset.openTopic) {
      const info = L.topicHover(state.topicsById[Number(target.dataset.openTopic)], state.topics, state.botsByKey);
      if (info) html = topicHoverHtml(info);
    } else if (target.dataset.openNote) {
      const id = Number(target.dataset.openNote);
      let item = noteCache.get(id);
      if (!item) {
        item = await api(`/api/items/${id}`).catch(() => null);
        if (item) noteCache.set(id, item);
      }
      if (hoverState.target !== target) return;
      const info = L.notePreview(item);
      if (info) html = noteHoverHtml(info);
    }
    if (!html) return;
    card.innerHTML = html;
    placeHover(card, target);
    target.setAttribute('aria-describedby', 'hoverCard');
  }

  function hoverTargetOf(element) {
    if (!(element instanceof Element) || element.closest('#hoverCard, #noteSheet')) return null;
    return element.closest('[data-open-topic], [data-open-note]');
  }

  function watchHoverCards() {
    const startHover = target => {
      if (target === hoverState.target) return;
      closeHover();
      if (!target) return;
      hoverState.target = target;
      hoverState.timer = setTimeout(() => showHover(target), 350);
    };
    // Mouse users get the card on hover; keyboard users when they tab to a link.
    if (window.matchMedia('(hover: hover)').matches) {
      document.addEventListener('mouseover', event => startHover(hoverTargetOf(event.target)));
    }
    document.addEventListener('focusin', event => {
      const target = hoverTargetOf(event.target);
      if (target && target.matches(':focus-visible')) startHover(target);
      else if (!target) closeHover();
    });
    document.addEventListener('scroll', closeHover, true);
    document.addEventListener('pointerdown', closeHover);
    window.addEventListener('blur', closeHover);
  }

  // --- the note page: one page for a note, opened from everywhere ---------------------------
  function orderedTopics(topics) {
    const ids = new Set(topics.map(topic => topic.id));
    const mains = topics
      .filter(topic => !topic.parent_topic_id || !ids.has(topic.parent_topic_id))
      .sort((first, second) => first.name.localeCompare(second.name));
    return mains.flatMap(main => [main, ...topics
      .filter(topic => topic.parent_topic_id === main.id)
      .sort((first, second) => first.name.localeCompare(second.name))]);
  }

  function topicOptions(selectedId) {
    const groups = state.bots.map(bot => ({
      label: bot.name,
      topics: state.topics.filter(topic => topic.bot_key === bot.key),
    }));
    groups.push({label: 'Not in an area', topics: state.topics.filter(topic => !topic.bot_key)});
    return groups.filter(group => group.topics.length).map(group => `
      <optgroup label="${escapeHtml(group.label)}">${orderedTopics(group.topics).map(topic => `
        <option value="${topic.id}"${topic.id === selectedId ? ' selected' : ''}>${topic.parent_topic_id ? '↳ ' : ''}${escapeHtml(topic.name)}</option>`).join('')}
      </optgroup>`).join('');
  }

  // What code read from a saved link (change 015): text only, no pictures or
  // players (decision I). Not AI output.
  function linkCard(card) {
    const facts = card.facts || {};
    const kind = {video: 'Video', recipe: 'Recipe', article: 'Article', event: 'Event', page: 'Page'}[card.kind] || 'Page';
    const lines = [
      card.channel ? `Channel: ${card.channel}` : '',
      card.site ? `Site: ${card.site}` : '',
      card.published ? `Published: ${card.published}` : '',
      facts.author ? `By: ${facts.author}` : '',
      facts.when ? `When: ${facts.when}${facts.ends ? ` to ${facts.ends}` : ''}` : '',
      facts.where ? `Where: ${facts.where}` : '',
      facts.time ? `Time: ${facts.time}` : '',
      facts.yield ? `Makes: ${facts.yield}` : '',
    ].filter(Boolean);
    return `<div class="link-card">
      <p class="muted small">${escapeHtml(kind)} · read from the page, not by AI</p>
      ${lines.length ? `<p class="small">${lines.map(escapeHtml).join(' · ')}</p>` : ''}
      ${facts.ingredients && facts.ingredients.length ? `<p class="small"><b>Ingredients</b></p><ul class="small">${facts.ingredients.map(i => `<li>${escapeHtml(i)}</li>`).join('')}</ul>` : ''}
      ${facts.steps && facts.steps.length ? `<p class="small"><b>Steps</b></p><ol class="small">${facts.steps.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ol>` : ''}
      ${card.description ? `<p>${escapeHtml(card.description)}</p>` : ''}
      ${card.limited ? '<p class="muted small">Limited preview: only the title could be read.</p>' : ''}
    </div>`;
  }

  function sourceSection(item) {
    const parts = [];
    if (item.item_type === 'url' && item.source_url) {
      parts.push(`<p><a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title || item.source_url)}</a></p>`);
      if (item.link_card) parts.push(linkCard(item.link_card));
    }
    if (item.item_type === 'image') {
      parts.push(`<img class="sheet-thumb" src="/api/items/${item.id}/file?variant=thumb" alt="${escapeHtml(item.original_filename || 'Saved image')}" />`);
    }
    if (['pdf', 'image', 'voice'].includes(item.item_type) && item.original_filename) {
      parts.push(`<p class="muted">${escapeHtml(item.original_filename)} · <a href="/api/items/${item.id}/file" target="_blank" rel="noopener">Open file</a></p>`);
    }
    const text = item.item_type === 'text' ? item.raw_text : (item.extracted_text || item.raw_text);
    if (text) {
      const shown = text.length > 1600 ? `${text.slice(0, 1600)}…` : text;
      parts.push(`<p class="source-text">${escapeHtml(shown)}</p>`);
    }
    if (item.processing_status === 'failed') {
      parts.push(`<p class="status error">This capture couldn't be read${item.error_message ? `: ${escapeHtml(item.error_message)}` : ''}.</p>`);
    }
    return parts.join('') || '<p class="muted">No text was saved with this note.</p>';
  }

  async function openNote(itemId, {keepFocus = false} = {}) {
    const id = Number(itemId);
    if (!id) return;
    const sheet = $('noteSheet');
    const body = $('noteSheetBody');
    if (sheet.hidden && !keepFocus) state.lastFocus = document.activeElement;
    if (!keepFocus || state.openNoteId !== id) state.sheetMessage = '';
    state.openNoteId = id;
    sheet.hidden = false;
    document.body.classList.add('sheet-open');
    if (!keepFocus) body.innerHTML = '<p class="muted">Opening the note…</p>';
    const token = ++noteToken;
    let item;
    try {
      item = await api(`/api/items/${id}`);
    } catch {
      if (token === noteToken) body.innerHTML = '<h2 id="noteSheetTitle">Note not found</h2><p class="muted">It may have been deleted.</p>';
      return;
    }
    const [insight, tasks, relations, updates, ideas] = await Promise.all([
      api(`/api/items/${id}/insight`).catch(() => null),
      api('/api/tasks?status=all').catch(() => []),
      api('/api/relations').catch(() => []),
      api(`/api/items/${id}/updates`).catch(() => []),
      api(`/api/items/${id}/ideas`).catch(() => []),
    ]);
    if (!state.topics.length) await refreshTopics();
    const relatedIds = relations
      .filter(rel => !rel.dismissed && (rel.item_id_a === id || rel.item_id_b === id))
      .map(rel => (rel.item_id_a === id ? rel.item_id_b : rel.item_id_a))
      .filter((value, index, all) => all.indexOf(value) === index)
      .slice(0, 5);
    const related = (await Promise.all(relatedIds.map(other => api(`/api/items/${other}`).catch(() => null))))
      .filter(Boolean);
    if (token !== noteToken) return;

    const topicId = insight && insight.effective_topic_id;
    const crumbs = L.breadcrumb(topicId, state.topicsById, state.botsByKey);
    const secret = Boolean(item.secret_masked);
    const revealed = secret && state.revealed.has(id);
    const view = revealed ? item : L.shown(item);
    const ownTasks = tasks.filter(task => (task.source_item_ids || []).includes(id));
    const openTasks = ownTasks.filter(task => task.status === 'open');
    const dates = ownTasks.filter(task => task.due_on).map(task => task.due_on).sort();
    const priority = insight ? insight.effective_priority : null;
    const movedByYou = Boolean(insight && insight.user_topic_id && insight.user_topic_id !== insight.topic_id);
    const aiTopic = insight && state.topicsById[insight.topic_id];
    let why;
    if (!insight) {
      why = '<span class="muted">Not organized yet.</span>';
    } else if (movedByYou) {
      why = `You moved it here.${insight.rationale
        ? ` <span class="muted">Life Inbox first filed it${aiTopic ? ` under ${escapeHtml(aiTopic.name)}` : ''}: ${escapeHtml(insight.rationale)}</span>`
        : ''}`;
    } else if (insight.filing_pending) {
      why = 'Life Inbox wasn\'t sure where this goes, so it doesn\'t guess: Captain asks you in “Needs you”.';
    } else {
      why = insight.rationale ? escapeHtml(insight.rationale) : '<span class="muted">No reason was saved.</span>';
    }
    // What memory added (change 017): the hints the filing call said it used.
    const remembered = insight && !movedByYou && (insight.memory_used || []).length
      ? `<p class="muted small">It also used what it remembered: ${insight.memory_used
          .map(hint => `“${escapeHtml(hint.text)}”`).join(', ')}. <a href="#/memory">What I learned</a></p>`
      : '';
    // How it was filed (change 014): the rule that decided, and who filed it.
    const filedBy = insight ? ({ai: 'Filed by AI', offline: 'Filed without AI', you: 'Filed by you'})[insight.filed_by] : null;
    const how = insight && !movedByYou && (insight.filing_rule || filedBy)
      ? `<p class="muted small">${[insight.filing_rule ? `Rule ${escapeHtml(insight.filing_rule)}` : '', filedBy || '',
          insight.filing_confidence && insight.filed_by !== 'you' ? `${escapeHtml(insight.filing_confidence)} confidence` : '']
          .filter(Boolean).join(' · ')}</p>`
      : '';
    const added = (insight && (insight.ai_summary || insight.suggested_action || insight.cleaned_transcript)) || item.source_summary
      ? `<section class="sheet-section"><h3>What the AI added</h3>
          ${item.source_summary ? `<p class="muted small">Summary of the whole document (AI, made once when you saved it):</p><p>${escapeHtml(item.source_summary)}</p>` : ''}
          ${insight && insight.ai_summary ? `<p>${escapeHtml(insight.ai_summary)}</p>` : ''}
          ${insight && insight.suggested_action ? `<p><span class="chip">${escapeHtml(insight.suggested_action)}</span></p>` : ''}
          ${insight && insight.cleaned_transcript ? `<p class="muted small">Tidied transcript (AI):</p><p>${escapeHtml(insight.cleaned_transcript)}</p>` : ''}
          <p class="muted small">AI output, kept apart from your words and the source.</p></section>`
      : '';

    body.innerHTML = `
      <nav class="breadcrumb" aria-label="Where this note is filed">${crumbs.length
        ? crumbs.map(part => (part.kind === 'bot'
          ? `<button type="button" class="crumb" data-set-lens="${escapeHtml(part.key)}">${escapeHtml(part.label)}</button>`
          : `<button type="button" class="crumb" data-open-topic="${part.id}">${escapeHtml(part.label)}</button>`)).join('<span aria-hidden="true">›</span>')
        : `<span class="muted">${insight && insight.filing_pending ? 'Waiting for your pick' : 'Not filed yet'}</span>`}</nav>
      <h2 id="noteSheetTitle">${escapeHtml(itemTitle(item, insight))}</h2>
      <div class="chips">
        <span class="chip">${escapeHtml(typeLabel(item.item_type))}</span>
        ${priority ? `<span class="pri pri-${escapeHtml(priority.toLowerCase())}">${escapeHtml(priority)}</span>` : ''}
        ${dates.length ? `<span class="chip">${escapeHtml(L.formatDay(dates[0]))}</span>` : ''}
      </div>
      ${secret ? `<p class="secret-note">${icon('lock', 16)}<span>${revealed
        ? 'Showing the secret. It still never goes to the AI.'
        : 'This note looks like it holds a secret, so it\'s hidden here. It never goes to the AI or into memory.'}</span>
        <button type="button" class="link-btn small" data-reveal-secret="${id}">${revealed ? 'Hide' : 'Show'}</button></p>` : ''}
      ${item.item_type !== 'text' && state.editingContext === id
        ? `<section class="sheet-section"><h3>Your note</h3><form class="need-note" data-context-form="${id}">
            <label class="muted small" for="contextText">Why you saved it, in your words. Saving files it again from them.</label>
            <textarea id="contextText" rows="3" maxlength="2000">${escapeHtml(item.user_context || '')}</textarea>
            <div class="need-actions"><button type="submit" class="small-btn">Save note</button>
            <button type="button" class="small-btn secondary" data-context-cancel>Cancel</button></div></form></section>`
        : view.user_context
          ? `<section class="sheet-section"><h3>Your note</h3><p class="user-note">${escapeHtml(view.user_context)}</p>
              ${item.item_type !== 'text' ? `<button type="button" class="link-btn small" data-context-edit="${id}">Edit note</button>` : ''}</section>`
          : item.item_type !== 'text'
            ? `<section class="sheet-section"><h3>Your note</h3><button type="button" class="link-btn small" data-context-edit="${id}">Add a note: why you saved it</button></section>`
            : ''}
      <section class="sheet-section"><h3>Source</h3>${sourceSection(view)}</section>
      ${added}
      <section class="sheet-section"><h3>Why it's here</h3>
        <p>${why}</p>
        ${remembered}
        ${how}
        ${insight && insight.effective_tags && insight.effective_tags.length ? `<div class="chips">${insight.effective_tags.map(tag => `<span class="chip chip-muted">${escapeHtml(tag)}</span>`).join('')}</div>` : ''}
      </section>
      <section class="sheet-section"><h3>Tasks from this note</h3><div id="noteSheetTasks">${ownTasks.length ? '' : '<p class="muted">No tasks.</p>'}</div></section>
      ${ideas.length ? `<section class="sheet-section"><h3>Ideas, not tasks yet</h3><ul class="updates">${ideas.map(idea => `
        <li><span class="chip ${idea.intent === 'someday' ? 'chip-muted' : 'chip-dashed'}">${idea.intent === 'someday' ? 'Someday' : 'Maybe'}</span>
          ${escapeHtml(idea.text)}${idea.timing_text ? `<span class="muted small"> · ${escapeHtml(idea.timing_text)}</span>` : ''}
          <button type="button" class="link-btn small" data-idea-add="${idea.id}">Add as task</button></li>`).join('')}</ul>
        <p class="muted small">Things you might do. They stay off your calendar and lists until you add them.</p></section>` : ''}
      ${updates.length ? `<section class="sheet-section"><h3>Updates</h3><ul class="updates">${updates.map(update => `
        <li>${escapeHtml(update.text)}<span class="muted small"> · ${escapeHtml(savedOn(update.created_at))}</span>${update.needs_confirmation ? ' <span class="chip chip-dashed">waiting for your OK</span>' : ''}</li>`).join('')}</ul></section>` : ''}
      <section class="sheet-section"><h3>Related</h3>${related.length
        ? related.map(other => `<button type="button" class="row-link block" data-open-note="${other.id}">${escapeHtml(itemTitle(other))}</button>`).join('')
        : '<p class="muted">Nothing related yet.</p>'}</section>
      <div class="sheet-actions">
        ${openTasks.length ? `<button type="button" id="noteMarkDone">Mark its tasks done</button>` : ''}
        <label class="move-topic">${topicId ? 'Move to topic' : 'Put it in a topic'}
          <select id="noteMoveTopic"${insight ? '' : ' disabled'}>${topicId ? '' : '<option value="" selected disabled>Pick a topic…</option>'}${topicOptions(topicId)}</select>
        </label>
        <button type="button" class="secondary" id="noteShowInList">Show in All notes</button>
      </div>
      <p id="noteSheetStatus" class="status muted" role="status" aria-live="polite">${escapeHtml(state.sheetMessage || (insight ? '' : 'Organize this note first to move it to a topic.'))}</p>`;

    const taskRoot = $('noteSheetTasks');
    if (typeof renderTask === 'function') {
      for (const task of ownTasks) taskRoot.appendChild(renderTask(task));
    }
    // A note is just kept; only a note with open tasks can be "done" (its tasks).
    if (openTasks.length) $('noteMarkDone').addEventListener('click', () => markDone(id));
    $('noteMoveTopic').addEventListener('change', event => moveToTopic(id, Number(event.target.value)));
    $('noteShowInList').addEventListener('click', () => showInAllNotes(id));
    if (!keepFocus) body.closest('.sheet-panel').querySelector('.sheet-close').focus();
  }

  async function saveContext(id) {
    const text = $('contextText').value.trim();
    const button = document.querySelector('[data-context-form] button[type="submit"]');
    if (button) { button.disabled = true; button.textContent = 'Saving and filing…'; }
    try {
      const result = await api(`/api/items/${id}/context`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({context: text || null})});
      state.editingContext = null;
      showToast(result.refiled ? 'Saved. Filed again from your words.' : 'Saved. It will be filed from your words next time.');
      noteCache.delete(id);
      reloadV1Lists();
      changed();
      openNote(id, {keepFocus: true});
    } catch (error) {
      showToast(error.message || 'Could not save your note.');
      if (button) { button.disabled = false; button.textContent = 'Save note'; }
    }
  }

  function editNoteContext(id) {
    state.editingContext = Number(id);
    openNote(id).then(() => { if ($('contextText')) $('contextText').focus(); });
  }

  function closeSheet() {
    const sheet = $('noteSheet');
    if (!sheet || sheet.hidden) return;
    sheet.hidden = true;
    state.openNoteId = null;
    state.revealed.clear();
    state.editingContext = null;
    document.body.classList.remove('sheet-open');
    if (state.lastFocus && document.contains(state.lastFocus)) state.lastFocus.focus();
  }

  // After a change made here, the v1 lists reload too (app.js reloads its own).
  function reloadV1Lists() {
    if (typeof loadTasks === 'function') loadTasks();
    if (typeof loadNotes === 'function') loadNotes();
    if (typeof loadCalendarEvents === 'function') loadCalendarEvents();
  }

  async function markDone(id) {
    try {
      await api(`/api/items/${id}/complete`, {method: 'POST'});
      state.sheetMessage = 'Marked done. Its tasks leave your open lists.';
      $('noteSheetStatus').textContent = state.sheetMessage;
      reloadV1Lists();
      changed();
    } catch (error) {
      $('noteSheetStatus').textContent = error.message || 'Could not mark it done.';
    }
  }

  async function moveToTopic(id, topicId) {
    try {
      await api(`/api/items/${id}/insight`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_topic_id: topicId}),
      });
      const topic = state.topicsById[topicId];
      state.sheetMessage = `Moved to ${topic ? topic.name : 'that topic'}.`;
      $('noteSheetStatus').textContent = state.sheetMessage;
      reloadV1Lists();
      changed();
    } catch (error) {
      $('noteSheetStatus').textContent = error.message || 'Could not move the note.';
    }
  }

  function showInAllNotes(id) {
    closeSheet();
    goTo('topics');
    if (typeof v1JumpToSourceNote === 'function') v1JumpToSourceNote(id);
  }

  // --- the calendar preview dock (v1 previews show wherever they start) ---------------------
  function watchCalendarPreview() {
    const dock = $('calendarDock');
    const preview = $('calendarPreview');
    const status = $('calendarStatus');
    if (!dock || !preview || !status) return;
    const sync = () => {
      dock.hidden = !preview.textContent.trim() && !status.textContent.trim();
    };
    const observer = new MutationObserver(sync);
    observer.observe(preview, {childList: true, subtree: true, characterData: true});
    observer.observe(status, {childList: true, subtree: true, characterData: true});
    $('calendarDockClose').addEventListener('click', () => {
      preview.innerHTML = '';
      status.textContent = '';
      sync();
    });
    sync();
  }

  // --- refresh after any change ----------------------------------------------------------------
  let refreshTimer = null;
  async function refresh() {
    await Promise.all([refreshBots(), refreshTopics(), refreshNeeds(), refreshScout()]);
    renderCurrentView();
    if (state.openNoteId && !$('noteSheet').hidden) openNote(state.openNoteId, {keepFocus: true});
  }

  // --- wiring ------------------------------------------------------------------------------------
  let v1JumpToSourceNote = null;

  function init() {
    // Every "jump to the source note" in the v1 screens now opens the note page.
    if (typeof window.jumpToSourceNote === 'function') {
      v1JumpToSourceNote = window.jumpToSourceNote;
      window.jumpToSourceNote = itemId => openNote(itemId);
    }

    document.addEventListener('click', event => {
      // In-app links (#/timeline, #/topics, ...) go through goTo, not a hash navigation.
      const link = event.target.closest('a[href^="#/"]');
      if (link && event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
        event.preventDefault();
        // Captain's link means "everything": it also clears the lens.
        if (link.hasAttribute('data-clear-lens')) setLens(null);
        const route = L.routeFromHash(link.getAttribute('href'));
        goTo(route.view, route.query);
        return;
      }
      const ideaButton = event.target.closest('[data-idea-add]');
      if (ideaButton) {
        api(`/api/ideas/${ideaButton.dataset.ideaAdd}/add`, {method: 'POST'})
          .then(() => { showToast('Added as a task.'); changed(); if (state.openNoteId) openNote(state.openNoteId, {keepFocus: true}); })
          .catch(error => showToast(error.message || 'Could not add it.'));
        return;
      }
      if (event.target.closest('[data-welcome-skip]')) {
        api('/api/onboarding/skip', {method: 'POST'}).catch(() => null).then(() => goTo('home'));
        return;
      }
      const scoutButton = event.target.closest('[data-scout-action],[data-scout-reason],[data-scout-cancel],[data-scout-bulk],[data-scout-bulk-yes],[data-scout-bulk-cancel],[data-scout-finish],[data-someday-on],[data-someday-off]');
      if (scoutButton) {
        scoutClick(scoutButton);
        return;
      }
      const contextButton = event.target.closest('[data-context-edit],[data-context-cancel]');
      if (contextButton) {
        state.editingContext = contextButton.dataset.contextEdit ? Number(contextButton.dataset.contextEdit) : null;
        if (state.openNoteId) {
          openNote(state.openNoteId, {keepFocus: true}).then(() => { if ($('contextText')) $('contextText').focus(); });
        }
        return;
      }
      const memoryButton = event.target.closest('[data-memory-confirm],[data-memory-edit],[data-memory-delete],[data-memory-forget],[data-memory-cancel]');
      if (memoryButton) {
        memoryAction(memoryButton);
        return;
      }
      const reveal = event.target.closest('[data-reveal-secret]');
      if (reveal) {
        const id = Number(reveal.dataset.revealSecret);
        if (state.revealed.has(id)) state.revealed.delete(id);
        else state.revealed.add(id);
        openNote(id, {keepFocus: true}).then(() => { const again = document.querySelector('[data-reveal-secret]'); if (again) again.focus(); });
        return;
      }
      const needButton = event.target.closest('[data-need-action]');
      if (needButton) {
        answerNeed(needButton);
        return;
      }
      if (event.target.closest('[data-need-cancel]')) {
        state.needAnswer = null;
        renderHome();
        return;
      }
      const captureAction = event.target.closest('[data-new-note],[data-close-capture]');
      if (captureAction) {
        if (captureAction.dataset.newNote !== undefined) openCapture();
        else closeCapture();
        return;
      }
      const viewAction = event.target.closest('[data-timeline-mode],[data-timeline-shift],[data-timeline-today],[data-open-backlog],[data-close-day],[data-add-task],[data-close-add-task],[data-reset-priority],[data-date-task],[data-pick-date],[data-close-date],[data-confirm-date],[data-picker-day],[data-picker-month],[data-picker-time],[data-picker-notime],[data-save-date],[data-ask-yes],[data-ask-change],[data-ask-later]');
      if (viewAction) {
        const data = viewAction.dataset;
        if (data.timelineMode) setTimeline({mode: data.timelineMode});
        else if (data.timelineShift) {
          setTimeline({anchor: L.shiftAnchor(timeline.anchor || L.isoDate(new Date()), timeline.mode, Number(data.timelineShift))});
        } else if (data.timelineToday !== undefined) setTimeline({anchor: null});
        else if (data.openBacklog !== undefined) {
          goTo('priority');
          const backlog = $('priorityBacklog');
          backlog.open = true;
          setTimeout(() => backlog.scrollIntoView({block: 'start', behavior: 'smooth'}), 300);
        } else if (data.closeDay !== undefined) closeDayPopup();
        else if (data.addTask !== undefined) {
          $('addTaskPanel').hidden = false;
          $('quickTaskText').focus();
        } else if (data.closeAddTask !== undefined) {
          $('addTaskPanel').hidden = true;
          $('addTaskButton').focus();
        } else if (data.dateTask) openDatePicker(Number(data.dateTask), viewAction);
        else if (data.pickDate) saveTaskDate(data.pickDate, state.datePicker && state.datePicker.showTime ? state.datePicker.time : '');
        else if (data.closeDate !== undefined) closeDatePicker();
        else if (data.confirmDate !== undefined && state.datePicker) {
          const {task} = state.datePicker;
          saveDateFor(task, task.suggested_due_on, task.suggested_due_time);
        } else if (data.pickerDay) pickDay(data.pickerDay);
        else if (data.pickerMonth && state.datePicker) {
          state.datePicker.month = L.shiftAnchor(state.datePicker.month, 'month', Number(data.pickerMonth));
          drawDatePicker();
        } else if (data.pickerTime !== undefined && state.datePicker) {
          state.datePicker.showTime = true;
          drawDatePicker();
          if ($('datePickerTime')) $('datePickerTime').focus();
        } else if (data.pickerNotime !== undefined && state.datePicker) {
          Object.assign(state.datePicker, {showTime: false, time: ''});
          drawDatePicker();
        } else if (data.saveDate !== undefined && state.datePicker) {
          saveTaskDate(state.datePicker.selected, state.datePicker.showTime ? state.datePicker.time : '');
        }
        else if (data.askYes !== undefined) answerDateQuestion();
        else if (data.askChange !== undefined) expandDateQuestion();
        else if (data.askLater !== undefined) closeDatePicker();
        else if (data.resetPriority) setTaskPriority(Number(data.resetPriority), null);
        return;
      }
      const topicAction = event.target.closest('[data-new-topic],[data-close-new-topic],[data-topic-edit],[data-topic-edit-cancel],[data-topic-delete],[data-topic-delete-yes],[data-topic-type],[data-topic-more]');
      if (topicAction) {
        const data = topicAction.dataset;
        if (data.newTopic !== undefined) openNewTopic();
        else if (data.closeNewTopic !== undefined) closeNewTopic();
        else if (data.topicEdit !== undefined) startTopicEdit();
        else if (data.topicEditCancel !== undefined) stopTopicEdit();
        else if (data.topicDelete !== undefined) askTopicDelete();
        else if (data.topicDeleteYes !== undefined) deleteCurrentTopic(topicAction);
        else if (data.topicType !== undefined) filterTopicItems(data.topicType);
        else if (data.topicMore !== undefined) showMoreTopicItems(topicAction);
        return;
      }
      const target = event.target.closest('[data-open-note],[data-open-topic],[data-bot],[data-set-lens],[data-close-sheet],[data-go-view],[data-show-failed],[data-clear-lens]');
      if (!target) return;
      if (target.dataset.openNote !== undefined && target.dataset.openNote) {
        openNote(target.dataset.openNote);
      } else if (target.dataset.openTopic) {
        openTopicNotes(Number(target.dataset.openTopic));
      } else if (target.dataset.bot) {
        setLens(target.dataset.bot);
      } else if (target.dataset.setLens) {
        closeSheet();
        setLens(target.dataset.setLens, {toggle: false});
        goTo('home');
      } else if (target.dataset.closeSheet !== undefined) {
        closeSheet();
      } else if (target.dataset.goView) {
        closeSheet();
        goTo(target.dataset.goView);
      } else if (target.dataset.showFailed !== undefined) {
        if (typeof showFailedItems === 'function') showFailedItems();
      } else if (target.dataset.clearLens !== undefined) {
        setLens(null);
      }
    });

    $('lensClear').addEventListener('click', () => setLens(null));
    document.addEventListener('submit', event => {
      const contextForm = event.target.closest('[data-context-form]');
      if (contextForm) {
        event.preventDefault();
        saveContext(Number(contextForm.dataset.contextForm));
        return;
      }
      const renameForm = event.target.closest('[data-need-rename]');
      if (renameForm) {
        event.preventDefault();
        saveNeedRename(renameForm);
        return;
      }
      const dropForm = event.target.closest('[data-scout-drop-form]');
      if (dropForm) {
        event.preventDefault();
        scoutAnswer(dropForm.dataset.scoutDropForm, 'drop', {reason: dropForm.elements.reason.value.trim() || undefined});
        return;
      }
      if (event.target.id === 'scoutSettingsForm') {
        saveScoutSettings(event);
        return;
      }
      if (event.target.id === 'deleteAccountForm') {
        deleteAccount(event);
        return;
      }
      if (event.target.id === 'welcomeForm') {
        event.preventDefault();
        saveWelcome(event.target);
        return;
      }
      const memoryForm = event.target.closest('[data-memory-form]');
      if (memoryForm) {
        event.preventDefault();
        saveMemoryEdit(memoryForm);
        return;
      }
      const form = event.target.closest('[data-need-note]');
      if (!form) return;
      event.preventDefault();
      saveNeedNote(form);
    });
    $('globalSearchForm').addEventListener('submit', event => {
      event.preventDefault();
      const query = $('globalSearch').value.trim();
      if (query) goTo('search', query);
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        closeHover();
        if (closeDatePicker()) return;
        if (closeCapture()) return;
        if (!$('noteSheet').hidden) closeSheet();
        else closeDayPopup();
        return;
      }
      if ((event.key === 'n' || event.key === 'N') && !event.ctrlKey && !event.metaKey && !event.altKey
          && !isTyping(event.target) && $('noteSheet').hidden) {
        event.preventDefault();
        openCapture();
      }
    });
    window.addEventListener('lifeinbox:edited', event => {
      if (event.detail && event.detail.itemId) editedNotes.set(Number(event.detail.itemId), Date.now());
    });
    window.addEventListener('lifeinbox:analyzed', event => {
      const itemId = event.detail && Number(event.detail.itemId);
      if (!itemId) return;
      askAboutMovedDates(itemId);
      askAboutNewDates(itemId);
    });
    document.addEventListener('keydown', pickerKeys);
    document.addEventListener('keydown', trapDateFocus);
    document.addEventListener('pointerdown', event => {
      const picker = $('datePicker');
      if (!picker || picker.hidden) return;
      if (picker.contains(event.target) || event.target.closest('[data-date-task]')) return;
      // A question's dimmed page answers "Ask me later" when clicked (data-ask-later).
      if (state.datePicker && state.datePicker.ask) return;
      closeDatePicker({restoreFocus: false});
    });
    window.addEventListener('lifeinbox:captured', event => {
      if (event.detail && event.detail.itemId) capturedNotes.add(Number(event.detail.itemId));
      if (!captureIsFloating()) return;
      const itemId = event.detail && event.detail.itemId;
      closeCapture();
      showToast('Saved. Life Inbox is filing it now.', itemId ? {action: 'Open', onAction: () => openNote(itemId)} : {});
    });
    watchHoverCards();
    window.addEventListener('hashchange', () => routeFromLocation());
    window.addEventListener('popstate', () => {
      const key = L.lensFromSearch(window.location.search);
      if (key !== Lens.key) {
        Lens.key = key;
        applyLens();
      }
    });
    window.addEventListener('lifeinbox:changed', () => {
      noteCache.clear();
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(refresh, 400);
    });

    document.addEventListener('change', event => {
      if (event.target.id === 'aiProcessing') setAiProcessing(event.target);
      else if (event.target.matches('[data-health-consent]')) setHealthConsent(event.target);
      else if (event.target.matches('[data-topic-move]')) moveTopicArea(event.target);
      else if (event.target.matches('[data-task-priority]')) {
        setTaskPriority(Number(event.target.dataset.taskPriority), event.target.value);
      } else if (event.target.id === 'priorityGroupByArea') {
        priorityView.groupByArea = event.target.checked;
        renderPriority();
      }
    });
    watchCalendarDays();
    watchPriorityDrag();

    watchCalendarPreview();
    watchMasonry();
    renderLensChip();
    document.body.dataset.view = state.view;
    routeFromLocation({force: true});
    Promise.all([refreshAccount(), refreshBots(), refreshTopics(), refreshNeeds(), refreshScout()])
      .then(renderCurrentView)
      .then(maybeWelcome);
  }

  // app.js calls refreshTopics() after it changes topics (loadTopics).
  async function refreshTopicsAndView() {
    await refreshTopics();
    if (state.view === 'topics' || state.view === 'topic') renderCurrentView();
  }

  window.LifeInboxShell = {showView, openNote, closeSheet, setLens, refresh, goTo, refreshTopics: refreshTopicsAndView, toast: showToast,
    editNoteContext,
    lensKey: () => Lens.key, lensName: () => (Lens.key ? Lens.name : null), areaName: key => (state.botsByKey[key] || {}).name || key};

  // app.js loads after this file; by DOMContentLoaded both have run.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    setTimeout(init, 0);
  }
})();
