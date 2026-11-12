"""Integration tests for administrative user management, monitoring, and CSV reporting."""

from __future__ import annotations

from tests.conftest import login_as, seed_user


def test_admin_user_provisioning_suspension_and_reports(client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="adm1", email="admin@uni.edu", role="admin", full_name="Root Admin")
    headers = login_as(client, auth_gateway, uid="adm1", email="admin@uni.edu", role="admin")

    # 1. Create Examiner via Admin API
    create_resp = client.post(
        "/api/admin/users",
        json={
            "email": "prof.clark@uni.edu",
            "password": "StrongPassword123!",
            "full_name": "Prof. Clark",
            "role": "examiner",
            "institution_id": "FAC-88",
            "department": "Mathematics",
        },
        headers=headers,
    )
    assert create_resp.status_code == 201
    created_uid = create_resp.get_json()["data"]["user"]["uid"]
    assert create_resp.get_json()["data"]["user"]["role"] == "examiner"

    # 2. Cannot suspend self
    self_susp = client.patch(
        "/api/admin/users/adm1",
        json={"status": "suspended"},
        headers=headers,
    )
    assert self_susp.status_code == 400

    # 3. Suspend created examiner and verify role update
    upd_resp = client.patch(
        f"/api/admin/users/{created_uid}",
        json={"status": "suspended"},
        headers=headers,
    )
    assert upd_resp.status_code == 200
    assert upd_resp.get_json()["data"]["user"]["status"] == "suspended"

    # 4. Overview & audit logs & CSV export
    overview = client.get("/api/admin/overview").get_json()["data"]
    assert overview["metrics"]["total_users"] == 2
    assert overview["metrics"]["suspended_users"] == 1
    assert any(log["action"] == "ADMIN_USER_CREATED" for log in overview["recent_activity"])

    csv_resp = client.get("/api/admin/reports/exams.csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["Content-Type"]
    assert "Exam ID,Course Code,Title" in csv_resp.get_data(as_text=True)

