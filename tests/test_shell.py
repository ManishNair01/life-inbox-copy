"""The three-pane app (changes 009 and 010): page structure, nothing from v1
lost, and the shell's pure logic (run in Node, like tests/test_pagination_state.py)."""

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import register

MODULES = ("app.main", "app.database", "app.auth", "app.config")
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
LOGIC = STATIC / "shell_logic.js"
NODE = shutil.which("node")

# Every element id the v1 single page had. They all stay, inside the new views,
# except the flat topic list "topics": change 010 replaced it with cards grouped
# by life area (topicGroups) and a page per topic (topicPage), which keep its
# counts and its delete action.
V1_IDS = """
accountMenuPanel accountMenuToggle addNoteButton aiOutput analysisStatus analyzeButton askButton
askForm askOutput askQuestion askSection askStatus attachLinkButton attachmentChip attachmentKind
attachmentLabel attention authStatus authUser briefing briefingStatus calMonthYear calNextBtn
calPrevBtn calTodayBtn calendarDayDetails calendarDayHeading calendarEventsList calendarGrid
calendarPreview calendarSection calendarStatus categoryFilter changePasswordButton
changePasswordForm composerHint currentPassword dailyDigestTime dashboard dashboardSection
dashboardStatus enableNotificationPrompt failureCenter failureCenterHeading homeTop imageFile
inAppCalendar inAppCalendarStatus includeUnscheduledPrompt itemSearch itemSearchForm itemTypeFilter
linkAttachRow micIcon micLabel micPulse micSpinner micTimer micVoiceButton micVoiceStatus
newPassword newPasswordConfirm noteCharCount noteStatus noteText notes notificationPrompt
notificationPromptHeading notificationPromptMessage notificationSettingsForm notificationStatus
notificationTimezone notificationsEnabled pdfFile priorityFilter processingStatusFilter
quickTaskDueOn quickTaskForm quickTaskPriority quickTaskSubmit quickTaskText rawSavedNotesHeading
saveNotificationSettingsButton searchStatus taskStatus taskStatusFilter tasks tasksSection
topicAcceptParent topicDescription topicForm topicKeepSeparate topicName topicNextButton topicStatus
topicSuggestion topicSuggestionReason topicSuggestionText urlText voiceFile
""".split()

# Every action the v1 page offered.
V1_HANDLERS = [
    "logoutSession()", "logoutAllSessions()", "changePassword(event)",
    "enableNotificationsFromPrompt(event)", "showFailedItems()", "clearAttachment()",
    "confirmLinkAttach()", "cancelLinkAttach()", "openLinkAttach()", "pickAttachment('pdf')",
    "pickAttachment('image')", "pickAttachment('audio')", "toggleVoiceRecording()", "addCapture()",
    "resortEverything()", "askInbox(event)", "fillAskExample(", "createTopic(event)",
    "confirmTopic(true)", "confirmTopic(false)", "cancelTopicSuggestion()",
    "changeCalendarMonth(-1)", "changeCalendarMonth(1)", "jumpCalendarToToday()",
    "saveNotificationSettings(event)", "createQuickTask(event)", "changeTaskStatusFilter()",
    "applyItemFilters(event)", "clearItemFilters()", 'href="/api/items/export.md"',
]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'shell.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    for name in MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    with TestClient(main.app) as test_client:
        register(test_client, "owner@example.com")
        yield test_client
    database.engine.dispose()
    for name in MODULES:
        sys.modules.pop(name, None)


def page_ids(page):
    return re.findall(r'\bid="([A-Za-z0-9_-]+)"', page)


# --- the page ------------------------------------------------------------------------


def test_page_is_the_three_pane_app(client):
    page = client.get("/").text
    for landmark in ('class="shell-header"', 'class="pane pane-left"', 'id="centerPane"',
                     'class="pane pane-right"', 'id="lensChip"', 'id="globalSearch"',
                     'id="pinnedTopics"', 'id="lifeBots"', 'id="captainLink"', 'id="noteSheet"',
                     'id="calendarDock"', 'data-theme="calm"', 'id="topicGroups"',
                     'id="newTopicPanel"', 'id="topicBotChoice"', 'id="topicPage"'):
        assert landmark in page, landmark
    views = re.findall(r'class="view" data-view="([a-z]+)"', page)
    assert views == ["home", "topics", "topic", "timeline", "calendar", "priority",
                     "dashboard", "ask", "search", "welcome", "scout", "memory", "settings"]
    links = re.findall(r'data-view-link="([a-z]+)"', page)
    assert links == ["home", "topics", "timeline", "calendar", "priority", "dashboard", "ask"]
    # The composer stays on top of the centre pane, before every view.
    assert page.index('id="noteText"') < page.index('class="views"')
    # The shell's logic and drawing load before app.js, which reads the lens.
    scripts = re.findall(r'<script src="/static/([a-z_]+\.js)', page)
    assert scripts == ["password_rules.js", "pagination_state.js", "shell_logic.js", "shell.js", "app.js"]
    assert "/static/shell.css" in page


def test_nothing_from_the_v1_page_is_lost(client):
    page = client.get("/").text
    ids = page_ids(page)
    for element_id in V1_IDS:
        assert ids.count(element_id) == 1, element_id
    for handler in V1_HANDLERS:
        assert handler in page, handler
    # The long scrolling page and its anchor rail are gone.
    assert "app-rail" not in page and "zone--" not in page


