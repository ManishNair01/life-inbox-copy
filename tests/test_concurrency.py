"""Several users hitting the app in parallel against one SQLite database."""

import sys
import threading

from fastapi.testclient import TestClient

from tests.test_api import client  # noqa: F401  (fixture: isolated temp DB)

USERS = 5
ITEMS_PER_USER = 4


def _marker(index: int) -> str:
    return f"zebra{index}marker"


def _run_user(app, index, results, errors):
    try:
        with TestClient(app) as http:
            login = http.post(
                "/api/auth/dev-login", json={"email": f"user{index}@example.com"}
            )
            assert login.status_code == 200, login.text
            user_id = login.json()["id"]

            created = []
            for n in range(ITEMS_PER_USER):
                response = http.post(
                    "/api/items",
                    json={
                        "raw_text": f"{_marker(index)} remember to call contact {n} "
                        f"about project {index}"
                    },
                )
                assert response.status_code == 200, response.text
                created.append(response.json()["id"])

            analyze = http.post("/api/analyze")
            assert analyze.status_code == 200, analyze.text

            search = http.get("/api/search", params={"q": _marker(index)})
            assert search.status_code == 200, search.text

            listed = http.get("/api/items")
            assert listed.status_code == 200, listed.text

            ask = http.post(
                "/api/ask", json={"question": f"What is {_marker(index)} about?"}
            )
            assert ask.status_code == 200, ask.text

            tasks = http.get("/api/tasks")
            assert tasks.status_code == 200, tasks.text

            results[index] = {
                "user_id": user_id,
                "created": set(created),
                "listed": listed.json(),
                "search": search.json(),
                "ask": ask.json(),
                "tasks": tasks.json(),
            }
    except BaseException as exc:  # noqa: BLE001 - surfaced by the test
        errors.append((index, repr(exc)))


def test_parallel_users_do_not_collide_or_leak(client):  # noqa: F811
    app = sys.modules["app.main"].app
    results, errors = {}, []
    threads = [
        threading.Thread(target=_run_user, args=(app, i, results, errors))
        for i in range(USERS)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert errors == []
    assert set(results) == set(range(USERS))

    all_created = [r["created"] for r in results.values()]
    for i, a in enumerate(all_created):
        for b in all_created[i + 1 :]:
            assert a.isdisjoint(b)

    for index, result in results.items():
        listed_ids = {item["id"] for item in result["listed"]}
        assert listed_ids == result["created"]
        assert all(i["owner_user_id"] == result["user_id"] for i in result["listed"])

        other_markers = [_marker(j) for j in range(USERS) if j != index]
        blob = repr((result["search"], result["ask"], result["tasks"])).lower()
        assert not any(m in blob for m in other_markers)
        assert result["search"], "user should find their own items"
