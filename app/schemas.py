from typing import Dict, List, Literal, Optional, Set
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class NoteText(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def reject_whitespace_only_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Note text must contain non-whitespace characters")
        return value


class NoteCreate(NoteText):
    pass


class NoteUpdate(NoteText):
    pass


class Note(BaseModel):
    id: int
    text: str
    created_at: str


class InboxItemText(BaseModel):
    raw_text: str = Field(min_length=1, max_length=2000)

    @field_validator("raw_text")
    @classmethod
    def reject_whitespace_only_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Item text must contain non-whitespace characters")
        return value


class InboxItemCreate(InboxItemText):
    pass


class InboxItemUpdate(InboxItemText):
    pass


class ItemContextUpdate(BaseModel):
    """Your note on a saved source (change 023); empty removes it."""

    model_config = ConfigDict(extra="forbid")

    context: Optional[str] = Field(default=None, max_length=2000)


class ItemContextResult(BaseModel):
    item: "InboxItem"
    refiled: bool


class InboxItem(BaseModel):
    # Change 016: the note seems to hold a secret; the screen hides it until you tap.
    looks_secret: bool = False
    secret_masked: Optional[dict] = None
    # Change 022: a long PDF's one-time AI summary (AI output, kept apart).
    source_summary: Optional[str] = None
    # Change 015: what code read from a saved link; and, for a link saved
    # again, the earlier note it reused (no fetch) and whether its filing was
    # reused too (no AI call).
    link_card: Optional[Dict[str, object]] = None
    reused_from: Optional[int] = None
    filing_reused: bool = False

    id: int
    item_type: str
    title: Optional[str]
    raw_text: Optional[str]
    source_url: Optional[str]
    original_filename: Optional[str]
    mime_type: Optional[str]
    processing_status: str
    error_message: Optional[str] = None
    storage_path: Optional[str] = None
    extracted_text: Optional[str] = None
    ai_description: Optional[str] = None
    # The user's own note about why they saved the source.
    user_context: Optional[str] = None
    owner_user_id: Optional[int] = None
    created_at: str
    updated_at: Optional[str]


NOTE_MAX_LENGTH = 2000


class UrlItemCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    # Optional note from the composer: why the user is saving this link.
    context: Optional[str] = Field(default=None, max_length=NOTE_MAX_LENGTH)


class ExtractedTextUpdate(BaseModel):
    extracted_text: str = Field(min_length=0, max_length=20000)


Priority = Literal["High", "Medium", "Low"]
AnalysisMode = Literal[
    "nvidia_nim",
    "openai",
    "fallback_no_api_call",
    "fallback_after_api_error",
    "empty_inbox",
]


class StrictAnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisNote(StrictAnalysisModel):
    id: int
    title: str = Field(min_length=1)
    priority: Priority
    tags: List[str] = Field(default_factory=list)
    rationale: Optional[str] = None


class AnalysisBucket(StrictAnalysisModel):
    name: str = Field(min_length=1)
    notes: List[AnalysisNote]


class AnalysisTodo(StrictAnalysisModel):
    task: str = Field(min_length=1)
    priority: Priority
    source_note_ids: List[int] = Field(min_length=1)
    when: Optional[str] = None


class AnalysisPriorityItem(StrictAnalysisModel):
    id: int
    title: str = Field(min_length=1)


class AnalysisPriorityView(StrictAnalysisModel):
    High: List[AnalysisPriorityItem]
    Medium: List[AnalysisPriorityItem]
    Low: List[AnalysisPriorityItem]


class AnalysisResult(StrictAnalysisModel):
    buckets: List[AnalysisBucket]
    todos: List[AnalysisTodo]
    priority_view: AnalysisPriorityView
    mode: AnalysisMode

    @model_validator(mode="after")
    def validate_consistent_item_views(self):
        bucket_ids = [
            note.id
            for bucket in self.buckets
            for note in bucket.notes
        ]
        priority_ids = [
            item.id
            for level in ("High", "Medium", "Low")
            for item in getattr(self.priority_view, level)
        ]
        if len(bucket_ids) != len(set(bucket_ids)):
            raise ValueError("Each item must appear in exactly one bucket")
        if len(priority_ids) != len(set(priority_ids)):
            raise ValueError(
                "Each item must appear once in the priority view"
            )
        if set(bucket_ids) != set(priority_ids):
            raise ValueError(
                "Bucket and priority views must contain the same items"
            )
        return self

    def validate_for_item_ids(self, expected_ids: Set[int]) -> None:
        bucket_ids = {
            note.id
            for bucket in self.buckets
            for note in bucket.notes
        }
        if bucket_ids != expected_ids:
            raise ValueError(
                "Analysis item IDs must match the current inbox"
            )
        todo_source_ids = {
            item_id
            for todo in self.todos
            for item_id in todo.source_note_ids
        }
        if not todo_source_ids <= expected_ids:
            raise ValueError("ToDos reference unknown inbox items")


class PersistedAnalysis(AnalysisResult):
    analysis_run_id: int
    generated_at: str
    is_stale: bool = False
    inbox_fingerprint: Optional[str] = None


TaskStatus = Literal["open", "completed", "dismissed"]
TaskListStatus = Literal["open", "completed", "dismissed", "all"]


class Task(BaseModel):
    id: int
    text: str
    # Yours when you chose one (user_priority), else the AI's (ai_priority).
    priority: Priority
    ai_priority: Optional[Priority] = None
    user_priority: Optional[Priority] = None
    # From the first source note: its life area, and the AI's reason for it.
    bot_key: Optional[str] = None
    reason: Optional[str] = None
    timing_text: Optional[str]
    ai_timing_text: Optional[str] = None
    timing_confirmed: bool = False
    due_on: Optional[str] = None
    due_time: Optional[str] = None
    # Where the date stands (change 012): "from_note" (your words name the
    # day), "suggested" (a guess, in suggested_due_on, waiting for your OK) or
    # "user_confirmed"; None when there is no date.
    due_confidence: Optional[str] = None
    suggested_due_on: Optional[str] = None
    suggested_due_time: Optional[str] = None
    snoozed_until: Optional[str] = None
    reminder_at: Optional[str] = None
    status: TaskStatus
    source_item_ids: List[int]
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    # Change 018: a task for some day, off your dates and lists.
    someday: bool = False
    someday_since: Optional[str] = None

class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    priority: Priority = "Medium"
    due_on: Optional[date] = None

class TaskDateUpdate(BaseModel):
    """Your date for a task (Postpone / Change date, change 012). It counts as
    confirmed, even if another date was confirmed before."""

    model_config = ConfigDict(extra="forbid")

    due_on: date
    due_time: Optional[str] = Field(default=None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


class NeedsYouAction(BaseModel):
    """One answer on a Needs you card (change 013)."""

    action: str
    label: str
    value: Optional[int | str] = None
    primary: bool = False


class NeedsYouCard(BaseModel):
    """One question from Captain's "Needs you" list (change 013)."""

    id: str
    kind: Literal["date", "moved", "no_date", "failed", "area", "unfiled", "review", "topic_area", "clash", "idea", "plan",
                  "proposal", "fact"]
    heading: str
    title: str
    text: str
    item_id: Optional[int] = None
    task_id: Optional[int] = None
    topic_id: Optional[int] = None
    actions: List[NeedsYouAction]
    data: Dict[str, object] = Field(default_factory=dict)


class AccountDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=256)
    confirm: str = Field(max_length=20)


class OnboardingAnswers(BaseModel):
    """The setup questions (change 024); every one is optional."""

    model_config = ConfigDict(extra="forbid")

    role: Optional[Literal["student", "working", "both", "home", "other"]] = None
    role_other: Optional[str] = Field(default=None, max_length=80)
    city: Optional[str] = Field(default=None, max_length=60)
    focus: List[str] = Field(default_factory=list, max_length=9)
    care: Optional[str] = Field(default=None, max_length=80)
    health_memory_consent: Optional[bool] = None


class Greeting(BaseModel):
    text: str
    ai: bool


class BotSummary(BaseModel):
    bot_key: str
    summary: str
    ai: bool


class ScoutAction(BaseModel):
    action: str
    label: str
    primary: bool = False


class ScoutQuestion(BaseModel):
    id: str
    kind: Literal["past", "undated", "someday"]
    rank: int
    task_id: int
    title: str
    text: str
    actions: List[ScoutAction]
    item_id: Optional[int] = None
    bot_key: Optional[str] = None
    data: dict = {}


class ScoutBulkPlan(BaseModel):
    old_to_someday: List[int]
    past_to_next_week: List[int]


class ScoutState(BaseModel):
    mode: Literal["daily", "weekly", "away"]
    intro: str
    questions: List[ScoutQuestion]
    total: int
    away_days: Optional[int] = None
    catchup_due: bool
    next_catchup: str
    drop_reasons: List[str]
    bulk: ScoutBulkPlan


class ScoutAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["done", "reschedule", "drop", "someday", "keep", "skip"]
    due_on: Optional[date] = None
    due_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    reason: Optional[str] = Field(default=None, max_length=200)


class ScoutResult(BaseModel):
    said: str
    scout: ScoutState
    moved: List[int] = []


class ScoutBulk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    which: Literal["old_to_someday", "past_to_next_week"]


class TaskSomeday(BaseModel):
    model_config = ConfigDict(extra="forbid")

    someday: bool


class MemoryFact(BaseModel):
    """Something Life Inbox learned about you (change 016)."""

    id: int
    bot_key: Optional[str] = None
    kind: Literal["long_term", "short_term", "example"]
    text: str
    source_item_ids: List[int] = []
    source_kind: str
    status: Literal["suggested", "confirmed", "expired", "deleted"]
    times_seen: int
    valid_until: Optional[str] = None
    core_profile: bool = False
    created_at: str
    updated_at: str


class UpcomingPlan(BaseModel):
    task_id: int
    text: str
    due_on: str
    due_time: Optional[str] = None
    confirmed: bool


class MemoryView(BaseModel):
    facts: List[MemoryFact]
    coming_up: List[UpcomingPlan]
    health_memory_consent: bool


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Optional[str] = Field(default=None, min_length=1, max_length=200)
    status: Optional[Literal["confirmed"]] = None
    core_profile: Optional[bool] = None


class UserSettings(BaseModel):
    health_memory_consent: bool
    ai_processing: bool
    catchup_day: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    catchup_time: str
    last_seen_at: Optional[str] = None
    last_catchup_at: Optional[str] = None
    last_weekly_review_at: Optional[str] = None
    onboarding_done: bool


class UserSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    health_memory_consent: Optional[bool] = None
    ai_processing: Optional[bool] = None
    catchup_day: Optional[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] = None
    catchup_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class TaskIdea(BaseModel):
    """An action you didn't commit to yet (change 014a): "tentative" (Captain
    asks first) or "someday" (kept with its note, never asked about)."""

    id: int
    item_id: int
    text: str
    timing_text: Optional[str] = None
    intent: Literal["tentative", "someday"]
    status: Literal["waiting", "added", "dismissed"]
    task_id: Optional[int] = None
    created_at: str


class NeedsYouList(BaseModel):
    cards: List[NeedsYouCard]
    total: int


class NeedsYouResolve(BaseModel):
    """Your answer to a card: "Not now", a pick, a note for a failed capture..."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["not_now", "ignore", "drop", "add_note", "delete", "pick", "done", "add", "move", "different",
                    "create", "never", "yes", "no"]
    value: Optional[int | str] = None

    @field_validator("value")
    @classmethod
    def _short_value(cls, value):
        if isinstance(value, str) and len(value) > 2000:
            raise ValueError("Keep your note under 2000 characters.")
        return value


class TaskDateChange(BaseModel):
    """One change to a task's date, shown as an update on its note."""

    id: int
    task_id: int
    task_text: str
    kind: Literal["set", "postponed", "moved_earlier", "confirmed", "note_edit"]
    from_due_on: Optional[str] = None
    from_due_time: Optional[str] = None
    to_due_on: Optional[str] = None
    to_due_time: Optional[str] = None
    created_at: str
    text: str
    # A date your edit moved that still waits for your OK.
    needs_confirmation: bool = False


class TaskPriorityUpdate(BaseModel):
    """Your priority for a task (Priority view drag); null goes back to the AI's."""

    model_config = ConfigDict(extra="forbid")

    priority: Optional[Priority]

class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Optional[str] = Field(default=None, min_length=1, max_length=500)
    priority: Optional[Priority] = None
    due_on: Optional[date] = None
    clear_due_date: bool = False

    @model_validator(mode="after")
    def require_a_change(self):
        # priority: null on its own is a change: back to Life Inbox's priority.
        if not self.model_fields_set or (
            self.text is None
            and "priority" not in self.model_fields_set
            and self.due_on is None
            and not self.clear_due_date
        ):
            raise ValueError("Nothing to update.")
        if self.due_on is not None and self.clear_due_date:
            raise ValueError("Choose a new date or clear it, not both.")
        return self


class TaskTimingConfirm(BaseModel):
    timing_text: Optional[str] = Field(default=None, max_length=200)


class TaskSnoozeRequest(BaseModel):
    until: str = Field(min_length=8, max_length=32)


class TaskReminderRequest(BaseModel):
    reminder_at: str = Field(min_length=8, max_length=32)


class NotificationPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    daily_digest_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(min_length=1, max_length=64)
    include_unscheduled_prompt: bool = False

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        cleaned = value.strip()
        try:
            ZoneInfo(cleaned)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use a valid IANA timezone name.") from exc
        return cleaned


class PushSubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=10, max_length=4096)
    keys: dict[str, str]

    @field_validator("keys")
    @classmethod
    def validate_keys(cls, value: dict[str, str]) -> dict[str, str]:
        if not value.get("p256dh") or not value.get("auth"):
            raise ValueError("Push subscription must include encryption keys.")
        if len(value["p256dh"]) > 512 or len(value["auth"]) > 512:
            raise ValueError("Push subscription keys are too long.")
        return value