def test_every_element_app_js_looks_up_is_on_the_page(client):
    ids = set(page_ids(client.get("/").text))
    wanted = set(re.findall(r"getElementById\('([A-Za-z0-9_-]+)'\)", (STATIC / "app.js").read_text(encoding="utf-8")))
    created_by_script = {"loadMoreItems", "recordVoiceButton"}
    assert wanted - created_by_script - ids == set()


def test_shell_js_only_uses_elements_that_exist(client):
    ids = set(page_ids(client.get("/").text))
    shell = (STATIC / "shell.js").read_text(encoding="utf-8")
    wanted = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", shell))
    created_by_shell = {
        "noteSheetTasks", "noteMarkDone", "noteMoveTopic", "noteShowInList", "noteSheetStatus",
        "topicItems", "topicPageStatus", "topicEditor", "topicEditForm", "topicEditName",
        "topicEditDescription", "datePickerTime", "dateAskLeft", "needNote",
        # Scout's "Why drop it?" box (change 018)
        "scoutReason",
        # Rename for a topic proposal (change 020)
        "needName",
        # your note on a saved source (change 023)
        "contextText",
    }
    assert wanted - created_by_shell - ids == set()


def test_topics_view_replaces_the_flat_list(client):
    page = client.get("/").text
    topics_view = page[page.index('data-view="topics"'):page.index('data-view="topic"')]
    # Cards first, then All notes; the AI-organized inbox is folded away below.
    assert topics_view.index('id="topicGroups"') < topics_view.index('id="rawSavedNotesHeading"')
    assert topics_view.index('id="rawSavedNotesHeading"') < topics_view.index('id="aiOrganizedHeading"')
    assert '<details class="view-card ai-organized">' in topics_view
    assert 'id="topics"' not in page
    # The new topic form lives in its panel, with the area step.
    panel = page[page.index('id="newTopicPanel"'):page.index('id="topicGroups"')]
    for element_id in ("topicForm", "topicSuggestion", "topicBotChoice", "topicStatus"):
        assert f'id="{element_id}"' in panel, element_id
    # app.js's loadTopics now asks the shell to redraw instead of drawing a list.
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "LifeInboxShell.refreshTopics()" in app_js
    assert "askDeleteTopic" not in app_js


def test_new_topic_area_choices_match_the_server(client):
    page = client.get("/").text
    select = page[page.index('id="topicBotChoice"'):page.index("</select>", page.index('id="topicBotChoice"'))]
    options = re.findall(r'<option value="([a-z]*)">([^<]+)</option>', select)
    bots = [(bot["key"], bot["name"]) for bot in client.get("/api/bots").json()]
    assert options[0] == ("", "Let Life Inbox choose")
    assert [(key, name.replace("&amp;", "&")) for key, name in options[1:]] == bots


def test_account_menu_and_captain_link(client):
    page = client.get("/").text
    menu = page[page.index('id="accountMenuPanel"'):page.index("</details>", page.index('id="accountMenuPanel"'))]
    for link in ('href="#/settings"', "showFailedItems()", 'href="/api/items/export.md"', 'href="/privacy"'):
        assert link in menu, link
    # Captain stands for everything: its link clears the lens.
    assert re.search(r'id="captainLink"[^>]*data-clear-lens', page)


def test_view_switches_never_assign_location_hash():
    # Assigning location.hash fires popstate, and app.js reloads its lists on popstate.
    # That raced "Failed captures", which lost its filter. goTo uses pushState instead.
    shell = (STATIC / "shell.js").read_text(encoding="utf-8")
    assert not re.search(r"location\.hash\s*=[^=]", shell)
    assert "history.pushState(window.history.state, '', hash)" in shell


def test_prototype_is_no_longer_served(client):
    assert client.get("/static/prototype/new-ui-prototype.html").status_code == 404
    assert (Path(__file__).resolve().parents[1] / "docs" / "design" / "prototype" / "new-ui-prototype.html").exists()


def test_items_can_be_listed_newest_first(client):
    ids = [client.post("/api/items", json={"raw_text": f"Note {n}"}).json()["id"] for n in range(3)]
    newest = [item["id"] for item in client.get("/api/items", params={"order": "desc", "limit": 2}).json()]
    assert newest == [ids[2], ids[1]]
    oldest = [item["id"] for item in client.get("/api/items").json()]
    assert oldest == ids
    assert client.get("/api/items", params={"order": "sideways"}).status_code == 422


# --- the shell's pure logic, in Node ----------------------------------------------------

needs_node = pytest.mark.skipif(NODE is None, reason="node is required for JS helper tests")


def run_logic(script, timezone=None):
    env = dict(os.environ)
    if timezone:
        env["TZ"] = timezone
    completed = subprocess.run(
        [NODE, "-e", f"const S = require({json.dumps(str(LOGIC))});\n{script}"],
        check=True, capture_output=True, text=True, encoding="utf-8", env=env,
    )
    return json.loads(completed.stdout)


@needs_node
def test_bot_keys_match_the_server():
    from app.bots import BOT_KEYS

    assert run_logic("console.log(JSON.stringify(S.BOT_KEYS));") == list(BOT_KEYS)


