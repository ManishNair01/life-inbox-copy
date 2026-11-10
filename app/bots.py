"""The five life areas ("life bots") and their default topics.

From docs/research-life-categories.md: §3 gives the areas, their three default
topics and what belongs in each; §6.2 gives the "about" text the AI reads.
Every bot starts with exactly three default topics, and users can add as many
topics and subtopics as they like. Every topic belongs to one bot.

Pure data and small helpers only: nothing here touches the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DefaultTopic:
    name: str
    description: str
    # A built-in subtopic names its parent (Hobbies › Cooking).
    parent: Optional[str] = None


@dataclass(frozen=True)
class Bot:
    key: str
    name: str
    description: str  # one line, for people
    about: str  # what belongs here and what doesn't, for the AI
    topics: tuple[DefaultTopic, ...]


BOTS: tuple[Bot, ...] = (
    Bot(
        key="learn",
        name="Learning & work",
        description="What you study, earn a living from, or build skills for.",
        about=(
            "Things the user studies, earns a living from, or is building skills for: "
            "classes, quizzes, exams, assignments, study material, college admin and clubs "
            "or events they help run, jobs, internships, interviews, meetings, work trips, "
            "side projects, and app or startup ideas. Not here: paying course fees (Money & "
            "home), leisure reading or videos (Fun & interests), a child's school (People)."
        ),
        topics=(
            DefaultTopic("Study", "Courses, exams, assignments, study notes, and college life you take part in (admin, clubs, events)."),
            DefaultTopic("Work & career", "Job or internship tasks, meetings, interviews, applications, salary talks, colleagues, work travel."),
            DefaultTopic("Skills & projects", "Self-directed learning, tutorials, tools to try, side projects, app and startup ideas."),
        ),
    ),
    Bot(
        key="money",
        name="Money & home",
        description="Running your household and your own money.",
        about=(
            "Running the user's household and their own money: rent, bills, EMIs, "
            "subscriptions and memberships (paying, renewing, cancelling), fees, bank, salary "
            "received, savings, tax, insurance, IDs such as passport or licence, warranties, "
            "groceries, shopping, chores, repairs, appliances, car, pets, and household info. "
            "Not here: a college's or employer's budget (Learning & work), gifts for someone "
            "(People), bookings for a specific trip (Fun & interests), medicines (Health)."
        ),
        topics=(
            DefaultTopic("Bills & subscriptions", "Anything you pay or cancel on a schedule: rent, bills, EMIs, subscriptions, memberships, fees."),
            DefaultTopic("Bank, tax & documents", "Accounts, savings, salary received, investments, tax filing, insurance policies, IDs, warranties."),
            DefaultTopic("Home & errands", "Groceries, shopping, chores, repairs, appliances, vehicle, pets, household info."),
        ),
    ),
    Bot(
        key="health",
        name="Health",
        description="Your body and mind, plus the medical needs of people you care for.",
        about=(
            "The user's body and mind, and medical needs of people they care for: medicines "
            "and pill schedules, refills, doctor, dentist and lab visits, symptoms, checkups, "
            "workouts, sports routines, diet, sleep, stress, therapy, meditation, and personal "
            "reflection or journaling. Not here: paying gym or insurance bills (Money & home), "
            "pet vet visits (Money & home), recipes to try for fun (Fun & interests)."
        ),
        topics=(
            DefaultTopic("Medicines & doctors", "Pills, doses, refills, appointments, tests, checkups, prescriptions."),
            DefaultTopic("Fitness & food", "Workouts, sports routines, steps, sleep, diet and nutrition goals."),
            DefaultTopic("Mind & mood", "Feelings, stress, therapy, meditation, journaling, faith or reflection practice."),
        ),
    ),
    Bot(
        key="people",
        name="People",
        description="Your relationships and the occasions you share.",
        about=(
            "The user's relationships and shared occasions: family, partner, friends, calls or "
            "messages to make, kids' school and care, birthdays, anniversaries, weddings, dates, "
            "parties, gifts, invitations, and community or religious gatherings. Not here: "
            "medical care for a family member (Health), trips with friends (Fun & interests), "
            "events the user organises for college or work (Learning & work)."
        ),
        topics=(
            DefaultTopic("Family", "Parents, siblings, spouse, kids: their needs, school, family plans."),
            DefaultTopic("Friends & partner", "Friends, boyfriend/girlfriend, catch-ups, people to call or message."),
            DefaultTopic("Occasions & gifts", "Birthdays, anniversaries, weddings, dates, parties, gatherings, gifts, invites."),
        ),
    ),
    Bot(
        key="fun",
        name="Fun & interests",
        description="What you do for enjoyment and curiosity.",
        about=(
            "What the user does for enjoyment and curiosity: shows, films, books, podcasts, "
            "music, videos to watch later, quotes they liked, recipes to try, cooking, games, "
            "crafts and other hobbies, holidays, trip plans and bookings, visas for a trip, "
            "packing, and places or restaurants to visit. Not here: study or work material "
            "(Learning & work), diet plans (Health), weekly groceries (Money & home), work "
            "trips (Learning & work)."
        ),
        topics=(
            DefaultTopic("Watch, read & listen", "Your media queue, plus quotes and highlights from it."),
            DefaultTopic("Hobbies", "Games, crafts, music you play, sport, collecting and other creative pursuits."),
            DefaultTopic("Cooking", "Recipes to try, dishes to cook, cooking ideas and kitchen tips.", parent="Hobbies"),
            DefaultTopic("Trips & places", "Holidays, itineraries, bookings, trip visas, packing, places to visit."),
        ),
    ),
)

BOT_KEYS: tuple[str, ...] = tuple(bot.key for bot in BOTS)
BOTS_BY_KEY: dict[str, Bot] = {bot.key: bot for bot in BOTS}
DEFAULT_TOPIC_BOT: dict[str, str] = {
    topic.name: bot.key for bot in BOTS for topic in bot.topics
}
DEFAULT_TOPIC_DESCRIPTIONS: dict[str, str] = {
    topic.name: topic.description for bot in BOTS for topic in bot.topics
}
DEFAULT_TOPIC_PARENT: dict[str, str] = {
    topic.name: topic.parent for bot in BOTS for topic in bot.topics if topic.parent
}

# The v1 catch-all. Kept, with no bot, until change 014 re-sorts its notes into
# real topics and removes it: today's (v1) filing still falls back to it.
LEGACY_CATCH_ALL = "Personal / Reference"
LEGACY_CATCH_ALL_DESCRIPTION = "Everything else worth remembering for later."

# Offline matching, first match wins: v1's keyword rules moved onto the new
# default topics (design §4.1 "Moving from v1"), with the keywords the research
# assigns elsewhere moved (tax, insurance, passport; workouts and diet;
# birthdays; family). Change 014 rewrites this in rule order R1-R6.
DEFAULT_TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Work & career", ("team", "meeting", "architecture", "recruiter", "finance", "interview", "document")),
    ("Bills & subscriptions", ("bill", "domain", "reimbursement")),
    ("Bank, tax & documents", ("tax", "insurance", "ca ", "passport")),
    ("Mind & mood", ("therapy", "therapist", "stress", "meditat")),
    ("Watch, read & listen", ("movie", "podcast", "song")),
    ("Study", ("read", "watch", "lecture", "article", "learn", "vector database", "prompt injection")),
    ("Home & errands", ("buy", "groceries", "pick up", "order", "dry cleaning")),
    ("Medicines & doctors", (
        "dentist", "health", "doctor", "medicine", "medication", "pill", "tablet", "dose",
        "dosage", "prescription", "pharmacy", "vitamin", "hospital", "clinic",
    )),
    ("Fitness & food", ("workout", "fitness", "gym", "diet")),
    ("Cooking", ("recipe", "cook")),
    ("Hobbies", ("guitar", "piano", "chess", "hobby", "craft", "painting")),
    ("Trips & places", ("trip", "travel", "hotel", "jaipur", "flight", "visa")),
    ("Skills & projects", ("idea", "build", "app", "startup", "product")),
    ("Occasions & gifts", ("birthday",)),
    ("Family", ("papa", "mom", "family")),
    ("Friends & partner", ("call", "ask", "rohan", "friend")),
)


def match_default_topic(text: str) -> Optional[tuple[str, str]]:
    """(default topic, matched keyword) for the first rule that fits, else None."""
    lowered = (text or "").lower()
    for name, markers in DEFAULT_TOPIC_RULES:
        for marker in markers:
            if marker in lowered:
                return name, marker.strip()
    return None


def bot_for_text(text: str) -> Optional[str]:
    """The bot whose default topic's keywords appear in the text, if any."""
    match = match_default_topic(text)
    return DEFAULT_TOPIC_BOT[match[0]] if match else None


def bot_ref(key: Optional[str]) -> Optional[dict]:
    bot = BOTS_BY_KEY.get(key or "")
    return {"key": bot.key, "name": bot.name} if bot else None
