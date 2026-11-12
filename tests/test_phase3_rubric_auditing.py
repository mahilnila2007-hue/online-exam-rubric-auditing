"""Integration and NLP unit tests for Phase 3: Intelligent Rubric Auditing and Alternative Phrase Detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.nlp_engine import CalibratedHybridNlpEngine
from tests.conftest import login_as, seed_user


def test_nlp_engine_exact_paraphrase_and_unrelated_scenarios():
    engine = CalibratedHybridNlpEngine()
    criterion = {
        "title": "Split-Vote Resolution",
        "description": "Explain how Raft prevents repeated election ties.",
        "key_concepts": ["election timeout", "split vote"],
        "alternative_phrases": [],
    }
    prompt = "Explain split-vote resolution in Raft leader election."
    model_answer = "Randomized election timeouts break split vote ties quickly."

    # 1. Exact rubric keyword found -> zero missing-phrase gap suggestions
    exact_hits = engine.detect_alternative_phrases(
        answer_text="Raft uses a randomized election timeout so nodes avoid a split vote.",
        criterion=criterion,
        question_prompt=prompt,
        model_answer=model_answer,
    )
    assert exact_hits == []

    # 2. Relevant concept expressed using a different phrase -> detected cleanly
    paraphrase_hits = engine.detect_alternative_phrases(
        answer_text="A randomized waiting interval prevents a tie during voting.",
        criterion=criterion,
        question_prompt=prompt,
        model_answer=model_answer,
    )
    expected_map = {h.expected_phrase: h for h in paraphrase_hits}
    assert "split vote" in expected_map
    assert expected_map["split vote"].suggested_phrase == "tie during voting"
    assert expected_map["split vote"].confidence_score >= 0.70

    # 3. Unrelated phrase sharing a superficial word ('timeout') -> rejected by context grounding
    unrelated_hits = engine.detect_alternative_phrases(
        answer_text="A database connection timeout happens on restaurant menu servers.",
        criterion=criterion,
        question_prompt=prompt,
        model_answer=model_answer,
    )
    assert unrelated_hits == []

    # 3b. Negated concept -> rejected
    negated_hits = engine.detect_alternative_phrases(
        answer_text="Nodes never encounter a tie during voting without randomized delays.",
        criterion=criterion,
        question_prompt=prompt,
        model_answer=model_answer,
    )
    assert all(h.suggested_phrase != "tie during voting" for h in negated_hits)


def _setup_auditable_exam(client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner", full_name="Prof. Raft")
    seed_user(repos, auth_gateway, uid="ex2", email="ex2@uni.edu", role="examiner", full_name="Prof. Intruder")
    seed_user(repos, auth_gateway, uid="s1", email="s1@uni.edu", role="student", full_name="Alice", inst_id="S-01")
    seed_user(repos, auth_gateway, uid="s2", email="s2@uni.edu", role="student", full_name="Bob", inst_id="S-02")

    ex1_h = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")

    q_desc = client.post(
        "/api/examiner/questions",
        json={
            "type": "descriptive",
            "difficulty": "hard",
            "subject": "Distributed Systems",
            "marks": 10,
            "prompt": "Explain split vote resolution and majority quorum in Raft.",
            "rubric": {
                "title": "Raft Rubric",
                "model_answer": "Randomized election timeouts resolve split votes; majority quorum ensures one leader.",
                "criteria": [
                    {
                        "title": "Split-Vote Handling",
                        "description": "How Raft resolves voting ties",
                        "max_marks": 5,
                        "key_concepts": ["split vote"],
                        "alternative_phrases": [],
                    },
                    {
                        "title": "Quorum Rule",
                        "description": "How Raft guarantees single leader safety",
                        "max_marks": 5,
                        "key_concepts": ["majority quorum"],
                        "alternative_phrases": [],
                    },
                ],
            },
        },
        headers=ex1_h,
    ).get_json()["data"]["question"]

    now = datetime.now(timezone.utc)
    exam = client.post(
        "/api/examiner/exams",
        json={
            "title": "CS510 Consensus Exam",
            "course_code": "CS510",
            "status": "published",
            "scheduled_start": (now - timedelta(minutes=10)).isoformat(),
            "scheduled_end": (now + timedelta(hours=2)).isoformat(),
            "duration_minutes": 60,
            "passing_marks": 6,
            "question_ids": [q_desc["question_id"]],
            "rubric_audit_enabled": True,
        },
        headers=ex1_h,
    ).get_json()["data"]["exam"]

    # Student 1 uses alternative phrasing for both criteria ('tie during voting' and 'consensus from more than half')
    s1_h = login_as(client, auth_gateway, uid="s1", email="s1@uni.edu", role="student")
    client.post(f"/api/student/exams/{exam['exam_id']}/start", json={}, headers=s1_h)
    sub1 = client.post(
        f"/api/student/exams/{exam['exam_id']}/submit",
        json={
            "answers": {
                q_desc["question_id"]: {
                    "text_answer": "A tie during voting is broken by timers, and consensus from more than half picks one leader."
                }
            }
        },
        headers=s1_h,
    ).get_json()["data"]["submission"]

    # Student 2 uses exact keyword for quorum, unrelated wording for split vote
    s2_h = login_as(client, auth_gateway, uid="s2", email="s2@uni.edu", role="student")
    client.post(f"/api/student/exams/{exam['exam_id']}/start", json={}, headers=s2_h)
    sub2 = client.post(
        f"/api/student/exams/{exam['exam_id']}/submit",
        json={
            "answers": {
                q_desc["question_id"]: {
                    "text_answer": "A majority quorum elects a leader while database connection timeout stays unrelated."
                }
            }
        },
        headers=s2_h,
    ).get_json()["data"]["submission"]

    # Examiner runs Phase 2 evaluation on Student 1: Student 1 gets 0/10 initially because exact keywords were missing,
    # and result is published at 0/10 FAIL!
    ex1_h = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")
    ws1 = client.get(f"/api/examiner/submissions/{sub1['submission_id']}/evaluation").get_json()["data"]
    c_ids = [c["criterion_id"] for c in ws1["descriptive_questions"][0]["criteria"]]
    client.put(
        f"/api/examiner/submissions/{sub1['submission_id']}/evaluate",
        json={
            "examiner_feedback": "Missing exact rubric terms initially.",
            "publish_result": True,
            "question_evaluations": {
                q_desc["question_id"]: {
                    "feedback": "Exact keywords not found.",
                    "criteria_scores": [
                        {"criterion_id": c_ids[0], "awarded_marks": 0.0, "feedback": "Missing split vote"},
                        {"criterion_id": c_ids[1], "awarded_marks": 0.0, "feedback": "Missing majority quorum"},
                    ],
                }
            },
        },
        headers=ex1_h,
    )

    return exam, q_desc, sub1, sub2


def test_phase3_audit_approval_rejection_reevaluation_history_and_rbac(client, repos, auth_gateway):
    exam, q_desc, sub1, sub2 = _setup_auditable_exam(client, repos, auth_gateway)
    exam_id = exam["exam_id"]
    rubric_id = q_desc["rubric_id"]

    # 10. Unauthorized users (student & non-owning examiner) cannot run audit or approve/reject
    s1_h = login_as(client, auth_gateway, uid="s1", email="s1@uni.edu", role="student")
    assert client.post(f"/api/examiner/exams/{exam_id}/audit", json={}, headers=s1_h).status_code == 403
    assert client.get("/examiner/audit").status_code == 403

    ex2_h = login_as(client, auth_gateway, uid="ex2", email="ex2@uni.edu", role="examiner")
    assert client.post(f"/api/examiner/exams/{exam_id}/audit", json={}, headers=ex2_h).status_code == 403

    # Owning examiner runs intelligent rubric audit
    ex1_h = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")
    assert client.get(f"/examiner/audit?exam_id={exam_id}").status_code == 200

    audit_resp = client.post(
        f"/api/examiner/exams/{exam_id}/audit",
        json={"confidence_threshold": 0.56},
        headers=ex1_h,
    )
    assert audit_resp.status_code == 201
    audit_data = audit_resp.get_json()["data"]
    assert audit_data["report"]["total_submissions_analyzed"] == 2

    # Duplicate audit processing on identical state must be prevented (409)
    dup_audit = client.post(
        f"/api/examiner/exams/{exam_id}/audit",
        json={"confidence_threshold": 0.56},
        headers=ex1_h,
    )
    assert dup_audit.status_code == 409
    assert dup_audit.get_json()["error"]["code"] == "DUPLICATE_AUDIT_PREVENTED"

    # 4. Potential rubric gaps detected cleanly without altering marks automatically
    dash = client.get(f"/api/examiner/audit?exam_id={exam_id}&status=pending").get_json()["data"]
    suggestions = dash["suggestions"]
    assert len(suggestions) == 2
    by_expected = {s["expected_phrase"]: s for s in suggestions}
    assert "split vote" in by_expected
    assert "majority quorum" in by_expected
    assert by_expected["split vote"]["affected_count"] == 1
    assert repos["results"].get_by_exam_and_student(exam_id, "s1")["obtained_marks"] == 0.0

    # Non-owning examiner cannot approve or reject ex1's suggestion
    sug_split = by_expected["split vote"]["suggestion_id"]
    sug_quorum = by_expected["majority quorum"]["suggestion_id"]
    ex2_h = login_as(client, auth_gateway, uid="ex2", email="ex2@uni.edu", role="examiner")
    assert client.post(f"/api/examiner/audit/suggestions/{sug_split}/approve", json={}, headers=ex2_h).status_code == 403
    assert client.post(f"/api/examiner/audit/suggestions/{sug_quorum}/reject", json={}, headers=ex2_h).status_code == 403

    # 5, 7, 8, 9. Examiner approves 'tie during voting' for 'split vote'
    ex1_h = login_as(client, auth_gateway, uid="ex1", email="ex1@uni.edu", role="examiner")
    app_resp = client.post(
        f"/api/examiner/audit/suggestions/{sug_split}/approve",
        json={"approval_note": "Valid domain phrasing for split vote"},
        headers=ex1_h,
    )
    assert app_resp.status_code == 200
    app_data = app_resp.get_json()["data"]

    # Rubric version incremented & previous version v1 preserved
    assert app_data["rubric"]["version"] == 2
    versions = client.get(f"/api/examiner/rubrics/{rubric_id}/versions").get_json()["data"]["versions"]
    assert len(versions) == 1
    assert versions[0]["version_number"] == 1
    assert versions[0]["rubric_data"]["criteria"][0]["alternative_phrases"] == []

    # Re-evaluation updated Student 1's marks (0 -> 5 on Split-Vote Handling => 5/10 = 50% Grade D)
    assert app_data["reevaluation_summary"]["affected_count"] == 1
    assert app_data["reevaluation_summary"]["updated_count"] == 1
    updated_sub1 = repos["submissions"].get_by_id(sub1["submission_id"])
    assert updated_sub1["grading"]["descriptive_score"] == 5.0
    assert updated_sub1["grading"]["total_score"] == 5.0

    # Previous evaluation record preserved intact inside evaluation_history!
    assert len(updated_sub1["grading"]["evaluation_history"]) == 1
    prior_snap = updated_sub1["grading"]["evaluation_history"][0]
    assert prior_snap["rubric_version_before"] == 1
    assert prior_snap["descriptive_score_before"] == 0.0
    assert prior_snap["total_score_before"] == 0.0

    # Published result updated & revision history + student notification created
    updated_res1 = repos["results"].get_by_exam_and_student(exam_id, "s1")
    assert updated_res1["obtained_marks"] == 5.0
    assert updated_res1["percentage"] == 50.0
    assert len(updated_res1["revision_history"]) == 1

    # 6. Examiner rejects 'majority quorum' suggestion -> rubric version stays 2, marks remain 5.0
    rej_resp = client.post(
        f"/api/examiner/audit/suggestions/{sug_quorum}/reject",
        json={"reason": "Too vague without explicit quorum threshold"},
        headers=ex1_h,
    )
    assert rej_resp.status_code == 200
    assert repos["rubrics"].get_by_id(rubric_id)["version"] == 2
    assert repos["submissions"].get_by_id(sub1["submission_id"])["grading"]["total_score"] == 5.0

    # Cannot approve an already rejected suggestion
    assert client.post(f"/api/examiner/audit/suggestions/{sug_quorum}/approve", json={}, headers=ex1_h).status_code == 409

    # Audit dashboard filters & audit history completeness
    approved_list = client.get(f"/api/examiner/audit?exam_id={exam_id}&status=approved").get_json()["data"]["suggestions"]
    rejected_list = client.get(f"/api/examiner/audit?exam_id={exam_id}&status=rejected").get_json()["data"]["suggestions"]
    assert len(approved_list) == 1
    assert len(rejected_list) == 1

    full_history = client.get(f"/api/examiner/audit?exam_id={exam_id}").get_json()["data"]["history"]
    event_types = {h["event_type"] for h in full_history}
    assert {"AUDIT_RUN", "RUBRIC_VERSION_SAVED", "SUBMISSION_REEVALUATED", "SUGGESTION_APPROVED", "SUGGESTION_REJECTED"} <= event_types

    # Student 1 receives notification and can mark it read
    s1_h = login_as(client, auth_gateway, uid="s1", email="s1@uni.edu", role="student")
    notifs = client.get("/api/student/notifications").get_json()["data"]["notifications"]
    assert len(notifs) == 1
    assert notifs[0]["previous_marks"] == 0.0
    assert notifs[0]["updated_marks"] == 5.0
    assert client.post(f"/api/student/notifications/{notifs[0]['notification_id']}/read", json={}, headers=s1_h).status_code == 200