class CalendarPreviewRequest(BaseModel):
    task_id: int
    title: Optional[str] = Field(default=None, max_length=200)
    start_date: Optional[str] = Field(default=None, max_length=32)
    description: Optional[str] = Field(default=None, max_length=2000)


class CalendarConfirmRequest(BaseModel):
    draft_id: str = Field(min_length=4, max_length=80)


class CalendarEvent(BaseModel):
    id: int  # task_id
    title: str
    event_date: str  # YYYY-MM-DD
    priority: Priority
    # The source note's life area, for the dot colour.
    bot_key: Optional[str] = None
    status: TaskStatus
    timing_text: Optional[str] = None
    time_of_day: Optional[str] = None
    timing_confirmed: bool = False
    due_confidence: Optional[str] = None
    needs_confirmation: bool = False
    source_item_id: Optional[int] = None
    source_item_ids: List[int] = Field(default_factory=list)
    source_type: Optional[str] = None
    source_title: Optional[str] = None



class TopicCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=400)
    # Set only after the user accepts a "make it a subtopic of ..." suggestion.
    parent_topic_id: Optional[int] = None
    # The life area (app/bots.py). A subtopic always takes its parent's; when
    # left out, Life Inbox picks one from the name and description.
    bot_key: Optional[str] = Field(default=None, max_length=20)


class TopicParentSuggestionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=400)


class TopicRef(BaseModel):
    id: int
    name: str


class BotRef(BaseModel):
    key: str
    name: str


class TopicParentSuggestion(BaseModel):
    """Advisory only: the topic is never nested unless the user agrees."""

    suggested_parent: Optional[TopicRef] = None
    suggested_bot: Optional[BotRef] = None
    reason: Optional[str] = None
    mode: Literal["ai", "offline", "none"] = "none"


class MovedNote(BaseModel):
    item_id: int
    # None: no topic fitted, so the note waits in Needs you (change 014).
    topic_id: Optional[int] = None
    topic_name: str


class ResortPlan(BaseModel):
    """What "Re-sort everything" would do, before you start it (change 014)."""

    notes: int
    calls: int
    per_call: int
    ai: bool


class ResortResult(BaseModel):
    notes: int
    calls: int
    waiting: int
    retired_catch_all: bool


class TopicMove(BaseModel):
    item_id: int
    title: Optional[str] = None
    # The topic it had before (what Undo puts back); None: it had none.
    topic_id: Optional[int] = None


class TopicRecheck(BaseModel):
    """After you create a topic: the notes that moved into it (change 014)."""

    topic: Dict[str, object]
    moved: List[TopicMove]
    calls: int