@needs_node
def test_lens_and_routes():
    result = run_logic("""
console.log(JSON.stringify({
  lens: ['?bot=health', '?bot=HEALTH', '?bot=travel', '', '?q=x&bot=fun'].map(S.lensFromSearch),
  routes: ['#/calendar', '#/search?q=gym%20plan', '#/nowhere', '', '#/home'].map(S.routeFromHash),
  topicRoutes: ['#/topic/12', '#/topic/0', '#/topic/abc', '#/topic', '#/topics', '#/home/3'].map(S.routeFromHash),
  hash: [S.hashFor('search', 'a b'), S.hashFor('topics'), S.hashFor('bogus'), S.hashFor('topic', 12)],
}));
""")
    assert result["lens"] == ["health", "health", None, None, "fun"]
    assert result["routes"] == [
        {"view": "calendar", "query": ""}, {"view": "search", "query": "gym plan"},
        {"view": "home", "query": ""}, {"view": "home", "query": ""}, {"view": "home", "query": ""},
    ]
    # A topic's page; a bad topic id falls back to Topics and spaces.
    assert result["topicRoutes"] == [
        {"view": "topic", "query": "12"}, {"view": "topics", "query": ""},
        {"view": "topics", "query": ""}, {"view": "topics", "query": ""},
        {"view": "topics", "query": ""}, {"view": "home", "query": ""},
    ]
    assert result["hash"] == ["#/search?q=a%20b", "#/topics", "#/home", "#/topic/12"]


@needs_node
@pytest.mark.parametrize("timezone", ["UTC", "Asia/Kolkata", "America/Los_Angeles"])
def test_week_runs_monday_to_sunday_in_any_time_zone(timezone):
    result = run_logic("""
console.log(JSON.stringify([
  S.weekDays(new Date(2026, 10, 4, 23, 30)),
  S.weekDays(new Date(2026, 10, 8, 0, 15)),
  S.weekDays(new Date(2026, 10, 2, 9, 0)),
]));
""", timezone=timezone)
    week = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08"]
    assert result == [week, week, week]


TASKS = """
const tasks = [
  {id: 1, status: 'open', text: 'Quiz', priority: 'High', due_on: '2026-11-03', due_time: '11:00', timing_confirmed: true, source_item_ids: [10]},
  {id: 2, status: 'open', text: 'Pasta', priority: 'High', due_on: null, suggested_due_on: '2026-11-07', timing_confirmed: false, source_item_ids: [11]},
  {id: 3, status: 'open', text: 'Old bill', priority: 'Medium', due_on: '2026-11-01', source_item_ids: []},
  {id: 4, status: 'completed', text: 'Done one', priority: 'High', due_on: '2026-11-04'},
  {id: 5, status: 'open', text: 'Call Rohan', priority: 'High', due_on: null},
  {id: 6, status: 'open', text: 'Snoozed', priority: 'High', due_on: '2026-11-02', snoozed_until: '2026-11-06'},
  {id: 7, status: 'open', text: 'Netflix', priority: 'Low', due_on: '2026-12-15'},
  {id: 8, status: 'open', text: 'Read', priority: 'Low', due_on: null},
];
"""


@needs_node
def test_week_spikes_next_up_and_todays_focus():
    result = run_logic(TASKS + """
const days = S.weekDays(new Date(2026, 10, 4));
const spikes = S.weekSpikes(tasks, days);
const focus = S.todaysFocus(tasks, '2026-11-04');
console.log(JSON.stringify({
  spikes: spikes.map(s => [s.day, s.tasks.map(t => [t.id, t.confirmed, t.sourceItemId])]),
  next: S.nextUp(tasks, '2026-11-04').map(t => t.id),
  focus: focus.items.map(t => t.id),
  waiting: focus.waiting,
}));
""")
    # Solid for a confirmed date or a day the note named; dashed for a suggestion (task 2).
    assert result["spikes"] == [
        ["2026-11-02", [[6, True, None]]], ["2026-11-03", [[1, True, 10]]], ["2026-11-04", []],
        ["2026-11-05", []], ["2026-11-06", []], ["2026-11-07", [[2, False, 11]]], ["2026-11-08", []],
    ]
    # From today on, in date order; completed tasks never count.
    assert result["next"] == [2, 7]
    # Overdue and due today first (High before Medium), then other High ones;
    # the snoozed task waits; at most 3.
    assert result["focus"] == [1, 3, 2]
    assert result["waiting"] == 4


