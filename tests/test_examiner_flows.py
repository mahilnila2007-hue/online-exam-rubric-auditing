"""Integration tests for examiner question bank, rubric builder, and exam creation flows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import login_as, seed_user


def test_question_rubric_and_exam_lifecycle(client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner", full_name="Dr. Ada")
    seed_user(repos, auth_gateway, uid="ex2", email="ex2@uni.edu", role="examiner", full_name="Dr. Bob")
    headers = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")

    # 1. Create MCQ question
    mcq_resp = client.post(
        "/api/examiner/questions",
        json={
            "type": "mcq",
            "difficulty": "medium",
            "subject": "Distributed Systems",
            "topic": "Consensus",
            "marks": 2,
            "prompt": "Which property guarantees all non-faulty nodes agree on the same value?",
            "options": [
                {"id": "opt_1", "text": "Safety / Agreement"},
                {"id": "opt_2", "text": "Load Balancing"},
                {"id": "opt_3", "text": "Sharding"},
            ],
            "correct_option_id": "opt_1",
            "explanation": "Agreement ensures non-faulty processes decide identically.",
        },
        headers=headers,
    )
    assert mcq_resp.status_code == 201
    mcq_id = mcq_resp.get_json()["data"]["question"]["question_id"]

    # 2. Descriptive rubric mismatch validation must fail
    bad_desc = client.post(
        "/api/examiner/questions",
        json={
            "type": "descriptive",
            "difficulty": "hard",
            "subject": "Distributed Systems",
            "marks": 10,
            "prompt": "Explain Raft leader election.",
            "rubric": {
                "title": "Raft Rubric",
                "criteria": [{"title": "Accuracy", "max_marks": 6}],
            },
        },
        headers=headers,
    )
    assert bad_desc.status_code == 400

    # 3. Create valid Descriptive question with inline rubric (sum == 10)
    desc_resp = client.post(
        "/api/examiner/questions",
        json={
            "type": "descriptive",
            "difficulty": "hard",
            "subject": "Distributed Systems",
            "topic": "Raft",
            "marks": 10,
            "prompt": "Explain how Raft handles split votes during leader election.",
            "rubric": {
                "title": "Raft Election Rubric",
                "model_answer": "Randomized election timeouts prevent repeated split votes.",
                "criteria": [
                    {
                        "title": "Randomized Timeouts",
                        "description": "Explains election timer randomization",
                        "max_marks": 6,
                        "key_concepts": ["election timeout", "split vote", "term"],
                    },
                    {
                        "title": "Majority Quorum",
                        "description": "Explains RequestVote majority rule",
                        "max_marks": 4,
                        "key_concepts": ["quorum", "RequestVote"],
                    },
                ],
            },
        },
        headers=headers,
    )
    assert desc_resp.status_code == 201
    desc_q = desc_resp.get_json()["data"]["question"]
    desc_id = desc_q["question_id"]
    assert desc_q["rubric_id"] is not None
    assert desc_q["rubric_snapshot"]["max_marks"] == 10

    # 4. Cannot publish exam with 0 questions
    now = datetime.now(timezone.utc)
    bad_exam = client.post(
        "/api/examiner/exams",
        json={
            "title": "Empty Exam",
            "course_code": "CS401",
            "status": "published",
            "scheduled_start": (now - timedelta(minutes=10)).isoformat(),
            "scheduled_end": (now + timedelta(hours=2)).isoformat(),
            "duration_minutes": 60,
            "passing_marks": 0,
            "question_ids": [],
        },
        headers=headers,
    )
    assert bad_exam.status_code == 400

    # 5. Create and publish valid exam
    exam_resp = client.post(
        "/api/examiner/exams",
        json={
            "title": "CS401 Midterm",
            "course_code": "CS401",
            "status": "published",
            "scheduled_start": (now - timedelta(minutes=10)).isoformat(),
            "scheduled_end": (now + timedelta(hours=2)).isoformat(),
            "duration_minutes": 45,
            "passing_marks": 6,
            "question_ids": [mcq_id, desc_id],
            "rubric_audit_enabled": True,
        },
        headers=headers,
    )
    assert exam_resp.status_code == 201
    exam = exam_resp.get_json()["data"]["exam"]
    assert exam["total_marks"] == 12.0
    assert exam["mcq_count"] == 1
    assert exam["descriptive_count"] == 1

    # 6. Ownership isolation: ex2 cannot edit ex1's exam
    headers2 = login_as(client, auth_gateway, uid="ex2", email="ex2@uni.edu", role="examiner")
    forbidden_edit = client.get(f"/api/examiner/exams/{exam['exam_id']}", headers=headers2)
    assert forbidden_edit.status_code == 403

