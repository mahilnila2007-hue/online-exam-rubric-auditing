"""Integration tests for student exam attendance, answer security, autosave, and submission."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import login_as, seed_user


def _setup_live_exam(client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner", full_name="Prof. Turing")
    seed_user(repos, auth_gateway, uid="stu1", email="stu1@uni.edu", role="student", full_name="Student Alpha", inst_id="S-001")
    seed_user(repos, auth_gateway, uid="stu2", email="stu2@uni.edu", role="student", full_name="Student Beta", inst_id="S-002")

    ex_headers = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")
    q1 = client.post(
        "/api/examiner/questions",
        json={
            "type": "mcq",
            "difficulty": "easy",
            "subject": "Algorithms",
            "marks": 4,
            "prompt": "Time complexity of binary search?",
            "options": [
                {"id": "opt_1", "text": "O(log n)"},
                {"id": "opt_2", "text": "O(n^2)"},
            ],
            "correct_option_id": "opt_1",
            "explanation": "Search space halves each step.",
        },
        headers=ex_headers,
    ).get_json()["data"]["question"]["question_id"]

    q2 = client.post(
        "/api/examiner/questions",
        json={
            "type": "descriptive",
            "difficulty": "medium",
            "subject": "Algorithms",
            "marks": 6,
            "prompt": "Compare merge sort and quicksort stability.",
            "rubric": {
                "title": "Sorting Rubric",
                "model_answer": "Merge sort is stable; standard in-place quicksort is unstable.",
                "criteria": [{"title": "Stability Comparison", "max_marks": 6, "key_concepts": ["stable", "partition"]}],
            },
        },
        headers=ex_headers,
    ).get_json()["data"]["question"]["question_id"]

    now = datetime.now(timezone.utc)
    exam = client.post(
        "/api/examiner/exams",
        json={
            "title": "Algorithms Final",
            "course_code": "CS202",
            "status": "published",
            "scheduled_start": (now - timedelta(minutes=5)).isoformat(),
            "scheduled_end": (now + timedelta(hours=1)).isoformat(),
            "duration_minutes": 30,
            "passing_marks": 4,
            "question_ids": [q1, q2],
            "rubric_audit_enabled": True,
        },
        headers=ex_headers,
    ).get_json()["data"]["exam"]

    return exam, q1, q2


def test_student_end_to_end_exam_attendance_and_submission(client, repos, auth_gateway):
    exam, q1, q2 = _setup_live_exam(client, repos, auth_gateway)
    exam_id = exam["exam_id"]

    stu_headers = login_as(client, auth_gateway, uid="stu1", email="stu1@uni.edu", role="student")

    # 1. Dashboard & instructions
    dash = client.get("/api/student/exams").get_json()["data"]
    assert dash["summary"]["live_count"] == 1
    assert dash["exams"][0]["can_start"] is True

    instr = client.get(f"/api/student/exams/{exam_id}/instructions").get_json()["data"]["exam"]
    assert instr["total_marks"] == 10.0

    # 2. Start exam & verify NO answer keys leak to student!
    start_resp = client.post(f"/api/student/exams/{exam_id}/start", json={}, headers=stu_headers)
    assert start_resp.status_code == 200
    start_data = start_resp.get_json()["data"]
    assert start_data["remaining_seconds"] > 0
    for q in start_data["questions"]:
        assert "correct_option_id" not in q
        assert "explanation" not in q
        if q["type"] == "descriptive":
            assert "model_answer" not in str(q)

    # 3. Autosave answers
    save_resp = client.put(
        f"/api/student/exams/{exam_id}/answers",
        json={
            "answers": {
                q1: {"selected_option_id": "opt_1", "flagged_for_review": False},
                q2: {"text_answer": "Merge sort preserves equal element order; quicksort does not.", "flagged_for_review": True},
            }
        },
        headers=stu_headers,
    )
    assert save_resp.status_code == 200
    assert save_resp.get_json()["data"]["answered_count"] == 2

    # 4. Resume returns saved progress
    resume_resp = client.post(f"/api/student/exams/{exam_id}/start", json={}, headers=stu_headers)
    assert resume_resp.status_code == 200
    assert resume_resp.get_json()["data"]["answers"][q1]["selected_option_id"] == "opt_1"

    # 5. Final submission calculates MCQ score and creates Phase 3 rubric audit slot
    submit_resp = client.post(f"/api/student/exams/{exam_id}/submit", json={}, headers=stu_headers)
    assert submit_resp.status_code == 200
    sub = submit_resp.get_json()["data"]["submission"]
    sub_id = sub["submission_id"]
    assert sub["status"] == "submitted"
    assert sub["grading"]["mcq_score"] == 4.0
    assert sub["grading"]["mcq_max_score"] == 4.0
    assert sub["grading"]["descriptive_max_score"] == 6.0
    assert sub["grading"]["evaluation_status"] == "pending_descriptive"
    assert sub["rubric_audit"]["audit_status"] == "pending_audit"

    # 6. Cannot re-start already submitted exam
    restart = client.post(f"/api/student/exams/{exam_id}/start", json={}, headers=stu_headers)
    assert restart.status_code == 409
    assert restart.get_json()["error"]["code"] == "EXAM_ALREADY_SUBMITTED"

    # 7. Confirmation page & History page render cleanly
    assert client.get(f"/student/submissions/{sub_id}/confirmation").status_code == 200
    hist = client.get("/api/student/history").get_json()["data"]["submissions"]
    assert len(hist) == 1
    assert hist[0]["mcq_score"] == 4.0

    # 8. Student Beta cannot view Student Alpha's submission
    login_as(client, auth_gateway, uid="stu2", email="stu2@uni.edu", role="student")
    assert client.get(f"/api/student/submissions/{sub_id}").status_code == 403

    # 9. Examiner can list and inspect Student Alpha's submission
    login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")
    ex_subs = client.get(f"/api/examiner/exams/{exam_id}/submissions").get_json()["data"]["submissions"]
    assert len(ex_subs) == 1
    assert ex_subs[0]["student_name"] == "Student Alpha"


def test_all_ten_pages_render_and_timer_expiry_autosubmits(client, repos, auth_gateway):
    # Public login & register (before signing in)
    assert client.get("/login").status_code == 200
    assert client.get("/register").status_code == 200

    exam, q1, _ = _setup_live_exam(client, repos, auth_gateway)
    exam_id = exam["exam_id"]

    # Examiner pages
    ex_headers = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")
    assert client.get("/examiner/dashboard").status_code == 200
    assert client.get("/examiner/exams/new").status_code == 200
    assert client.get(f"/examiner/exams/{exam_id}/edit").status_code == 200
    assert client.get("/examiner/questions").status_code == 200

    # Admin page
    seed_user(repos, auth_gateway, uid="adm_p", email="admp@uni.edu", role="admin", full_name="Admin Page")
    login_as(client, auth_gateway, uid="adm_p", email="admp@uni.edu", role="admin")
    assert client.get("/admin/dashboard").status_code == 200

    # Upcoming exam cannot be started early
    future = datetime.now(timezone.utc) + timedelta(days=1)
    ex_headers = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")
    upcoming_exam = client.post(
        "/api/examiner/exams",
        json={
            "title": "Future Quiz",
            "course_code": "CS999",
            "status": "scheduled",
            "scheduled_start": future.isoformat(),
            "scheduled_end": (future + timedelta(hours=1)).isoformat(),
            "duration_minutes": 20,
            "passing_marks": 2,
            "question_ids": [q1],
        },
        headers=ex_headers,
    ).get_json()["data"]["exam"]

    # Student pages & timer expiry auto-submit
    stu_headers = login_as(client, auth_gateway, uid="stu1", email="stu1@uni.edu", role="student")
    assert client.get("/student/dashboard").status_code == 200
    assert client.get(f"/student/exams/{exam_id}/instructions").status_code == 200
    assert client.get(f"/student/exams/{exam_id}/attempt").status_code == 200
    assert client.get("/student/history").status_code == 200

    # Upcoming exam blocked from starting
    early_start = client.post(f"/api/student/exams/{upcoming_exam['exam_id']}/start", json={}, headers=stu_headers)
    assert early_start.status_code == 400

    # Start live exam, save answer, then expire timer beyond grace period
    start_data = client.post(f"/api/student/exams/{exam_id}/start", json={}, headers=stu_headers).get_json()["data"]
    sub_id = start_data["submission_id"]
    client.put(
        f"/api/student/exams/{exam_id}/answers",
        json={"answers": {q1: {"selected_option_id": "opt_1"}}},
        headers=stu_headers,
    )
    repos["submissions"].update(
        sub_id,
        {"expires_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()},
    )
    expired_save = client.put(
        f"/api/student/exams/{exam_id}/answers",
        json={"answers": {q1: {"selected_option_id": "opt_2"}}},
        headers=stu_headers,
    )
    assert expired_save.status_code == 409
    assert expired_save.get_json()["error"]["code"] == "EXAM_TIME_EXPIRED"

    # Saved opt_1 prior to expiry was graded during auto-submit
    detail = client.get(f"/api/student/submissions/{sub_id}").get_json()["data"]["submission"]
    assert detail["status"] == "auto_submitted"
    assert detail["grading"]["mcq_score"] == 4.0
    assert client.get(f"/student/submissions/{sub_id}/confirmation").status_code == 200