@needs_node
def test_pinned_topics_breadcrumb_and_text():
    result = run_logic("""
const topics = [
  {id: 1, name: 'Study', item_count: 2, bot_key: 'learn', parent_topic_id: null},
  {id: 2, name: 'Python', item_count: 3, bot_key: 'learn', parent_topic_id: 1},
  {id: 3, name: 'Family', item_count: 0, bot_key: 'people'},
  {id: 4, name: 'Archived', item_count: 9, archived: true},
  {id: 5, name: 'Bills & subscriptions', item_count: 2, bot_key: 'money'},
];
const byId = Object.fromEntries(topics.map(t => [t.id, t]));
const bots = {learn: {key: 'learn', name: 'Learning & work'}};
console.log(JSON.stringify({
  pinned: S.pinnedTopics(topics).map(t => t.name),
  crumbs: S.breadcrumb(2, byId, bots).map(p => p.label),
  noCrumbs: S.breadcrumb(99, byId, bots),
  day: [S.formatDay('2026-11-03'), S.formatDay('2026-12-15'), S.formatDay('nope')],
  greet: [S.greeting(new Date(2026, 10, 4, 8)), S.greeting(new Date(2026, 10, 4, 14)), S.greeting(new Date(2026, 10, 4, 20))],
  captain: [
    S.captainSummary({overdue: 1, today: 2, upcoming: 0}, 1),
    S.captainSummary({}, 0),
    S.captainSummary({upcoming: 3}, 2),
  ],
  bot: [
    S.botSummary({name: 'Health', item_count: 0, open_task_count: 0}),
    S.botSummary({name: 'Learning & work', item_count: 3, open_task_count: 1,
                  next_task: {text: 'Take Python quiz', due_on: '2026-11-03', due_time: '11:00'}}),
  ],
}));
""")
    assert result["pinned"] == ["Python", "Bills & subscriptions", "Study"]
    assert result["crumbs"] == ["Learning & work", "Study", "Python"]
    assert result["noCrumbs"] == []
    assert result["day"] == ["Tue 3 Nov", "Tue 15 Dec", "nope"]
    assert result["greet"] == ["Good morning", "Good afternoon", "Good evening"]
    assert result["captain"] == [
        "1 task overdue, 2 due today. 1 thing needs a quick answer from you.",
        "Nothing is due right now. Nothing needs you.",
        "3 coming up. 2 things need a quick answer from you.",
    ]
    assert result["bot"] == [
        "Nothing in Health yet. Notes about it will gather here.",
        "3 notes · 1 open task. Next: Take Python quiz, Tue 3 Nov at 11:00.",
    ]


@needs_node
def test_topic_groups_busiest_area_first():
    result = run_logic("""
const bots = [
  {key: 'learn', name: 'Learning & work'}, {key: 'money', name: 'Money & home'},
  {key: 'health', name: 'Health'}, {key: 'people', name: 'People'}, {key: 'fun', name: 'Fun & interests'},
];
const t = (id, name, bot_key, item_count, extra = {}) => ({id, name, bot_key, item_count, total_item_count: item_count, ...extra});
const topics = [
  t(1, 'Study', 'learn', 1, {total_item_count: 4}),
  t(2, 'Python', 'learn', 3, {parent_topic_id: 1}),
  t(3, 'Work & career', 'learn', 0),
  t(4, 'Skills & projects', 'learn', 2),
  t(5, 'Bills & subscriptions', 'money', 5),
  t(6, 'Family', 'people', 0),
  t(7, 'Personal / Reference', null, 1, {is_built_in: true}),
  t(8, 'Old', 'fun', 9, {archived: true}),
  t(9, 'SQL', 'learn', 0, {parent_topic_id: 1}),
];
const view = groups => groups.map(g => [g.key, g.count, g.entries.map(e => [e.topic.name, e.subtopics.map(s => s.name)])]);
const emptyCatchAll = topics.map(x => x.id === 7 ? {...x, item_count: 0, total_item_count: 0} : x);
const ownLoose = emptyCatchAll.concat([t(10, 'Chess', null, 0)]);
console.log(JSON.stringify({
  all: view(S.topicGroups(bots, topics, null)),
  lens: view(S.topicGroups(bots, topics, 'learn')),
  emptyCatchAll: view(S.topicGroups(bots, emptyCatchAll, null)).map(g => g[0]),
  ownLoose: view(S.topicGroups(bots, ownLoose, null)).slice(-1),
  filters: [S.typeFilters({text: 4, url: 1, voice: 2}), S.typeFilters({}), S.typeFilters(null)],
}));
""")
    # Busiest area first (Learning 6 > Money 5), the rest in their usual order;
    # inside an area, busiest topic first; subtopics under their topic; archived
    # topics left out; topics in no area last.
    assert result["all"] == [
        ["learn", 6, [["Study", ["Python", "SQL"]], ["Skills & projects", []], ["Work & career", []]]],
        ["money", 5, [["Bills & subscriptions", []]]],
        ["health", 0, []],
        ["people", 0, [["Family", []]]],
        ["fun", 0, []],
        [None, 1, [["Personal / Reference", []]]],
    ]
    # The empty v1 catch-all alone gets no card; your own topic with no area does.
    assert result["emptyCatchAll"] == ["learn", "money", "health", "people", "fun"]
    assert result["ownLoose"] == [[None, 0, [["Chess", []], ["Personal / Reference", []]]]]
    # With a lens, only that area (and never the no-area group).
    assert result["lens"] == [["learn", 6, [["Study", ["Python", "SQL"]], ["Skills & projects", []], ["Work & career", []]]]]
    # Kind filters: All, then only the kinds the topic has, in a fixed order.
    assert result["filters"][0] == [
        {"type": "", "label": "All", "count": 7}, {"type": "text", "label": "Notes", "count": 4},
        {"type": "url", "label": "Links", "count": 1}, {"type": "voice", "label": "Voice", "count": 2},
    ]
    assert result["filters"][1] == result["filters"][2] == [{"type": "", "label": "All", "count": 0}]