class TopicMovesUndo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    moves: List[TopicMove] = Field(max_length=25)


class TopicDeleteResult(BaseModel):
    deleted: TopicRef
    # Set when a subtopic was deleted and its notes moved to the parent.
    moved_to_parent: Optional[TopicRef] = None
    moved_notes: List[MovedNote] = []
    # Subtopics of a deleted main topic become main topics.
    promoted_subtopics: List[TopicRef] = []
    mode: Literal["parent", "ai", "offline", "none"] = "none"


class TopicUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=400)
    archived: Optional[bool] = None
    # Moves a main topic, with its subtopics, to another life area.
    bot_key: Optional[str] = Field(default=None, max_length=20)


class Topic(BaseModel):
    id: int
    name: str
    description: Optional[str]
    archived: bool
    item_count: int = 0
    # item_count plus the notes in this topic's subtopics.
    total_item_count: int = 0
    parent_topic_id: Optional[int] = None
    # The life area (app/bots.py); None means not in an area yet.
    bot_key: Optional[str] = None
    origin: Literal["built_in", "user", "ai"] = "user"
    is_built_in: bool = False
    created_at: str
    updated_at: str
    # Change 020: suggested by an area from these notes, approved by you then.
    proposed_by: Optional[str] = None
    evidence_item_ids: List[int] = []
    approved_at: Optional[str] = None


