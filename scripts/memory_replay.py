"""Memory replay (change 017): does memory make filing better against the real AI?

Files each made-up scenario note twice, without memory and with it, on a fresh
throwaway database, and prints a Markdown table to compare. It never opens
data/life_inbox.db, and it spends AI credits, so it only runs with --live:

    python -m scripts.memory_replay --live            # 6 scenarios, about 12 filing calls
    python -m scripts.memory_replay --live --out docs/changes/017-replay.md

Needs NVIDIA_API_KEY (or OPENAI_API_KEY) in the environment or .env. The notes
and facts are invented; no real personal data.
"""

from __future__ import annotations

import argparse
import importlib
import os
import secrets
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Each scenario: facts you've confirmed, plans you have (text, days from today,
# time), the new note, and what good filing does with it.
SCENARIOS = [
    {
        "name": "A fact decides an unclear note",
        "facts": [("You run your college's events", "learn")],
        "plans": [],
        "note": "Need to finalise the stall list by Thursday",
        "expect": {"topic": "Work & career", "uses_memory": True, "plan_update": False},
    },
    {
        "name": "A note moves a plan",
        "facts": [],
        "plans": [("Dentist appointment", 3, "10:00")],
        "note": "Dentist moved to Friday 4pm",
        "expect": {"topic": "Medicines & doctors", "uses_memory": True, "plan_update": True},
    },
    {
        "name": "A filing example from your own choice",
        "facts": [("You filed “Chess openings” under Hobbies.", "fun")],
        "plans": [],
        "note": "Learn the Sicilian defence properly",
        "expect": {"topic": "Hobbies", "uses_memory": True, "plan_update": False},
    },
    {
        "name": "A person you've mentioned",
        "facts": [("Your sister is Priya", "people")],
        "plans": [],
        "note": "Priya's birthday next week, maybe a book",
        "expect": {"topic": "Occasions & gifts", "uses_memory": False, "plan_update": False},
    },
    {
        "name": "A hint must not override the note's words",
        "facts": [("You run your college's events", "learn")],
        "plans": [],
        "note": "Buy rice, dal and onions on the way home",
        "expect": {"topic": "Home & errands", "uses_memory": False, "plan_update": False},
    },
    {
        "name": "A similar plan that is a different one",
        "facts": [],
        "plans": [("Team lunch", 2, None)],
        "note": "Lunch with Aman on Tuesday to plan the trip",
        "expect": {"topic": "Friends & partner", "uses_memory": False, "plan_update": False},
    },
]


def replay_database_url(work: Path) -> str:
    """The throwaway database for a replay run (never the real one)."""
    path = Path(work) / "memory-replay.db"
    assert "life_inbox.db" not in path.name
    return "sqlite:///" + str(path).replace("\\", "/")


def _row(scenario: dict, off: dict, on: dict) -> str:
    expect = scenario["expect"]
    good = (on["topic"] == expect["topic"] and bool(on["plan_update"]) == expect["plan_update"])
    return (f"| {scenario['name']} | {scenario['note']} | {expect['topic']} | {off['topic'] or 'Needs you'} "
            f"| {on['topic'] or 'Needs you'} | {', '.join(on['memory_used']) or '-'} "
            f"| {'yes' if on['plan_update'] else 'no'} | {'✓' if good else '✗'} |")


def run(out: Path | None) -> int:
    from fastapi.testclient import TestClient

    work = Path(tempfile.mkdtemp(prefix="life-inbox-replay-"))
    os.environ["DATABASE_URL"] = replay_database_url(work)
    os.environ["LIFE_INBOX_UPLOAD_DIR"] = str(work / "uploads")
    import subprocess

    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    from app import llm
    from app.attention.dates import today_in_configured_tz

    if not llm.is_configured():
        print("No AI key is configured (NVIDIA_API_KEY or OPENAI_API_KEY); nothing was run.")
        return 2
    lines = ["| Scenario | Note | Expected | Without memory | With memory | Hints used | Plan update | Good |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    with TestClient(main.app) as client:
        for number, scenario in enumerate(SCENARIOS, start=1):
            client.post("/api/auth/logout")
            password = secrets.token_urlsafe(18)  # a throwaway account per scenario; never shown
            response = client.post("/api/auth/register", json={
                "email": f"replay{number}@example.test", "password": password, "display_name": "",
                "confirm_adult": True, "accept_terms": True})
            response.raise_for_status()
            user_id = (client.get("/api/auth/me").json().get("user") or {}).get("id")
            database.set_current_owner_id(user_id)
            for text, bot in scenario["facts"]:
                database.remember(text, kind="example" if text.startswith("You filed") else "long_term",
                                  source_kind="you", bot_key=bot, status="confirmed")
            database.set_current_owner_id(None)
            for text, days, clock in scenario["plans"]:
                task = client.post("/api/tasks", json={"text": text}).json()
                day = (today_in_configured_tz() + timedelta(days=days)).isoformat()
                client.post(f"/api/tasks/{task['id']}/date", json={"due_on": day, **({"due_time": clock} if clock else {})})
            note = client.post("/api/items", json={"raw_text": scenario["note"]}).json()
            results = {}
            for label, flag in (("off", ""), ("on", "1")):
                os.environ["LIFE_INBOX_MEMORY_IN_FILING"] = flag
                client.post("/api/analyze", params={"item_id": note["id"]}).raise_for_status()
                insight = client.get(f"/api/items/{note['id']}/insight").json()
                topics = {t["id"]: t["name"] for t in client.get("/api/topics").json()}
                cards = client.get("/api/captain/needs-you").json()["cards"]
                results[label] = {
                    "topic": topics.get(insight.get("effective_topic_id")),
                    "memory_used": [hint["text"] for hint in insight.get("memory_used") or []],
                    "plan_update": any(card["kind"] == "plan" for card in cards),
                }
            lines.append(_row(scenario, results["off"], results["on"]))
    os.environ.pop("LIFE_INBOX_MEMORY_IN_FILING", None)
    report = "\n".join(["# Memory replay (change 017)", "", *lines, ""])
    print(report)
    if out:
        out.write_text(report, encoding="utf-8")
        print(f"Saved to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--live", action="store_true", help="really call the AI (spends credits)")
    parser.add_argument("--out", type=Path, help="also save the table to this Markdown file")
    args = parser.parse_args(argv)
    if not args.live:
        print(f"This replay files {len(SCENARIOS)} made-up notes twice each against the real AI "
              f"(about {2 * len(SCENARIOS)} filing calls). Run it with --live once you're OK with that.")
        return 2
    return run(args.out)


if __name__ == "__main__":
    sys.exit(main())