def test_priority_calendar_and_dashboard_views(client):
    page = client.get("/").text
    priority = page[page.index('data-view="priority"'):page.index('data-view="dashboard"')]
    # The columns come first; the v1 task list and attention board fold away below.
    assert priority.index('id="priorityBoard"') < priority.index('id="priorityBacklog"')
    assert priority.index('id="priorityBacklog"') < priority.index('id="tasks"')
    assert priority.index('id="tasks"') < priority.index('id="attention"')
    assert priority.count('<details class="view-card folded"') == 2
    # + Add task holds today's quick task form; task messages show at the top.
    panel = priority[priority.index('id="addTaskPanel"'):priority.index('id="priorityBoard"')]
    assert 'id="quickTaskForm"' in panel
    assert priority.index('id="taskStatus"') < priority.index('id="addTaskPanel"')
    dashboard = page[page.index('data-view="dashboard"'):page.index('data-view="ask"')]
    assert dashboard.index('id="glanceView"') < dashboard.index('id="dashboard"')
    # The calendar's day list is a pop-up, closed until a day is clicked.
    assert re.search(r'id="calendarDayDetails"[^>]*role="dialog"[^>]*hidden', page)
    assert "data-close-day" in page
    # Related items moved to each note's page (change 009); the dashboard no longer lists them.
    assert "Related Items" not in (STATIC / "app.js").read_text(encoding="utf-8")


@needs_node
def test_timeline_and_priority_helpers():
    result = run_logic("""
const tasks = [
  {id: 1, status: 'open', priority: 'High', due_on: '2026-11-03', bot_key: 'money'},
  {id: 2, status: 'open', priority: 'Medium', due_on: '2026-11-05', bot_key: 'learn'},
  {id: 3, status: 'open', priority: 'Low', due_on: '2026-11-06', bot_key: 'learn'},
  {id: 4, status: 'open', priority: 'High', due_on: '2026-11-07', bot_key: 'fun'},
  {id: 5, status: 'open', priority: 'Medium', due_on: '2026-11-09'},
  {id: 6, status: 'open', priority: 'Low', due_on: '2026-11-20', bot_key: 'money'},
  {id: 7, status: 'open', priority: 'High', due_on: null, bot_key: 'learn'},
  {id: 8, status: 'open', priority: 'Medium', due_on: '2026-11-06', snoozed_until: '2026-11-10'},
  {id: 9, status: 'completed', priority: 'High', due_on: '2026-11-05'},
];
const split = S.prioritySplit(tasks, '2026-11-05');
const bots = [{key: 'learn', name: 'Learning & work'}, {key: 'money', name: 'Money & home'}, {key: 'fun', name: 'Fun & interests'}];
console.log(JSON.stringify({
  month: [S.monthDays(new Date(2026, 1, 10)).length, S.monthDays(new Date(2026, 10, 5))[0], S.monthDays(new Date(2026, 10, 5)).slice(-1)[0]],
  shift: [S.shiftAnchor('2026-11-05', 'week', 1), S.shiftAnchor('2026-11-05', 'week', -1),
          S.shiftAnchor('2026-01-31', 'month', 1), S.shiftAnchor('2026-01-15', 'month', -1)],
  board: split.board.map(t => t.id),
  backlog: split.backlog.map(t => t.id),
  columns: S.priorityColumns(split.board).map(c => [c.priority, c.tasks.map(t => t.id)]),
  groups: S.groupByArea(split.board, bots).map(g => [g.key, g.tasks.map(t => t.id)]),
}));
""")
    assert result["month"] == [28, "2026-11-01", "2026-11-30"]
    assert result["shift"] == ["2026-11-12", "2026-10-29", "2026-02-01", "2025-12-01"]
    # Overdue and today, then the next 3 dated; snoozed, later and undated wait.
    assert result["board"] == [1, 2, 3, 4, 5]
    assert result["backlog"] == [8, 6, 7]
    assert result["columns"] == [["High", [1, 4]], ["Medium", [2, 5]], ["Low", [3]]]
    assert result["groups"] == [["learn", [2, 3]], ["money", [1]], ["fun", [4]], [None, [5]]]



def test_capture_from_anywhere_and_hover_cards(client):
    page = client.get("/").text
    header = page[page.index('class="shell-header"'):page.index("</header>")]
    # "+ New note" (and the N key) open the composer from any view.
    assert re.search(r'id="newNoteButton"[^>]*data-new-note[^>]*aria-keyshortcuts="N"', header)
    assert header.index('id="newNoteButton"') < header.index('id="globalSearchForm"')
    # One composer: docked on Home, floating elsewhere, with its own close button.
    assert page.count('id="captureCard"') == 1 and page.count('id="noteText"') == 1
    composer = page[page.index('id="captureCard"'):page.index('class="views"')]
    assert "data-close-capture" in composer
    for element in ('id="captureFab"', 'id="captureBackdrop"', 'id="hoverCard" class="hover-card" role="tooltip"', 'id="toast"'):
        assert element in page, element
    css = (STATIC / "shell.css").read_text(encoding="utf-8")
    assert 'body[data-view]:not([data-view="home"]) .pane-center > .capture-card:not(.is-floating) { display: none; }' in css
    # Every kind of capture tells the shell it was saved: notes, sources and voice.
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert app_js.count("notifyCaptured(") == 4  # the helper and its 3 callers


