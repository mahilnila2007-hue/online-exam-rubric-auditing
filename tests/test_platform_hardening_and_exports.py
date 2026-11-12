"""Tests for security hardening, portal-aware auth redirects, CSV exports, cloning, and rubric version history."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from app.services.csv_utils import csv_safe_cell, rows_to_csv_string
from tests.conftest import login_as, seed_user


def test_security_headers_and_portal_aware_redirects(client, repos, auth_gateway):
    student_redirect = client.get("/student/dashboard")
    assert student_redirect.status_code == 302
    assert urlsplit(student_redirect.headers["Location"]).path == "/login"
    assert student_redirect.headers.get("Permissions-Policy") == "camera=(), microphone=(), geolocation=()"

    staff_redirect = client.get("/examiner/dashboard")
    assert staff_redirect.status_code == 302
    assert urlsplit(staff_redirect.headers["Location"]).path == "/staff/login"

    admin_redirect = client.get("/admin/dashboard")
    assert admin_redirect.status_code == 302
    assert urlsplit(admin_redirect.headers["Location"]).path == "/admin/login"


def test_role_aware_logout_redirect_urls(client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="stu1", email="stu1@uni.edu", role="student", full_name="Student One")
    seed_user(repos, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner", full_name="Staff One")
    seed_user(repos, auth_gateway, uid="adm1", email="adm1@uni.edu", role="admin", full_name="Admin One")

    stu_headers = login_as(client, auth_gateway, uid="stu1", email="stu1@uni.edu", role="student")
    assert client.post("/api/auth/logout", json={}, headers=stu_headers).get_json()["data"]["redirect_url"] == "/login"

    ex_headers = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")
    assert client.post("/api/auth/logout", json={}, headers=ex_headers).get_json()["data"]["redirect_url"] == "/staff/login"

    adm_headers = login_as(client, auth_gateway, uid="adm1", email="adm1@uni.edu", role="admin")
    assert client.post("/api/auth/logout", json={}, headers=adm_headers).get_json()["data"]["redirect_url"] == "/admin/login"


def test_csv_formula_injection_defense_utility():
    assert csv_safe_cell("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert csv_safe_cell("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
    assert csv_safe_cell("-2+3") == "'-2+3"
    assert csv_safe_cell("@IMPORTXML") == "'@IMPORTXML"
    assert csv_safe_cell("\twhoami") == "'\twhoami"
    assert csv_safe_cell("\rcmd") == "'\rcmd"
    assert csv_safe_cell(42.5) == 42.5
    assert csv_safe_cell(None) == ""

    csv_text = rows_to_csv_string(["Name", "Formula", "Score"], [["Alice", "=1+1", 95]])
    assert "'=1+1" in csv_text
    assert "95" in csv_text


def test_payload_too_large_returns_json_for_api_routes(app, client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner", full_name="Examiner")
    headers = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")

    original_limit = app.config.get("MAX_CONTENT_LENGTH")
    app.config["MAX_CONTENT_LENGTH"] = 64
    try:
        resp = client.post(
            "/api/examiner/questions",
            json={"prompt": "A" * 200},
            headers=headers,
        )
        assert resp.status_code == 413
        body = resp.get_json()
        assert body["error"]["code"] == "PAYLOAD_TOO_LARGE"
    finally:
        app.config["MAX_CONTENT_LENGTH"] = original_limit


def test_exam_clone_search_results_csv_and_rubric_versions(client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner", full_name="Dr. Ada")
    seed_user(repos, auth_gateway, uid="ex2", email="ex2@uni.edu", role="examiner", full_name="Dr. Bob")
    seed_user(repos, auth_gateway, uid="stu1", email="stu1@uni.edu", role="student", full_name="=EVIL_NAME", inst_id="+S-001")

    ex_headers = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")

    q_mcq = client.post(
        "/api/examiner/questions",
        json={
            "type": "mcq",
            "difficulty": "easy",
            "subject": "Systems",
            "marks": 4,
            "prompt": "Choose Raft property.",
            "options": [{"id": "opt_1", "text": "Leader"}, {"id": "opt_2", "text": "None"}],
            "correct_option_id": "opt_1",
        },
        headers=ex_headers,
    ).get_json()["data"]["question"]["question_id"]

    q_desc_resp = client.post(
        "/api/examiner/questions",
        json={
            "type": "descriptive",
            "difficulty": "medium",
            "subject": "Systems",
            "marks": 6,
            "prompt": "Explain quorum intersection.",
            "rubric": {
                "title": "Quorum Rubric",
                "model_answer": "Two majorities always overlap in at least one voter.",
                "criteria": [
                    {
                        "title": "Overlap Principle",
                        "description": "Mentions voter intersection",
                        "max_marks": 6,
                        "key_concepts": ["majority", "overlap", "voter"],
                    }
                ],
            },
        },
        headers=ex_headers,
    )
    assert q_desc_resp.status_code == 201
    q_desc_data = q_desc_resp.get_json()["data"]["question"]
    q_desc = q_desc_data["question_id"]
    rubric_id = q_desc_data["rubric_id"]

    now = datetime.now(timezone.utc)
    exam = client.post(
        "/api/examiner/exams",
        json={
            "title": "Distributed Consensus Final",
            "course_code": "CS510",
            "status": "published",
            "scheduled_start": (now - timedelta(minutes=15)).isoformat(),
            "scheduled_end": (now + timedelta(hours=2)).isoformat(),
            "duration_minutes": 45,
            "passing_marks": 5,
            "question_ids": [q_mcq, q_desc],
            "rubric_audit_enabled": True,
        },
        headers=ex_headers,
    ).get_json()["data"]["exam"]
    exam_id = exam["exam_id"]

    # Search filtering returns match and excludes non-matching query
    assert len(client.get("/api/examiner/exams?search=cs510", headers=ex_headers).get_json()["data"]["exams"]) == 1
    assert len(client.get("/api/examiner/exams?search=nomatch", headers=ex_headers).get_json()["data"]["exams"]) == 0

    # Other examiner cannot duplicate ex1's exam
    ex2_headers = login_as(client, auth_gateway, uid="ex2", email="ex2@uni.edu", role="examiner")
    forbidden_dup = client.post(f"/api/examiner/exams/{exam_id}/duplicate", json={}, headers=ex2_headers)
    assert forbidden_dup.status_code == 403

    # Owner duplicates into draft copy preserving active questions
    ex_headers = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")
    dup_resp = client.post(f"/api/examiner/exams/{exam_id}/duplicate", json={}, headers=ex_headers)
    assert dup_resp.status_code == 201
    cloned = dup_resp.get_json()["data"]["exam"]
    assert cloned["status"] == "draft"
    assert cloned["cloned_from_exam_id"] == exam_id
    assert cloned["question_ids"] == [q_mcq, q_desc]

    # Version endpoint returns current_rubric snapshot even before any audit revision
    ver_resp = client.get(f"/api/examiner/rubrics/{rubric_id}/versions", headers=ex_headers)
    assert ver_resp.status_code == 200
    assert ver_resp.get_json()["data"]["current_rubric"]["rubric_id"] == rubric_id
    assert ver_resp.get_json()["data"]["versions"] == []

    # Student submits; examiner batch-evaluates & checks results summary + formula-safe CSV export
    stu_headers = login_as(client, auth_gateway, uid="stu1", email="stu1@uni.edu", role="student")
    client.post(f"/api/student/exams/{exam_id}/start", json={}, headers=stu_headers)
    sub = client.post(
        f"/api/student/exams/{exam_id}/submit",
        json={
            "answers": {
                q_mcq: {"selected_option_id": "opt_1"},
                q_desc: {"text_answer": "Two majority sets always overlap on a voter."},
            }
        },
        headers=stu_headers,
    ).get_json()["data"]["submission"]

    ex_headers = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")
    client.post(f"/api/examiner/exams/{exam_id}/process-evaluations", json={}, headers=ex_headers)
    ws = client.get(f"/api/examiner/submissions/{sub['submission_id']}/evaluation", headers=ex_headers).get_json()["data"]
    crit_id = ws["descriptive_questions"][0]["criteria"][0]["criterion_id"]
    eval_resp = client.put(
        f"/api/examiner/submissions/{sub['submission_id']}/evaluate",
        json={
            "publish_result": True,
            "examiner_feedback": "Good insight",
            "question_evaluations": {
                q_desc: {
                    "feedback": "Accurate overlap explanation.",
                    "criteria_scores": [
                        {"criterion_id": crit_id, "awarded_marks": 5, "feedback": "Well stated."}
                    ],
                }
            },
        },
        headers=ex_headers,
    )
    assert eval_resp.status_code == 200

    res_list = client.get(f"/api/examiner/exams/{exam_id}/results", headers=ex_headers).get_json()["data"]
    assert res_list["summary"]["passed_count"] == 1
    assert sum(res_list["summary"]["grade_distribution"].values()) == 1

    csv_resp = client.get(f"/api/examiner/exams/{exam_id}/results.csv", headers=ex_headers)
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["Content-Type"]
    assert "attachment;" in csv_resp.headers["Content-Disposition"]
    csv_body = csv_resp.get_data(as_text=True)
    assert "'=EVIL_NAME" in csv_body
    assert "'+S-001" in csv_body
