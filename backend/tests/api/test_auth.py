"""Authentication endpoints. Needs the test database."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"


def test_register_then_sign_in(client):
    response = client.post(
        REGISTER,
        json={"email": "New.User@Example.com", "password": "a long test passphrase",
              "full_name": "New User"},
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new.user@example.com"  # stored lower-cased

    token_response = client.post(
        LOGIN, data={"username": "new.user@example.com", "password": "a long test passphrase"}
    )
    assert token_response.status_code == 200
    token = token_response.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["full_name"] == "New User"


def test_short_passwords_are_rejected_with_our_error_shape(client):
    response = client.post(REGISTER, json={"email": "a@example.com", "password": "short"})
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert "password" in body["message"]


def test_duplicate_email_is_a_conflict(client):
    payload = {"email": "dup@example.com", "password": "a long test passphrase"}
    assert client.post(REGISTER, json=payload).status_code == 201
    second = client.post(REGISTER, json=payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


def test_wrong_password_and_unknown_email_look_the_same(client):
    client.post(REGISTER, json={"email": "real@example.com", "password": "a long test passphrase"})

    wrong = client.post(LOGIN, data={"username": "real@example.com", "password": "not the one"})
    unknown = client.post(LOGIN, data={"username": "ghost@example.com", "password": "not the one"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_protected_routes_need_a_token(client):
    assert client.get("/api/v1/datasets").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