@needs_node
def test_hover_card_text():
    result = run_logic("""
const topics = [
  {id: 1, name: 'Study', bot_key: 'learn', item_count: 1, total_item_count: 3, description: '  Courses and exams ', is_built_in: true},
  {id: 2, name: 'Python', bot_key: 'learn', parent_topic_id: 1, item_count: 2},
  {id: 3, name: 'Old', parent_topic_id: 1, archived: true},
  {id: 4, name: 'Chess', bot_key: null, item_count: 0, total_item_count: 0},
];
const bots = {learn: {key: 'learn', name: 'Learning & work'}};
const long = 'Groceries for the week: ' + 'milk, eggs and bread '.repeat(20);
console.log(JSON.stringify({
  study: S.topicHover(topics[0], topics, bots),
  chess: S.topicHover(topics[3], topics, bots),
  missing: S.topicHover(undefined, topics, bots),
  short: S.notePreview({item_type: 'text', raw_text: 'Pay the electricity bill', created_at: '2026-11-04T20:00:00+00:00'}),
  long: S.notePreview({item_type: 'text', raw_text: long, created_at: '2026-11-05T09:00:00Z'}),
  link: S.notePreview({item_type: 'url', title: 'Python course', extracted_text: 'A course on Python basics.',
                       user_context: 'for learning Python', created_at: '2026-11-05T09:00:00Z', processing_status: 'ready'}),
  failed: S.notePreview({item_type: 'pdf', original_filename: 'scan.pdf', created_at: 'nope', processing_status: 'failed'}),
  titles: [S.noteTitle({raw_text: '  First line\\nsecond'}), S.noteTitle({original_filename: 'a.pdf'}), S.noteTitle(null)],
}));
""", timezone="Asia/Kolkata")
    assert result["study"] == {
        "name": "Study", "area": "Learning & work", "count": "3 notes, 2 in subtopics",
        "description": "Courses and exams", "subtopics": ["Python"], "builtIn": True,
    }
    assert result["chess"]["area"] == "Not in an area yet" and result["chess"]["count"] == "No notes yet"
    assert result["missing"] is None
    # A typed note shows its text once, on the day it was saved in the user's time zone.
    assert result["short"] == {"kind": "text", "title": "", "savedOn": "Thu 5 Nov", "note": "",
                               "excerpt": "Pay the electricity bill", "failed": False}
    assert len(result["long"]["excerpt"]) <= 220 and result["long"]["excerpt"].endswith("…")
    # A source keeps its own title, your note, then the start of its content.
    assert result["link"]["title"] == "Python course" and result["link"]["note"] == "for learning Python"
    assert result["link"]["excerpt"] == "A course on Python basics."
    assert result["failed"]["failed"] and result["failed"]["savedOn"] == "" and result["failed"]["title"] == "scan.pdf"
    assert result["titles"] == ["First line", "a.pdf", "Untitled note"]



def test_dates_can_be_changed_from_where_you_see_them(client):
    page = client.get("/").text
    assert re.search(r'id="datePicker" class="date-picker" role="dialog"[^>]*hidden', page)
    shell = (STATIC / "shell.js").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    # Date chips (task rows, priority cards) open the picker; so do task cards
    # and the Calendar pop-up ("Postpone").
    assert shell.count("= dateChip(task)") == 2  # task rows and priority cards
    assert "dateButton.dataset.dateTask" in app_js and "moveBtn.dataset.dateTask" in app_js
    assert "/api/tasks/${task.id}/date" in shell
    # An edit and the re-filing that follows are announced, so a moved date is asked about.
    assert "notifyEdited(note.id)" in app_js and app_js.count("notifyEdited(note.id)") == 2
    assert "lifeinbox:analyzed" in app_js and "askAboutMovedDates" in shell
    # The old one-off date box is gone.
    assert "askTaskDate" not in shell and "data-set-date" not in shell


@needs_node
def test_postpone_choices_are_always_later():
    result = run_logic("""
console.log(JSON.stringify([
  S.postponeChoices('2026-11-12', '2026-11-07'),
  S.postponeChoices('2026-11-07', '2026-11-07'),
  S.postponeChoices('2026-11-06', '2026-11-07'),
  S.postponeChoices(null, '2026-11-07'),
  S.postponeChoices('2026-12-31', '2026-11-07'),
  S.addDays('2026-02-28', 1),
]));
""")
    assert result == [
        [{"label": "A day later", "iso": "2026-11-13"}, {"label": "A week later", "iso": "2026-11-19"}],
        [{"label": "Tomorrow", "iso": "2026-11-08"}, {"label": "Next week", "iso": "2026-11-14"}],
        [{"label": "Tomorrow", "iso": "2026-11-08"}, {"label": "Next week", "iso": "2026-11-14"}],
        [{"label": "Tomorrow", "iso": "2026-11-08"}, {"label": "Next week", "iso": "2026-11-14"}],
        [{"label": "A day later", "iso": "2027-01-01"}, {"label": "A week later", "iso": "2027-01-07"}],
        "2026-03-01",
    ]


