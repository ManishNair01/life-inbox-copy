/**
 * Pure helpers for the three-pane app (changes 009 and 010): routes, the lens,
 * the week chart, Today's focus, pinned topics, topic groups and filters,
 * breadcrumbs and summary lines.
 * No DOM and no network, so tests can run it in Node.
 *
 * Works in the browser (window.LifeInboxShellLogic) and in Node (module.exports)
 * without a build step.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.LifeInboxShellLogic = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // The five life areas. Must match BOT_KEYS in app/bots.py (tests check).
  const BOT_KEYS = ['learn', 'money', 'health', 'people', 'fun'];
  const VIEWS = [
    'home', 'topics', 'topic', 'timeline', 'calendar', 'priority', 'dashboard', 'ask',
    'search', 'settings', 'memory', 'scout', 'welcome',
  ];
  // Note kinds, in the order the topic page offers them as filters.
  const TYPE_FILTERS = [
    ['text', 'Notes'], ['url', 'Links'], ['pdf', 'PDFs'], ['image', 'Images'], ['voice', 'Voice'],
  ];
  const PRIORITY_RANK = {High: 0, Medium: 1, Low: 2};
  const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const MONTH_NAMES = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];

  /** The lens from the page address (`?bot=`), or null when it isn't an area. */
  function lensFromSearch(search) {
    const value = new URLSearchParams(search || '').get('bot');
    const key = (value || '').trim().toLowerCase();
    return BOT_KEYS.includes(key) ? key : null;
  }

  /**
   * `#/calendar` → {view: 'calendar'}; `#/search?q=gym` → {view: 'search', query: 'gym'};
   * `#/topic/12` → {view: 'topic', query: '12'} (a topic's page).
   */
  function routeFromHash(hash) {
    const raw = String(hash || '').replace(/^#\/?/, '');
    const [path, query = ''] = raw.split('?');
    const [name, arg = ''] = path.split('/');
    if (name === 'topic') {
      return /^[1-9][0-9]*$/.test(arg) ? {view: 'topic', query: arg} : {view: 'topics', query: ''};
    }
    const view = VIEWS.includes(name) && !arg ? name : 'home';
    const q = new URLSearchParams(query).get('q');
    return {view, query: view === 'search' ? (q || '').trim() : ''};
  }

  function hashFor(view, query) {
    if (view === 'search') return `#/search?q=${encodeURIComponent(query || '')}`;
    if (view === 'topic') return `#/topic/${encodeURIComponent(String(query || ''))}`;
    return `#/${VIEWS.includes(view) ? view : 'home'}`;
  }

  function pad(number) {
    return String(number).padStart(2, '0');
  }

  /** YYYY-MM-DD in local time. Never toISOString(): it shifts days east of UTC. */
  function isoDate(date) {
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  /** Monday to Sunday of the week that contains `today`, as YYYY-MM-DD. */
  function weekDays(today) {
    const monday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
    return Array.from({length: 7}, (_, index) => isoDate(
      new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + index)
    ));
  }

  function parseIso(iso) {
    const [year, month, day] = String(iso || '').slice(0, 10).split('-').map(Number);
    return new Date(year, (month || 1) - 1, day || 1);
  }

  /** Every day of the month that contains `date`, as YYYY-MM-DD. */
  function monthDays(date) {
    const count = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
    return Array.from({length: count}, (_, index) => isoDate(
      new Date(date.getFullYear(), date.getMonth(), index + 1)
    ));
  }

  function addDays(iso, days) {
    const value = parseIso(iso);
    return isoDate(new Date(value.getFullYear(), value.getMonth(), value.getDate() + days));
  }

  /**
   * The date picker's one-click choices, always later than now: for a task due
   * later on, a day or a week after its date; otherwise tomorrow or next week.
   */
  function postponeChoices(dueIso, todayIso) {
    if (dueIso && dueIso > todayIso) {
      return [
        {label: 'A day later', iso: addDays(dueIso, 1)},
        {label: 'A week later', iso: addDays(dueIso, 7)},
      ];
    }
    return [
      {label: 'Tomorrow', iso: addDays(todayIso, 1)},
      {label: 'Next week', iso: addDays(todayIso, 7)},
    ];
  }

  /** The Timeline's anchor moved by whole weeks or months; months land on the 1st. */
  function shiftAnchor(anchorIso, mode, delta) {
    const anchor = parseIso(anchorIso);
    if (mode === 'month') return isoDate(new Date(anchor.getFullYear(), anchor.getMonth() + delta, 1));
    return isoDate(new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() + 7 * delta));
  }

  /**
   * Where a task's date stands (change 012): "confirmed" (by you), "note" (your
   * words name the day), "suggested" (a guess waiting for your OK) or "none".
   */
  function dateState(task) {
    if (!task) return 'none';
    if (task.due_on) return task.timing_confirmed ? 'confirmed' : 'note';
    return task.suggested_due_on ? 'suggested' : 'none';
  }

  /** The day a task sits on in Timeline and Priority: its date, else its suggestion. */
  function taskDay(task) {
    return (task && (task.due_on || task.suggested_due_on)) || null;
  }

  function isOpen(task) {
    return task && task.status === 'open';
  }

  /** One column per day; each open task due that day becomes a spike. */
  function weekSpikes(tasks, days) {
    return days.map(day => ({
      day,
      tasks: (tasks || [])
        .filter(task => isOpen(task) && taskDay(task) === day)
        .map(task => ({
          id: task.id,
          text: task.text,
          priority: task.priority,
          // Solid for a day you named or confirmed, dashed for a suggestion.
          confirmed: dateState(task) !== 'suggested',
          sourceItemId: (task.source_item_ids || [])[0] || null,
        })),
    }));
  }

  function byDue(first, second) {
    return (taskDay(first) || '9999').localeCompare(taskDay(second) || '9999')
      || (first.due_time || '99:99').localeCompare(second.due_time || '99:99')
      || first.id - second.id;
  }

  /** Someday tasks (change 018): kept apart from the board and the backlog. */
  function somedayTasks(tasks) {
    return (tasks || []).filter(task => isOpen(task) && task.someday)
      .sort((first, second) => String(first.someday_since || '').localeCompare(String(second.someday_since || '')));
  }

  /** Tasks done on each day up to today, by the local day they were done (Timeline ✓, decision F). */
  function doneByDay(tasks, days, todayIso) {
    const byDay = Object.fromEntries(days.map(day => [day, []]));
    for (const task of tasks || []) {
      if (task.status !== 'completed' || !task.completed_at) continue;
      const when = new Date(task.completed_at);
      if (Number.isNaN(when.getTime())) continue;
      const day = isoDate(when);
      if (day in byDay && day <= todayIso) byDay[day].push({id: task.id, text: task.text});
    }
    return byDay;
  }

  /** The next dated open tasks, from today on. */
  function nextUp(tasks, todayIso, limit = 3) {
    return (tasks || [])
      .filter(task => isOpen(task) && taskDay(task) && taskDay(task) >= todayIso)
      .sort(byDue)
      .slice(0, limit);
  }

  /**
   * At most `limit` tasks: overdue and due today first (most important first),
   * then other High-priority ones. Snoozed tasks wait until their day.
   */
  function todaysFocus(tasks, todayIso, limit = 3) {
    const open = (tasks || []).filter(task => isOpen(task));
    const awake = open.filter(task => !task.snoozed_until || task.snoozed_until <= todayIso);
    const rank = task => (task.priority in PRIORITY_RANK ? PRIORITY_RANK[task.priority] : 9);
    const due = awake
      .filter(task => task.due_on && task.due_on <= todayIso)
      .sort((first, second) => rank(first) - rank(second) || byDue(first, second));
    const important = awake
      .filter(task => task.priority === 'High' && !due.includes(task))
      .sort(byDue);
    const items = due.concat(important).slice(0, limit);
    return {items, waiting: open.length - items.length};
  }

  /**
   * Priority's board: overdue and today's tasks plus the next `next` dated ones
   * go on the board; later, undated and snoozed ones wait in the backlog.
   */
  function prioritySplit(tasks, todayIso, next = 3) {
    const open = (tasks || []).filter(task => isOpen(task) && !task.someday);
    const awake = open.filter(task => !task.snoozed_until || task.snoozed_until <= todayIso);
    const now = awake.filter(task => taskDay(task) && taskDay(task) <= todayIso);
    const soon = awake.filter(task => taskDay(task) && taskDay(task) > todayIso).sort(byDue).slice(0, next);
    const board = new Set(now.concat(soon).map(task => task.id));
    const sort = list => list.slice().sort((first, second) => byDue(first, second));
    return {
      board: sort(open.filter(task => board.has(task.id))),
      backlog: sort(open.filter(task => !board.has(task.id))),
    };
  }

  /**
   * On the Priority board a near date raises a task one step (Low → Medium →
   * High): due today, tomorrow or overdue, on a date your words named or you
   * confirmed. Your own pick is never changed. Change 012.
   */
  function boardPriority(task, todayIso) {
    const priority = task.priority || 'Medium';
    if (task.user_priority || !task.due_on || task.due_on > addDays(todayIso, 1)) {
      return {priority, raised: false};
    }
    const up = {Low: 'Medium', Medium: 'High', High: 'High'}[priority] || priority;
    return {priority: up, raised: up !== priority};
  }

  /** The date picker's month: weeks of 7 days, Monday first, with the days around it. */
  function monthGrid(anchorIso) {
    const anchor = parseIso(anchorIso);
    const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
    const start = new Date(first.getFullYear(), first.getMonth(), 1 - ((first.getDay() + 6) % 7));
    const weeks = [];
    for (let week = 0; week < 6; week += 1) {
      const days = [];
      for (let index = 0; index < 7; index += 1) {
        const day = new Date(start.getFullYear(), start.getMonth(), start.getDate() + week * 7 + index);
        days.push({iso: isoDate(day), day: day.getDate(), inMonth: day.getMonth() === first.getMonth()});
      }
      if (week > 3 && !days.some(day => day.inMonth)) break;
      weeks.push(days);
    }
    return {
      month: isoDate(first),
      title: `${['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][first.getMonth()]} ${first.getFullYear()}`,
      weeks,
    };
  }

  /** Tasks in priority columns: High, Medium, Low, each in date order. */
  function priorityColumns(tasks) {
    return ['High', 'Medium', 'Low'].map(priority => ({
      priority,
      tasks: (tasks || []).filter(task => (task.priority || 'Medium') === priority),
    }));
  }

  /** Tasks grouped by life area, in the areas' order; tasks in no area last. */
  function groupByArea(tasks, bots) {
    const groups = (bots || []).map(bot => ({
      key: bot.key, name: bot.name, tasks: (tasks || []).filter(task => task.bot_key === bot.key),
    }));
    const known = new Set((bots || []).map(bot => bot.key));
    groups.push({key: null, name: 'No area yet', tasks: (tasks || []).filter(task => !known.has(task.bot_key))});
    return groups.filter(group => group.tasks.length);
  }

  /** The busiest topics, by notes filed directly in them. */
  function pinnedTopics(topics, limit = 5) {
    return (topics || [])
      .filter(topic => !topic.archived && topic.item_count > 0)
      .sort((first, second) => second.item_count - first.item_count
        || first.name.localeCompare(second.name))
      .slice(0, limit);
  }

  const byBusiest = (first, second) => second.total_item_count - first.total_item_count
    || first.name.localeCompare(second.name);

  /**
   * Topics and spaces: one group per life area, busiest area first, each with
   * its main topics (busiest first) and their subtopics. Topics in no area yet
   * (the v1 catch-all until change 014) come last. With a lens, only that area.
   */
  function topicGroups(bots, topics, lensKey) {
    const live = (topics || []).filter(topic => !topic.archived);
    const ids = new Set(live.map(topic => topic.id));
    const isMain = topic => !topic.parent_topic_id || !ids.has(topic.parent_topic_id);
    const entries = members => members.filter(isMain).sort(byBusiest).map(topic => ({
      topic,
      subtopics: members
        .filter(sub => sub.parent_topic_id === topic.id)
        .sort((first, second) => second.item_count - first.item_count
          || first.name.localeCompare(second.name)),
    }));
    const count = members => members.filter(isMain)
      .reduce((sum, topic) => sum + (topic.total_item_count || 0), 0);
    const groups = (bots || [])
      .filter(bot => !lensKey || bot.key === lensKey)
      .map((bot, order) => {
        const members = live.filter(topic => topic.bot_key === bot.key);
        return {key: bot.key, name: bot.name, order, count: count(members), entries: entries(members)};
      })
      .sort((first, second) => second.count - first.count || first.order - second.order);
    // Topics in no area: shown while they hold notes, or when one is your own (to
    // move it). The empty v1 catch-all alone isn't worth a card.
    const loose = live.filter(topic => !topic.bot_key || !BOT_KEYS.includes(topic.bot_key));
    if (!lensKey && loose.length && (count(loose) > 0 || loose.some(topic => !topic.is_built_in))) {
      groups.push({key: null, name: 'Not in an area yet', order: groups.length, count: count(loose), entries: entries(loose)});
    }
    return groups;
  }

  /** The topic page's kind filters: "All", then only the kinds it has, with counts. */
  function typeFilters(typeCounts) {
    const counts = typeCounts || {};
    const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
    return [{type: '', label: 'All', count: total}].concat(
      TYPE_FILTERS.filter(([type]) => counts[type] > 0)
        .map(([type, label]) => ({type, label, count: counts[type]}))
    );
  }

  function firstLine(text) {
    return String(text || '').trim().split('\n')[0].trim();
  }

  function clip(text, max) {
    const flat = String(text || '').replace(/\s+/g, ' ').trim();
    return flat.length > max ? `${flat.slice(0, max - 1).trimEnd()}…` : flat;
  }

  /** A note as the screen shows it: secret values hidden (change 016). */
  function shown(item) {
    return item && item.secret_masked ? {...item, ...item.secret_masked} : item;
  }

  /** A note's title without its AI insight: a source's own title, else its first line. */
  function noteTitle(item) {
    if (!item) return 'Untitled note';
    item = shown(item);
    return clip(item.title || firstLine(item.raw_text) || firstLine(item.extracted_text)
      || item.original_filename || 'Untitled note', 90);
  }

  /** What a topic's hover card says: its area, counts, full description and subtopics. */
  function topicHover(topic, topics, botsByKey) {
    if (!topic) return null;
    const subtopics = (topics || [])
      .filter(other => other.parent_topic_id === topic.id && !other.archived)
      .map(other => other.name);
    const total = topic.total_item_count ?? topic.item_count ?? 0;
    const inSubtopics = Math.max(0, total - (topic.item_count || 0));
    const bot = (botsByKey || {})[topic.bot_key];
    let count = total ? plural(total, 'note') : 'No notes yet';
    if (inSubtopics) count += `, ${inSubtopics} in subtopics`;
    return {
      name: topic.name,
      area: bot ? bot.name : 'Not in an area yet',
      count,
      description: String(topic.description || '').trim(),
      subtopics,
      builtIn: Boolean(topic.is_built_in),
    };
  }

  /** What a note's hover card says: kind, the local day it was saved, your note and the start of its text. */
  function notePreview(item, maxText = 220, maxNote = 160) {
    if (!item) return null;
    item = shown(item);
    const kind = item.item_type || 'text';
    const when = new Date(item.created_at);
    // A typed note's title is just its first line, so its card shows the text
    // once. A source keeps its own title, then the start of its content.
    const isText = kind === 'text';
    const title = isText ? '' : noteTitle(item);
    const body = clip(isText ? item.raw_text : (item.extracted_text || item.raw_text), maxText);
    return {
      kind,
      title,
      savedOn: Number.isNaN(when.getTime()) ? '' : formatDay(isoDate(when)),
      note: item.user_context ? clip(item.user_context, maxNote) : '',
      excerpt: body && body !== title ? body : '',
      failed: item.processing_status === 'failed',
    };
  }

  /** area › parent topic › topic, for the note page. */
  function breadcrumb(topicId, topicsById, botsByKey) {
    const topic = topicsById[topicId];
    if (!topic) return [];
    const parent = topic.parent_topic_id ? topicsById[topic.parent_topic_id] : null;
    const bot = botsByKey[topic.bot_key];
    const parts = [];
    if (bot) parts.push({kind: 'bot', key: bot.key, label: bot.name});
    if (parent) parts.push({kind: 'topic', id: parent.id, label: parent.name});
    parts.push({kind: 'topic', id: topic.id, label: topic.name});
    return parts;
  }

  function greeting(date) {
    const hour = date.getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
  }

  /** "2026-11-03" → "Tue 3 Nov". */
  function formatDay(iso) {
    const [year, month, day] = String(iso || '').slice(0, 10).split('-').map(Number);
    if (!year || !month || !day) return iso || '';
    const date = new Date(year, month - 1, day);
    return `${DAY_NAMES[date.getDay()]} ${day} ${MONTH_NAMES[month - 1]}`;
  }

  /** "2026-11-08" → a calendar page: {weekday: 'Sun', weekdayLong: 'Sunday', day: 8, month: 'Nov', year: 2026}. */
  function dayParts(iso) {
    const [year, month, day] = String(iso || '').slice(0, 10).split('-').map(Number);
    if (!year || !month || !day) return null;
    const date = new Date(year, month - 1, day);
    return {
      weekday: DAY_NAMES[date.getDay()],
      weekdayLong: ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][date.getDay()],
      day,
      month: MONTH_NAMES[month - 1],
      year,
    };
  }

  /** Open tasks whose date is only a suggestion, soonest first: they wait for your OK (change 012). */
  function waitingDates(tasks) {
    return (tasks || []).filter(task => isOpen(task) && dateState(task) === 'suggested').sort(byDue);
  }

  function plural(count, word) {
    return `${count} ${word}${count === 1 ? '' : 's'}`;
  }

  /** Captain's line on Home, from the daily briefing counts. */
  function captainSummary(counts, needsYou) {
    const c = counts || {};
    const parts = [];
    if (c.overdue) parts.push(`${plural(c.overdue, 'task')} overdue`);
    if (c.today) parts.push(`${c.today} due today`);
    if (c.upcoming) parts.push(`${c.upcoming} coming up`);
    let text = parts.length ? `${parts.join(', ')}.` : 'Nothing is due right now.';
    if (needsYou) {
      text += ` ${plural(needsYou, 'thing')} ${needsYou === 1 ? 'needs' : 'need'} a quick answer from you.`;
    } else {
      text += ' Nothing needs you.';
    }
    return text;
  }

  // --- memory (change 016) ---
  const MEMORY_STATUS = {suggested: 'Not confirmed yet', expired: 'Past'};

  /** What a fact's status chip says; a confirmed fact needs none. */
  function memoryStatus(fact) {
    return MEMORY_STATUS[fact && fact.status] || '';
  }

  /** Facts grouped by area: what spans your areas (Captain's) first, then the five areas. */
  function memoryGroups(facts, bots) {
    const names = Object.fromEntries((bots || []).map(bot => [bot.key, bot.name]));
    const areaOf = fact => (BOT_KEYS.includes(fact.bot_key) ? fact.bot_key : null);
    return [null, ...BOT_KEYS]
      .map(key => ({
        key,
        name: key ? (names[key] || key) : 'Across your areas',
        facts: (facts || []).filter(fact => areaOf(fact) === key),
      }))
      .filter(group => group.facts.length);
  }

  /** A life area's summary line (written by code until change 020). */
  function botSummary(bot) {
    if (!bot) return '';
    if (!bot.item_count && !bot.open_task_count) {
      return `Nothing in ${bot.name} yet. Notes about it will gather here.`;
    }
    const parts = [plural(bot.item_count, 'note')];
    if (bot.open_task_count) parts.push(plural(bot.open_task_count, 'open task'));
    let text = parts.join(' · ');
    if (bot.next_task) {
      const time = bot.next_task.due_time ? ` at ${bot.next_task.due_time}` : '';
      text += `. Next: ${bot.next_task.text}, ${formatDay(bot.next_task.due_on)}${time}.`;
    }
    return text;
  }

  return {
    BOT_KEYS,
    VIEWS,
    lensFromSearch,
    routeFromHash,
    hashFor,
    isoDate,
    weekDays,
    monthDays,
    shiftAnchor,
    addDays,
    postponeChoices,
    weekSpikes,
    prioritySplit,
    priorityColumns,
    boardPriority,
    monthGrid,
    clip,
    dayParts,
    waitingDates,
    dateState,
    taskDay,
    groupByArea,
    nextUp,
    todaysFocus,
    pinnedTopics,
    topicGroups,
    typeFilters,
    breadcrumb,
    noteTitle,
    topicHover,
    notePreview,
    greeting,
    formatDay,
    captainSummary,
    botSummary,
    shown,
    memoryStatus,
    memoryGroups,
    somedayTasks,
    doneByDay,
  };
});
