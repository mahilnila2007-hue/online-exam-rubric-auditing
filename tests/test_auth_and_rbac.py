"""Integration tests for authentication, CSRF, registration, and role-based access control."""

from __future__ import annotations

from tests.conftest import get_csrf_headers, login_as, seed_user


def test_unauthenticated_redirects_and_api_401(client):
    for page in ["/student/dashboard", "/examiner/dashboard", "/admin/dashboard", "/examiner/questions"]:
        resp = client.get(page)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    api_resp = client.get("/api/student/exams")
    assert api_resp.status_code == 401


def test_csrf_protection_enforced_on_mutations(client, auth_gateway):
    token = auth_gateway.issue_id_token(uid="stu_1", email="s1@uni.edu", role="student")
    resp = client.post("/api/auth/session-login", json={"id_token": token})
    assert resp.status_code == 403
    assert resp.get_json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


def test_student_registration_locks_role_to_student(client, auth_gateway):
    headers = get_csrf_headers(client)
    id_token = auth_gateway.issue_id_token(uid="stu_reg_1", email="alice@uni.edu", role="student")

    resp = client.post(
        "/api/auth/register",
        json={
            "id_token": id_token,
            "full_name": "Alice Mercer",
            "institution_id": "STU-101",
            "department": "AI",
            "role": "admin",  # Attempted privilege escalation must be ignored
        },
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["user"]["role"] == "student"
    assert data["redirect_url"] == "/student/dashboard"

    # Student dashboard renders 200 with session cookie now set
    dash = client.get("/student/dashboard")
    assert dash.status_code == 200


def test_role_based_access_control_matrix(client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="s1", email="s1@uni.edu", role="student", full_name="Student One")
    seed_user(repos, auth_gateway, uid="e1", email="e1@uni.edu", role="examiner", full_name="Examiner One")
    seed_user(repos, auth_gateway, uid="a1", email="a1@uni.edu", role="admin", full_name="Admin One")

    # Student cannot reach examiner or admin portals
    login_as(client, auth_gateway, uid="s1", email="s1@uni.edu", role="student")
    assert client.get("/student/dashboard").status_code == 200
    assert client.get("/examiner/dashboard").status_code == 403
    assert client.get("/admin/dashboard").status_code == 403
    assert client.get("/api/examiner/exams").status_code == 403
    assert client.get("/api/admin/overview").status_code == 403

    # Examiner cannot reach student or admin portals
    headers = login_as(client, auth_gateway, uid="e1", email="e1@uni.edu", role="examiner")
    assert client.get("/examiner/dashboard").status_code == 200
    assert client.get("/examiner/questions").status_code == 200
    assert client.get("/examiner/exams/new").status_code == 200
    assert client.get("/student/dashboard").status_code == 403
    assert client.get("/admin/dashboard").status_code == 403

    # Logout terminates session
    logout_resp = client.post("/api/auth/logout", json={}, headers=headers)
    assert logout_resp.status_code == 200
    assert client.get("/examiner/dashboard").status_code == 302


def test_suspended_user_cannot_login(client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="s_susp", email="susp@uni.edu", role="student", full_name="Suspended User")
    repos["users"].update("s_susp", {"status": "suspended"})

    headers = get_csrf_headers(client)
    token = auth_gateway.issue_id_token(uid="s_susp", email="susp@uni.edu", role="student")
    resp = client.post("/api/auth/session-login", json={"id_token": token}, headers=headers)
    assert resp.status_code == 403


def test_login_portals_render_expected_modes(client):
    for path, marker in [
        ("/login", '"initialPortal": "student"'),
        ("/staff/login", '"initialPortal": "staff"'),
        ("/admin/login", '"initialPortal": "admin"'),
        ("/register", '"initialTab": "register"'),
    ]:
        resp = client.get(path)
        assert resp.status_code == 200
        assert marker in resp.get_data(as_text=True)


def test_staff_registration_requires_admin_verification_and_approval(client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="admin_ver", email="admin@uni.edu", role="admin", full_name="Chief Admin")
    seed_user(repos, auth_gateway, uid="stu_ver", email="stu@uni.edu", role="student", full_name="Plain Student")

    # Self-register as staff (examiner) without existing session
    headers = get_csrf_headers(client)
    staff_token = auth_gateway.issue_id_token(uid="staff_pend_1", email="dr.patel@uni.edu", role="student")
    reg_resp = client.post(
        "/api/auth/register",
        json={
            "id_token": staff_token,
            "full_name": "Dr. Meera Patel",
            "institution_id": "FAC-2026-09",
            "department": "Computer Science",
            "account_type": "staff",
        },
        headers=headers,
    )
    assert reg_resp.status_code == 202
    reg_data = reg_resp.get_json()["data"]
    assert reg_data["requires_approval"] is True
    assert reg_data["redirect_url"] == "/staff/login"
    assert reg_data["user"]["role"] == "examiner"
    assert reg_data["user"]["status"] == "pending_approval"

    # Must NOT have an active session cookie before Admin approval
    assert client.get("/examiner/dashboard").status_code == 302

    # Attempting to sign in before approval must be blocked
    login_blocked = client.post(
        "/api/auth/session-login",
        json={"id_token": staff_token, "portal": "staff"},
        headers=headers,
    )
    assert login_blocked.status_code == 403
    assert login_blocked.get_json()["error"]["code"] == "ACCOUNT_PENDING_APPROVAL"

    # Student attempting to use staff/admin portal login or approve API is blocked
    stu_headers = login_as(client, auth_gateway, uid="stu_ver", email="stu@uni.edu", role="student")
    forbidden_approve = client.post("/api/admin/users/staff_pend_1/approve", json={}, headers=stu_headers)
    assert forbidden_approve.status_code == 403
    client.post("/api/auth/logout", json={}, headers=stu_headers)

    stu_token = auth_gateway.issue_id_token(uid="stu_ver", email="stu@uni.edu", role="student")
    for wrong_portal in ("staff", "admin"):
        portal_err = client.post(
            "/api/auth/session-login",
            json={"id_token": stu_token, "portal": wrong_portal},
            headers=get_csrf_headers(client),
        )
        assert portal_err.status_code == 403
        assert portal_err.get_json()["error"]["code"] == "PORTAL_ROLE_MISMATCH"

    # Admin sees pending approval in overview and approves staff member
    admin_headers = login_as(client, auth_gateway, uid="admin_ver", email="admin@uni.edu", role="admin")
    overview_resp = client.get("/api/admin/overview")
    assert overview_resp.status_code == 200
    overview = overview_resp.get_json()["data"]
    assert overview["metrics"]["pending_staff_count"] == 1
    assert [u["uid"] for u in overview["pending_staff_approvals"]] == ["staff_pend_1"]

    approve_resp = client.post("/api/admin/users/staff_pend_1/approve", json={}, headers=admin_headers)
    assert approve_resp.status_code == 200
    approved_user = approve_resp.get_json()["data"]["user"]
    assert approved_user["status"] == "active"
    assert approved_user["role"] == "examiner"

    client.post("/api/auth/logout", json={}, headers=admin_headers)

    # Approved staff can now sign in via staff portal (but NOT admin portal) and reach examiner dashboard
    staff_headers = get_csrf_headers(client)
    refreshed_staff_token = auth_gateway.issue_id_token(uid="staff_pend_1", email="dr.patel@uni.edu", role="examiner")
    wrong_admin = client.post(
        "/api/auth/session-login",
        json={"id_token": refreshed_staff_token, "portal": "admin"},
        headers=staff_headers,
    )
    assert wrong_admin.status_code == 403
    assert wrong_admin.get_json()["error"]["code"] == "PORTAL_ROLE_MISMATCH"

    ok_login = client.post(
        "/api/auth/session-login",
        json={"id_token": refreshed_staff_token, "portal": "staff"},
        headers=staff_headers,
    )
    assert ok_login.status_code == 200
    assert ok_login.get_json()["data"]["redirect_url"] == "/examiner/dashboard"
    assert client.get("/examiner/dashboard").status_code == 200


def test_admin_can_reject_pending_staff_registration(client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="admin_rej", email="admin2@uni.edu", role="admin", full_name="Admin Two")

    headers = get_csrf_headers(client)
    tok = auth_gateway.issue_id_token(uid="staff_pend_2", email="fake.staff@uni.edu", role="student")
    reg_resp = client.post(
        "/api/auth/register",
        json={
            "id_token": tok,
            "full_name": "Unverified Applicant",
            "institution_id": "FAC-UNKNOWN",
            "department": "Math",
            "account_type": "staff",
        },
        headers=headers,
    )
    assert reg_resp.status_code == 202

    admin_headers = login_as(client, auth_gateway, uid="admin_rej", email="admin2@uni.edu", role="admin")
    rej_resp = client.post(
        "/api/admin/users/staff_pend_2/reject",
        json={"reason": "Faculty ID not found in HR roster"},
        headers=admin_headers,
    )
    assert rej_resp.status_code == 200
    assert rej_resp.get_json()["data"]["user"]["status"] == "rejected"
    client.post("/api/auth/logout", json={}, headers=admin_headers)

    # Rejected staff account is disabled in Firebase Auth (401) and rejected in Firestore (403)
    assert auth_gateway.users_by_uid["staff_pend_2"]["disabled"] is True
    login_disabled = client.post(
        "/api/auth/session-login",
        json={"id_token": tok, "portal": "staff"},
        headers=get_csrf_headers(client),
    )
    assert login_disabled.status_code == 401

    auth_gateway.update_user_status("staff_pend_2", disabled=False)
    login_rej = client.post(
        "/api/auth/session-login",
        json={"id_token": tok, "portal": "staff"},
        headers=get_csrf_headers(client),
    )
    assert login_rej.status_code == 403
    assert login_rej.get_json()["error"]["code"] == "ACCOUNT_REJECTED"