@needs_node
@pytest.mark.parametrize("timezone", ["Asia/Kolkata", "America/Los_Angeles", "UTC"])
def test_where_a_date_stands_and_the_small_calendar(timezone):
    """Change 012: the three ways a date can stand, the day a task sits on, the
    Priority board's due-soon raise, and the picker's month (in any time zone)."""
    result = run_logic("""
const today = '2026-11-07';
const confirmed = {due_on: '2026-11-13', timing_confirmed: true};
const note = {due_on: '2026-11-12', timing_confirmed: false};
const guess = {due_on: null, suggested_due_on: '2026-11-07'};
const none = {due_on: null, suggested_due_on: null};
const raise = (priority, due_on, extra) => S.boardPriority(Object.assign({priority, due_on}, extra || {}), today);
const nov = S.monthGrid('2026-11-20');
const feb = S.monthGrid('2027-02-14');
console.log(JSON.stringify({
  states: [confirmed, note, guess, none, null].map(S.dateState),
  days: [confirmed, note, guess, none].map(S.taskDay),
  raised: [
    raise('Low', '2026-11-08'),                           // tomorrow: one step up
    raise('Medium', '2026-11-07'),                        // today
    raise('Medium', '2026-11-01'),                        // overdue
    raise('High', '2026-11-07'),                          // already at the top
    raise('Low', '2026-11-09'),                           // two days away: not yet
    raise('Low', '2026-11-08', {user_priority: 'Low'}),   // your pick is never changed
    raise('Low', null, {suggested_due_on: '2026-11-07'}), // a guess doesn't raise
  ],
  nov: {title: nov.title, month: nov.month, weeks: nov.weeks.length,
        first: nov.weeks[0][0], last: nov.weeks[5][6],
        inMonth: nov.weeks.flat().filter(day => day.inMonth).length},
  feb: {title: feb.title, weeks: feb.weeks.length, first: feb.weeks[0][0].iso},
  clip: [S.clip('Book the train tickets to Pune next Monday', 20), S.clip('  short  ', 20)],
}));
""", timezone=timezone)
    assert result["states"] == ["confirmed", "note", "suggested", "none", "none"]
    assert result["days"] == ["2026-11-13", "2026-11-12", "2026-11-07", None]
    assert result["raised"] == [
        {"priority": "Medium", "raised": True},
        {"priority": "High", "raised": True},
        {"priority": "High", "raised": True},
        {"priority": "High", "raised": False},
        {"priority": "Low", "raised": False},
        {"priority": "Low", "raised": False},
        {"priority": "Low", "raised": False},
    ]
    # November 2026 starts on a Sunday: Monday-first weeks run 26 Oct to 6 Dec.
    assert result["nov"] == {
        "title": "November 2026", "month": "2026-11-01", "weeks": 6,
        "first": {"iso": "2026-10-26", "day": 26, "inMonth": False},
        "last": {"iso": "2026-12-06", "day": 6, "inMonth": False},
        "inMonth": 30,
    }
    # February 2027 starts on a Monday and fills exactly four weeks.
    assert result["feb"] == {"title": "February 2027", "weeks": 4, "first": "2027-02-01"}
    assert result["clip"] == ["Book the train tick…", "short"]


def test_dates_show_where_they_came_from(client):
    shell = (STATIC / "shell.js").read_text(encoding="utf-8")
    chip = shell[shell.index("function dateChip(task)"):shell.index("async function openDatePicker")]
    # Three chip styles plus "No date", each with hover text saying where the date came from.
    for cls, tip in (("chip chip-confirmed", "Confirmed by you"), ("chip chip-dashed", "Suggested from your words"),
                     ("'chip'", "From your note"), ("chip chip-muted", "No date yet")):
        assert cls in chip and tip in chip
    # Right after you save a note, each guessed date gets the question: a card in
    # the middle of a dimmed page (a toast at the bottom was easy to miss).
    assert "capturedNotes.add(" in shell and "askAboutNewDates(" in shell
    ask = shell[shell.index("async function askAboutNewDates"):shell.index("// --- Capture from anywhere")]
    assert "for (const task of guesses) queueDateQuestion(" in ask and "sticky: true" not in ask
    moved = shell[shell.index("async function askAboutMovedDates"):shell.index("async function askAboutNewDates")]
    assert "queueDateQuestion({kind: 'moved'" in moved and "showToast(" not in moved
    question = shell[shell.index("function drawDateQuestion"):shell.index("function answerDateQuestion")]
    for hook in ("data-ask-yes", "data-ask-change", "data-ask-later", "Is this the right day?", "Your edit moved a date"):
        assert hook in question
    assert re.search(r'id="datePickerBackdrop" class="date-backdrop" data-ask-later hidden', client.get("/").text)
    opener = shell[shell.index("async function openDatePicker"):shell.index("function drawDatePicker")]
    # While you're typing, Yes isn't focused, so a keystroke can't answer for you.
    assert "isTyping(returnFocus) ? picker :" in opener and "$('datePickerBackdrop').hidden = !ask" in opener
    assert "document.addEventListener('keydown', trapDateFocus)" in shell
    # A date left for later stays in Captain's "Needs you" list (change 013).
    assert "api('/api/captain/needs-you')" in shell


def test_captain_card_shows_the_needs_you_list(client):
    shell = (STATIC / "shell.js").read_text(encoding="utf-8")
    card = shell[shell.index("function needCard(card)"):shell.index("function needById")]
    # Each card: its kind's heading, the note (a link to it), the question, one-tap answers.
    for hook in ("card.heading", "data-open-note", "data-need-action", "data-need-value", "data-need-note"):
        assert hook in card
    answer = shell[shell.index("async function answerNeed"):shell.index("async function saveNeedNote")]
    # Dates use the date question; "Set date" the picker; Delete asks twice; the rest the server.
    for hook in ("queueDateQuestion(", "openDatePicker(card.task_id", "button.dataset.armed", "/retry", "resolveNeed(card, action, value)"):
        assert hook in answer
    assert "state.needsYou.total" in shell and "NEEDS_SHOWN = 5" in shell
    # The picker opens beside its chip, in the middle without one, and as a sheet on phones.
    place = shell[shell.index("function placeDatePicker"):shell.index("function closeDatePicker")]
    assert "is-sheet" in place and "(window.innerWidth - width) / 2" in place