class GlanceDay(BaseModel):
    date: str
    weekday: str
    count: int


class GlanceRow(BaseModel):
    """A life area (key), or with a lens one of its topics (id)."""

    key: Optional[str] = None
    id: Optional[int] = None
    name: str
    count: int


class GlanceTopic(BaseModel):
    id: int
    name: str
    count: int = 0
    last_on: Optional[str] = None
    days: Optional[int] = None


class GlanceTask(BaseModel):
    id: int
    text: str
    due_on: str
    due_time: Optional[str] = None
    priority: Priority
    bot_key: Optional[str] = None
    timing_confirmed: bool = False
    source_item_id: Optional[int] = None


class Glance(BaseModel):
    """The Dashboard: your life at a glance, worked out by code (change 011)."""

    lens: Optional[str] = None
    week_start: str
    week_end: str
    captured_this_week: int
    tasks_done_this_week: int
    open_tasks: int
    busiest_day: Optional[GlanceDay] = None
    attention_window_days: int
    attention: List[GlanceRow]
    noticed: List[str]
    growing: List[GlanceTopic]
    quiet: List[GlanceTopic]
    coming_up: List[GlanceTask]


class TopicDetail(Topic):
    """One topic for its page: counts, plus its notes (subtopics included) by
    kind, such as {"text": 4, "url": 1}."""

    type_counts: Dict[str, int] = {}


class BotNextTask(BaseModel):
    id: int
    text: str
    due_on: str
    due_time: Optional[str] = None
    # A guessed date, not confirmed yet (shown with "?").
    suggested: bool = False


class LifeBot(BaseModel):
    """One of the five life areas, as shown in the right-hand panel."""

    key: str
    name: str
    description: str
    topic_count: int
    item_count: int
    open_task_count: int
    next_task: Optional[BotNextTask] = None
    status: str


class InsightOverrideUpdate(BaseModel):
    user_title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    user_topic_id: Optional[int] = None
    user_priority: Optional[Priority] = None
    user_tags: Optional[List[str]] = None
    clear_overrides: bool = False
    needs_review: Optional[bool] = None


