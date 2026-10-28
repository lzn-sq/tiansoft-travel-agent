def test_requires_auth(client):
    response = client.get("/api/sessions")
    assert response.status_code == 401


def test_register_and_login(client, auth_headers):
    response = client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["username"] == "tester"

    duplicate = client.post(
        "/api/auth/register", json={"username": "tester", "password": "secret123"}
    )
    assert duplicate.status_code == 400


def test_login_wrong_password(client):
    response = client.post(
        "/api/auth/login", json={"username": "tester", "password": "wrong-password"}
    )
    assert response.status_code == 401


def test_session_crud(client, auth_headers):
    created = client.post("/api/session", json={}, headers=auth_headers)
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    listed = client.get("/api/sessions", headers=auth_headers)
    assert listed.status_code == 200
    assert any(item["id"] == session_id for item in listed.json()["sessions"])

    messages = client.get(f"/api/sessions/{session_id}/messages", headers=auth_headers)
    assert messages.status_code == 200
    assert messages.json()["messages"] == []

    deleted = client.delete(f"/api/sessions/{session_id}", headers=auth_headers)
    assert deleted.status_code == 200

    missing = client.get(f"/api/sessions/{session_id}/messages", headers=auth_headers)
    assert missing.status_code == 404


def test_session_isolation(client, auth_headers, other_auth_headers):
    created = client.post("/api/session", json={}, headers=auth_headers)
    session_id = created.json()["session_id"]

    assert (
        client.get(f"/api/sessions/{session_id}/messages", headers=other_auth_headers).status_code
        == 404
    )
    assert (
        client.delete(f"/api/sessions/{session_id}", headers=other_auth_headers).status_code == 404
    )
    chat = client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "text": "北京住宿标准"},
        headers=other_auth_headers,
    )
    assert chat.status_code == 404


def test_chat_rejects_unknown_session(client, auth_headers):
    response = client.post(
        "/api/chat/stream",
        json={"session_id": "not-exist", "text": "北京住宿标准"},
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_chat_empty_text_validation(client, auth_headers):
    response = client.post(
        "/api/chat/stream",
        json={"session_id": "any", "text": ""},
        headers=auth_headers,
    )
    assert response.status_code == 422