@needs_node
def test_calendar_page_parts_and_dates_waiting_for_you():
    result = run_logic("""
const tasks = [
  {id: 1, status: 'open', due_on: null, suggested_due_on: '2026-11-13'},
  {id: 2, status: 'open', due_on: '2026-11-08', timing_confirmed: false},
  {id: 3, status: 'open', due_on: null, suggested_due_on: '2026-11-08'},
  {id: 4, status: 'completed', due_on: null, suggested_due_on: '2026-11-07'},
  {id: 5, status: 'open', due_on: null, suggested_due_on: null},
];
console.log(JSON.stringify({
  waiting: S.waitingDates(tasks).map(task => task.id),
  none: S.waitingDates(null),
  page: S.dayParts('2026-11-08'),
  leap: S.dayParts('2028-02-29'),
  bad: S.dayParts('soon'),
}));
""", timezone="Asia/Kolkata")
    # Only open guesses wait for your OK, soonest first.
    assert result["waiting"] == [3, 1]
    assert result["none"] == []
    assert result["page"] == {"weekday": "Sun", "weekdayLong": "Sunday", "day": 8, "month": "Nov", "year": 2026}
    assert result["leap"] == {"weekday": "Tue", "weekdayLong": "Tuesday", "day": 29, "month": "Feb", "year": 2028}
    assert result["bad"] is None


def test_front_end_dates_are_local_days():
    # "Snooze 1 day" took tomorrow from a UTC date, which is still yesterday in
    # India until 05:30, so it only snoozed until later the same day. Every
    # calendar day the browser works out must be the user's own local day.
    for name in ("app.js", "shell.js", "shell_logic.js"):
        source = (STATIC / name).read_text(encoding="utf-8")
        for utc_day_math in ("setUTCDate(", "getUTCDate(", "toISOString().slice(0, 10)"):
            assert utc_day_math not in source, f"{name}: {utc_day_math}"
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    snooze = app_js[app_js.index("actionButton('Remind me tomorrow'"):app_js.index("/api/tasks/${task.id}/snooze")]
    assert "until.setDate(until.getDate() + 1)" in snooze and "toCalendarIsoDate(until)" in snooze
    # Change 018: renamed from "Snooze 1 day", and not offered on a task at a set time.
    assert "Snooze 1 day" not in app_js
    before = app_js[:app_js.index("actionButton('Remind me tomorrow'")]
    assert before.rstrip().endswith("if (!task.due_time) actions.append(")


@needs_node
def test_memory_groups_and_masked_notes():
    # Change 016: facts grouped by area (across-areas first), and a note that
    # holds a secret shows its masked copy in titles and hover cards.
    result = run_logic("""
const bots = [{key: 'learn', name: 'Learning & work'}, {key: 'health', name: 'Health'}];
const facts = [
  {id: 1, bot_key: 'health', status: 'confirmed'}, {id: 2, bot_key: null, status: 'suggested'},
  {id: 3, bot_key: 'learn', status: 'expired'}, {id: 4, bot_key: 'travel', status: 'confirmed'},
];
const item = {id: 9, item_type: 'text', created_at: '2026-11-09T10:00:00', title: null,
  raw_text: 'wifi password: x1y2z3', secret_masked: {title: null, raw_text: 'wifi password: \u2022\u2022\u2022\u2022'}};
console.log(JSON.stringify({
  groups: S.memoryGroups(facts, bots).map(g => [g.key, g.name, g.facts.map(f => f.id)]),
  status: facts.map(S.memoryStatus),
  title: S.noteTitle(item),
  excerpt: S.notePreview(item).excerpt,
  plain: S.noteTitle({raw_text: 'Buy milk'}),
}));
""")
    assert result["groups"] == [[None, "Across your areas", [2, 4]], ["learn", "Learning & work", [3]],
                                ["health", "Health", [1]]]
    assert result["status"] == ["", "Not confirmed yet", "Past", ""]
    assert result["title"] == result["excerpt"] == "wifi password: ••••"
    assert result["plain"] == "Buy milk"


@needs_node
def test_someday_stays_off_the_board_and_done_shows_on_its_day():
    # Change 018: Someday tasks are kept apart; Timeline's ✓ goes on the local
    # day a task was done, only up to today (decision F).
    result = run_logic("""
const tasks = [
  {id: 1, status: 'open', text: 'Board', due_on: '2026-11-09', priority: 'High'},
  {id: 2, status: 'open', text: 'Someday', someday: true, someday_since: '2026-11-01T10:00:00'},
  {id: 3, status: 'open', text: 'Backlog'},
];
const done = [
  {id: 4, status: 'completed', text: 'Quiz', completed_at: '2026-11-03T09:00:00'},
  {id: 5, status: 'completed', text: 'Future?', completed_at: '2026-11-12T09:00:00'},
  {id: 6, status: 'open', text: 'Open', completed_at: null},
];
const split = S.prioritySplit(tasks, '2026-11-09');
const days = ['2026-11-03', '2026-11-09', '2026-11-12'];
console.log(JSON.stringify({
  board: split.board.map(t => t.id), backlog: split.backlog.map(t => t.id),
  someday: S.somedayTasks(tasks).map(t => t.id),
  done: S.doneByDay(done, days, '2026-11-09'),
}));
""")
    assert result["board"] == [1] and result["backlog"] == [3] and result["someday"] == [2]
    assert result["done"] == {"2026-11-03": [{"id": 4, "text": "Quiz"}], "2026-11-09": [], "2026-11-12": []}
