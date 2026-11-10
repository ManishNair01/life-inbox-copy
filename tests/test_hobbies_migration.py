"""Migration 0026: "Cooking & hobbies" becomes Hobbies, with Cooking inside it."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_migration_0026_splits_cooking_out_of_hobbies(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'v25.db'}")
    command.upgrade(config, "0025_task_ideas")
    engine = create_engine(f"sqlite:///{tmp_path / 'v25.db'}")
    with engine.begin() as c:
        c.execute(text("INSERT INTO users (id, email, display_name, auth_provider, created_at) VALUES (77, 'a@example.com', '', 'password', 'x')"))
        c.execute(text("INSERT INTO topics (id, name, description, owner_user_id, created_at, updated_at, archived, bot_key, origin) "
                       "VALUES (900, 'Cooking & hobbies', 'old', 77, 'x', 'x', 0, 'fun', 'built_in')"))
        c.execute(text("INSERT INTO analysis_runs (id, started_at, status, mode, result_json) VALUES "
                       "(1, 'x', 'succeeded', 'nvidia_nim', '{\"buckets\": [{\"name\": \"Cooking & hobbies\", \"notes\": []}]}')"))
        for item_id, words, mine in ((1, "Butter chicken recipe", None), (2, "Practise guitar chords", None),
                                     (3, "Paneer tikka for the party", 900)):
            c.execute(text("INSERT INTO inbox_items (id, item_type, raw_text, processing_status, owner_user_id, created_at) "
                           "VALUES (:id, 'text', :words, 'ready', 77, 'x')"), {"id": item_id, "words": words})
            c.execute(text("INSERT INTO item_insights (item_id, analysis_run_id, category, concise_title, priority, topic_id, "
                           "user_topic_id, needs_review, updated_at) VALUES (:id, 1, 'Cooking & hobbies', :words, 'Low', 900, :mine, 0, 'x')"),
                      {"id": item_id, "words": words, "mine": mine})
    command.upgrade(config, "0026_hobbies_and_cooking")
    try:
        with engine.begin() as c:
            topics = {name: (tid, parent) for tid, name, parent in c.execute(text(
                "SELECT id, name, parent_topic_id FROM topics WHERE owner_user_id = 77")).all()}
            assert set(topics) == {"Hobbies", "Cooking"} and topics["Hobbies"] == (900, None)
            assert topics["Cooking"][1] == 900
            placed = dict(c.execute(text("SELECT item_id, topic_id FROM item_insights")).all())
            assert placed == {1: topics["Cooking"][0], 2: 900, 3: topics["Cooking"][0]}
            # Item 3's own pick (user_topic_id 900 = Hobbies) is kept as it was.
            assert c.execute(text("SELECT user_topic_id FROM item_insights WHERE item_id = 3")).scalar() == 900
            assert '"name": "Hobbies"' in c.execute(text("SELECT result_json FROM analysis_runs WHERE id = 1")).scalar()
    finally:
        engine.dispose()
