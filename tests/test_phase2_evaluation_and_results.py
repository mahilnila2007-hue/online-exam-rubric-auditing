"""Integration tests for Phase 2: MCQ marking rules, rubric evaluation, and result management."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import login_as, seed_user


def _seed_exam_and_submission(
    client,
    repos,
    auth_gateway,
    *,
    negative_marking_enabled: bool = False,
    negative_mark_fraction: float = 0.0,
    mcq1_choice: str = "opt_1",
    mcq2_choice: str = "opt_2",
    desc_text: str = "Randomized timer backoff resolves split vote ties while majority quorum preserves safety.",
):
    seed_user(repos, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner", full_name="Prof. Dijkstra")
    seed_user(repos, auth_gateway, uid="ex2", email="ex2@uni.edu", role="examiner", full_name="Prof. Lamport")
    seed_user(repos, auth_gateway, uid="stu1", email="stu1@uni.edu", role="student", full_name="Alice", inst_id="S-101")
    seed_user(repos, auth_gateway, uid="stu2", email="stu2@uni.edu", role="student", full_name="Bob", inst_id="S-102")

    ex_headers = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")

    q_mcq1 = client.post(
        "/api/examiner/questions",
        json={
            "type": "mcq",
            "difficulty": "easy",
            "subject": "Distributed Systems",
            "marks": 4,
            "prompt": "Which algorithm elects a single leader via randomized timeouts?",
            "options": [{"id": "opt_1", "text": "Raft"}, {"id": "opt_2", "text": "Bubble Sort"}],
            "correct_option_id": "opt_1",
            "explanation": "Raft uses randomized election timeouts.",
        },
        headers=ex_headers,
    ).get_json()["data"]["question"]["question_id"]

    q_mcq2 = client.post(
        "/api/examiner/questions",
        json={
            "type": "mcq",
            "difficulty": "medium",
            "subject": "Distributed Systems",
            "marks": 4,
            "prompt": "CAP theorem states a partitioned system must trade off consistency and?",
            "options": [{"id": "opt_1", "text": "Availability"}, {"id": "opt_2", "text": "Encryption"}],
            "correct_option_id": "opt_1",
        },
        headers=ex_headers,
    ).get_json()["data"]["question"]["question_id"]

    q_desc = client.post(
        "/api/examiner/questions",
        json={
            "type": "descriptive",
            "difficulty": "hard",
            "subject": "Distributed Systems",
            "marks": 12,
            "prompt": "Explain split-vote resolution and quorum safety in Raft.",
            "rubric": {
                "title": "Raft Consensus Rubric",
                "model_answer": "Randomized election timeouts break split votes; majority quorum ensures one leader per term.",
                "criteria": [
                    {
                        "title": "Split-Vote Resolution",
                        "description": "Explains election timeout randomization",
                        "max_marks": 6,
                        "key_concepts": ["election timeout", "split vote"],
                        "alternative_phrases": ["randomized timer"],
                    },
                    {
                        "title": "Quorum Agreement",
                        "description": "Explains majority quorum safety",
                        "max_marks": 6,
                        "key_concepts": ["majority quorum", "safety"],
                        "alternative_phrases": ["more than half"],
                    },
                ],
            },
        },
        headers=ex_headers,
    ).get_json()["data"]["question"]["question_id"]

    now = datetime.now(timezone.utc)
    exam = client.post(
        "/api/examiner/exams",
        json={
            "title": "Distributed Consensus Exam",
            "course_code": "CS501",
            "status": "published",
            "scheduled_start": (now - timedelta(minutes=10)).isoformat(),
            "scheduled_end": (now + timedelta(hours=2)).isoformat(),
            "duration_minutes": 60,
            "passing_marks": 12,
            "negative_marking_enabled": negative_marking_enabled,
            "negative_mark_fraction": negative_mark_fraction,
            "grade_rules": [
                {"grade": "HD", "min_percentage": 85},
                {"grade": "D", "min_percentage": 70},
                {"grade": "P", "min_percentage": 50},
                {"grade": "F", "min_percentage": 0},
            ],
            "question_ids": [q_mcq1, q_mcq2, q_desc],
            "rubric_audit_enabled": True,
        },
        headers=ex_headers,
    ).get_json()["data"]["exam"]

    # Student 1 attends and submits
    stu_headers = login_as(client, auth_gateway, uid="stu1", email="stu1@uni.edu", role="student")
    client.post(f"/api/student/exams/{exam['exam_id']}/start", json={}, headers=stu_headers)
    submit = client.post(
        f"/api/student/exams/{exam['exam_id']}/submit",
        json={
            "answers": {
                q_mcq1: {"selected_option_id": mcq1_choice},
                q_mcq2: {"selected_option_id": mcq2_choice},
                q_desc: {"text_answer": desc_text},
            }
        },
        headers=stu_headers,
    ).get_json()["data"]["submission"]

    return exam, submit, q_mcq1, q_mcq2, q_desc


def test_mcq_negative_marking_and_duplicate_submission_protection(client, repos, auth_gateway):
    # 1 correct (+4) and 1 wrong with 0.25 penalty (-1) => MCQ score 3.0
    exam, sub, q_mcq1, q_mcq2, _ = _seed_exam_and_submission(
        client,
        repos,
        auth_gateway,
        negative_marking_enabled=True,
        negative_mark_fraction=0.25,
        mcq1_choice="opt_1",
        mcq2_choice="opt_2",
    )
    assert sub["grading"]["mcq_score"] == 3.0
    assert sub["grading"]["negative_deductions"] == 1.0

    # Duplicate submission returns existing finalized submission without re-evaluating
    stu_headers = login_as(client, auth_gateway, uid="stu1", email="stu1@uni.edu", role="student")
    dup_resp = client.post(
        f"/api/student/exams/{exam['exam_id']}/submit",
        json={"answers": {q_mcq2: {"selected_option_id": "opt_1"}}},
        headers=stu_headers,
    )
    assert dup_resp.status_code == 200
    assert dup_resp.get_json()["data"]["submission"]["grading"]["mcq_score"] == 3.0


def test_descriptive_rubric_evaluation_examiner_override_and_result_publication(client, repos, auth_gateway):
    # 2 MCQs correct (8.0) + descriptive answer matching 1 key concept + 1 alternative phrase per criterion
    exam, sub, _, _, q_desc = _seed_exam_and_submission(
        client,
        repos,
        auth_gateway,
        negative_marking_enabled=False,
        mcq1_choice="opt_1",
        mcq2_choice="opt_1",
        desc_text="Using a randomized timer resolves split vote issues, and majority quorum ensures safety.",
    )
    exam_id = exam["exam_id"]
    sub_id = sub["submission_id"]

    # Student cannot view unpublished result or access examiner evaluation routes
    assert client.get("/api/student/results").get_json()["data"]["results"] == []
    assert client.get(f"/api/student/results/{sub_id}").status_code == 404
    stu_headers = login_as(client, auth_gateway, uid="stu1", email="stu1@uni.edu", role="student")
    assert client.post(f"/api/examiner/submissions/{sub_id}/auto-evaluate", json={}, headers=stu_headers).status_code == 403

    # Non-owning examiner (ex2) cannot evaluate or publish
    ex2_headers = login_as(client, auth_gateway, uid="ex2", email="ex2@uni.edu", role="examiner")
    assert client.post(f"/api/examiner/submissions/{sub_id}/auto-evaluate", json={}, headers=ex2_headers).status_code == 403
    assert client.get(f"/api/examiner/exams/{exam_id}/results", headers=ex2_headers).status_code == 403

    # Owning examiner (ex1) cannot publish un-evaluated descriptive result
    ex1_headers = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")
    premature_pub = client.post(f"/api/examiner/submissions/{sub_id}/publish-result", json={}, headers=ex1_headers)
    assert premature_pub.status_code == 400

    # Run preliminary transparent rubric evaluation
    pre_resp = client.post(f"/api/examiner/submissions/{sub_id}/auto-evaluate", json={}, headers=ex1_headers)
    assert pre_resp.status_code == 200
    pre_sub = pre_resp.get_json()["data"]["submission"]
    assert pre_sub["grading"]["evaluation_status"] == "preliminary_evaluated"
    # Both criteria covered 2/2 concept slots via key_concepts + alternative_phrases => 12.0 suggested
    assert pre_sub["grading"]["descriptive_score"] == 12.0

    # Duplicate preliminary auto-evaluation must be prevented (409)
    dup_eval = client.post(f"/api/examiner/submissions/{sub_id}/auto-evaluate", json={}, headers=ex1_headers)
    assert dup_eval.status_code == 409
    assert dup_eval.get_json()["error"]["code"] == "DUPLICATE_EVALUATION_PREVENTED"

    # Load evaluation workspace & inspect criterion IDs
    assert client.get(f"/examiner/exams/{exam_id}/results").status_code == 200
    assert client.get(f"/examiner/evaluations/{sub_id}").status_code == 200
    ws = client.get(f"/api/examiner/submissions/{sub_id}/evaluation").get_json()["data"]
    criteria = ws["descriptive_questions"][0]["criteria"]
    assert len(criteria) == 2

    # Marks exceeding criterion max_marks must be rejected (400)
    bad_marks = client.put(
        f"/api/examiner/submissions/{sub_id}/evaluate",
        json={
            "examiner_feedback": "Test",
            "publish_result": False,
            "question_evaluations": {
                q_desc: {
                    "feedback": "Too high",
                    "criteria_scores": [
                        {"criterion_id": criteria[0]["criterion_id"], "awarded_marks": 99, "feedback": ""},
                        {"criterion_id": criteria[1]["criterion_id"], "awarded_marks": 5, "feedback": ""},
                    ],
                }
            },
        },
        headers=ex1_headers,
    )
    assert bad_marks.status_code == 400

    # Examiner modifies marks (5.0 + 4.0 = 9.0 descriptive + 8.0 MCQ = 17.0 / 20.0 = 85% => Grade HD, PASS)
    eval_resp = client.put(
        f"/api/examiner/submissions/{sub_id}/evaluate",
        json={
            "examiner_feedback": "Strong grasp of split-vote timers; elaborate slightly more on log replication.",
            "publish_result": True,
            "question_evaluations": {
                q_desc: {
                    "feedback": "Clear explanation overall.",
                    "criteria_scores": [
                        {"criterion_id": criteria[0]["criterion_id"], "awarded_marks": 5.0, "feedback": "Good timer analysis"},
                        {"criterion_id": criteria[1]["criterion_id"], "awarded_marks": 4.0, "feedback": "Add term check detail"},
                    ],
                }
            },
        },
        headers=ex1_headers,
    )
    assert eval_resp.status_code == 200
    eval_data = eval_resp.get_json()["data"]
    assert eval_data["submission"]["grading"]["descriptive_score"] == 9.0
    assert eval_data["submission"]["grading"]["total_score"] == 17.0
    assert eval_data["submission"]["grading"]["evaluation_status"] == "evaluated"
    assert len(eval_data["submission"]["grading"]["decision_history"]) == 1
    assert eval_data["submission"]["grading"]["rubric_evaluations"][q_desc]["criteria_scores"][0]["examiner_override"] is True

    result = eval_data["result"]
    assert result["obtained_marks"] == 17.0
    assert result["total_marks"] == 20.0
    assert result["percentage"] == 85.0
    assert result["grade"] == "HD"
    assert result["pass_status"] == "PASS"
    assert result["publication_status"] == "published"

    # Prevent duplicate result documents in repository even if re-saved or re-published
    client.post(f"/api/examiner/exams/{exam_id}/publish-results", json={}, headers=ex1_headers)
    assert len(repos["results"].list_by_exam(exam_id)) == 1

    # Student 1 views published result & HTML pages
    login_as(client, auth_gateway, uid="stu1", email="stu1@uni.edu", role="student")
    assert client.get("/student/results").status_code == 200
    assert client.get(f"/student/results/{result['result_id']}").status_code == 200

    stu_results = client.get("/api/student/results").get_json()["data"]
    assert stu_results["summary"]["published_count"] == 1
    assert stu_results["results"][0]["grade"] == "HD"

    stu_detail = client.get(f"/api/student/results/{result['result_id']}").get_json()["data"]["result"]
    assert stu_detail["examiner_feedback"].startswith("Strong grasp")
    assert len(stu_detail["question_feedback"][2]["criteria_scores"]) == 2

    # Student 2 cannot access Student 1's result (403)
    login_as(client, auth_gateway, uid="stu2", email="stu2@uni.edu", role="student")
    assert client.get(f"/api/student/results/{result['result_id']}").status_code == 403


def test_batch_preliminary_evaluation_and_mcq_only_result_publication(client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="ex_b", email="exb@uni.edu", role="examiner", full_name="Prof. Batch")
    seed_user(repos, auth_gateway, uid="s_b1", email="sb1@uni.edu", role="student", full_name="Student B1", inst_id="SB-1")

    ex_h = login_as(client, auth_gateway, uid="ex_b", email="exb@uni.edu", role="examiner")
    q_mcq = client.post(
        "/api/examiner/questions",
        json={
            "type": "mcq",
            "difficulty": "easy",
            "subject": "Databases",
            "marks": 10,
            "prompt": "ACID stands for Atomicity, Consistency, Isolation, and?",
            "options": [{"id": "opt_1", "text": "Durability"}, {"id": "opt_2", "text": "Distribution"}],
            "correct_option_id": "opt_1",
        },
        headers=ex_h,
    ).get_json()["data"]["question"]["question_id"]

    now = datetime.now(timezone.utc)
    exam = client.post(
        "/api/examiner/exams",
        json={
            "title": "DBMS Quick Quiz",
            "course_code": "CS301",
            "status": "published",
            "scheduled_start": (now - timedelta(minutes=5)).isoformat(),
            "scheduled_end": (now + timedelta(hours=1)).isoformat(),
            "duration_minutes": 15,
            "passing_marks": 6,
            "question_ids": [q_mcq],
        },
        headers=ex_h,
    ).get_json()["data"]["exam"]

    # Student completes MCQ-only quiz
    stu_h = login_as(client, auth_gateway, uid="s_b1", email="sb1@uni.edu", role="student")
    client.post(f"/api/student/exams/{exam['exam_id']}/start", json={}, headers=stu_h)
    client.post(
        f"/api/student/exams/{exam['exam_id']}/submit",
        json={"answers": {q_mcq: {"selected_option_id": "opt_1"}}},
        headers=stu_h,
    )

    # Examiner runs batch process + publishes all evaluated results
    ex_h = login_as(client, auth_gateway, uid="ex_b", email="exb@uni.edu", role="examiner")
    batch_res = client.post(f"/api/examiner/exams/{exam['exam_id']}/process-evaluations", json={}, headers=ex_h).get_json()["data"]
    assert batch_res["skipped_count"] == 1  # Already completed MCQ-only submission

    pub_res = client.post(f"/api/examiner/exams/{exam['exam_id']}/publish-results", json={}, headers=ex_h).get_json()["data"]
    assert pub_res["published_count"] == 1

    overview = client.get(f"/api/examiner/exams/{exam['exam_id']}/results").get_json()["data"]
    assert overview["summary"]["published_count"] == 1
    assert overview["summary"]["average_percentage"] == 100.0
    assert overview["rows"][0]["grade"] == "A+"
    assert overview["rows"][0]["pass_status"] == "PASS"
