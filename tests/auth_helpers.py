"""Helpers for signing test clients in through the real password flow."""

DEFAULT_TEST_PASSWORD = "Correct-Horse-9-Staple"


def register(client, email, password=DEFAULT_TEST_PASSWORD, display_name=""):
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": password,
            "display_name": display_name,
            "confirm_adult": True,
            "accept_terms": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client, email, password=DEFAULT_TEST_PASSWORD):
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()