class ItemInsight(BaseModel):
    item_id: int
    analysis_run_id: int
    category: str
    concise_title: str
    priority: Priority
    topic_id: Optional[int]
    tags: List[str]
    rationale: Optional[str]
    user_title: Optional[str]
    user_topic_id: Optional[int]
    user_priority: Optional[Priority]
    user_tags: Optional[List[str]]
    effective_title: str
    effective_priority: Priority
    effective_topic_id: Optional[int]
    effective_tags: List[str]
    # Filing v2 (change 014): how it was filed, and what the AI added.
    filing_rule: Optional[str] = None
    filing_confidence: Optional[str] = None
    filing_choices: List[int] = []
    filed_by: Optional[str] = None
    filing_pending: bool = False
    ai_summary: Optional[str] = None
    suggested_action: Optional[str] = None
    cleaned_transcript: Optional[str] = None
    # Change 017: the hints from memory the filing call said it used.
    memory_used: List[dict] = []
    needs_review: bool
    updated_at: str
    has_user_overrides: bool


class ItemRelation(BaseModel):
    id: int
    item_id_a: int
    item_id_b: int
    relation_type: str
    score: float
    dismissed: bool
    created_at: str


class SearchHit(BaseModel):
    item_id: int
    item_type: str
    title: str
    excerpt: str
    source_kind: str
    preview_url: Optional[str] = None
    score: float
    keyword_score: float
    semantic_score: float


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    item_type: Optional[str] = Field(default=None, max_length=100)
    # Change 019: the lens (a life area), so only its notes are read.
    bot: Optional[str] = Field(default=None, max_length=20)


class AskCitation(BaseModel):
    id: str
    item_id: int
    item_type: str
    title: str
    excerpt: str
    source_kind: str
    preview_url: Optional[str] = None
    score: float


class AskFact(BaseModel):
    id: int
    text: str
    source_item_ids: List[int] = []


class AskTask(BaseModel):
    task_id: int
    text: str
    day: str
    time: Optional[str] = None
    confirmed: bool
    status: str
    source_item_ids: List[int] = []


class AskClaim(BaseModel):
    claim: str
    citation_ids: List[str]


class AskAction(BaseModel):
    kind: Literal["confirm_date"]
    task_id: int
    due_on: str
    due_time: Optional[str] = None
    label: str


class AskHow(BaseModel):
    """How I answered (change 019)."""

    areas: List[str] = []
    lens: Optional[str] = None
    notes_read: List[int] = []
    facts_considered: int = 0
    memory_used: int = 0
    tasks_read: int = 0
    period: Optional[str] = None
    ai_calls: int = 0


class AskResponse(BaseModel):
    question: str
    answer: str
    confidence: Literal["high", "medium", "insufficient"]
    citations: List[AskCitation]
    answer_kind: Literal["grounded_summary", "model_generated"]
    mode: Literal["llm_grounded", "extractive_fallback"] = "extractive_fallback"
    # Change 019: remembered facts and tasks it used, per-claim citations,
    # actions you can tap, and how it answered.
    facts: List[AskFact] = []
    tasks: List[AskTask] = []
    claims: List[AskClaim] = []
    suggested_actions: List[AskAction] = []
    how: Optional[AskHow] = None


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(default="", max_length=100)
    confirm_adult: bool = False
    accept_terms: bool = False
    # Change 025 (decision Q): the sign-up box (unticked means off). Left out
    # by older clients, it stays on, as for existing accounts.
    ai_processing: Optional[bool] = None


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class AuthUser(BaseModel):
    id: int
    email: Optional[str] = None
    display_name: str
    auth_provider: str
    created_at: str


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=1, max_length=254)


class ForgotPasswordResponse(BaseModel):
    status: Literal["code_sent_if_account_exists"] = "code_sent_if_account_exists"
    resend_after_seconds: int
    delivery: str


class ResetPasswordRequest(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    code: str = Field(min_length=1, max_length=20)
    new_password: str = Field(min_length=1, max_length=256)


ItemContextResult.model_rebuild()
