"""Integration tests for Excel multi-tier question set template, upload, filtering, and evaluation."""

from __future__ import annotations

import io
import openpyxl

from tests.conftest import login_as, seed_user


def _build_custom_set_workbook() -> bytes:
    """Create a workbook with separate 1M questions sheet, Options sheet, 2M sheet, and 5M sheet."""
    wb = openpyxl.Workbook()

    ws_1m = wb.active
    ws_1m.title = "1_Mark_MCQ"
    ws_1m.append(["Set Name", "QNo", "Subject", "Topic", "Difficulty", "Question Prompt", "Marks", "Correct Option"])
    ws_1m.append(["Set Beta", "Q1", "DBMS", "Normalization", "easy", "Which normal form removes partial functional dependencies?", 1, "B"])
    ws_1m.append(["Set Beta", "Q2", "DBMS", "Indexing", "medium", "Which structure keeps keys balanced in sorted order for range queries?", 1, ""])

    ws_opts = wb.create_sheet("Options")
    ws_opts.append(["Set Name", "QNo", "Option A", "Option B", "Option C", "Option D"])
    ws_opts.append(["Set Beta", "Q1", "1NF", "2NF", "3NF", "BCNF"])

    ws_opts_long = wb.create_sheet("MCQ_Options_Long")
    ws_opts_long.append(["Set Name", "QNo", "Option Text", "Is Correct"])
    ws_opts_long.append(["Set Beta", "Q2", "Hash Table", "false"])
    ws_opts_long.append(["Set Beta", "Q2", "B+ Tree", "true"])
    ws_opts_long.append(["Set Beta", "Q2", "Heap File", "false"])

    ws_2m = wb.create_sheet("2_Mark_Questions")
    ws_2m.append(["Set Name", "Subject", "Topic", "Question Prompt", "Marks", "Criterion Title", "Expected Keywords", "Alternative Phrases", "Model Answer"])
    ws_2m.append([
        "Set Beta",
        "DBMS",
        "Transactions",
        "State ACID atomicity in transaction processing.",
        2,
        "Atomicity Definition",
        "all or nothing, rollback",
        "complete completely or undo, abort changes",
        "Atomicity guarantees all operations commit together or rollback cleanly.",
    ])

    ws_5m = wb.create_sheet("5_Mark_Questions")
    ws_5m.append([
        "Set Name", "Subject", "Topic", "Difficulty", "Question Prompt", "Marks",
        "Criterion 1 Title", "Criterion 1 Marks", "Criterion 1 Keywords", "Criterion 1 Alternative Phrases",
        "Criterion 2 Title", "Criterion 2 Marks", "Criterion 2 Keywords", "Criterion 2 Alternative Phrases",
        "Model Answer",
    ])
    ws_5m.append([
        "Set Beta", "DBMS", "Concurrency Control", "hard",
        "Explain Two-Phase Locking (2PL) and compare growing vs shrinking phases.",
        5,
        "2PL Phases", 2.5, "growing phase, shrinking phase", "acquire locks, release locks",
        "Serializability & Deadlock Tradeoff", 2.5, "conflict serializable, deadlock", "strict 2PL, lock contention",
        "2PL acquires all locks in the growing phase before releasing any in the shrinking phase, ensuring conflict serializability though deadlocks can still happen.",
    ])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_download_template_and_roundtrip_import_with_exam_creation(client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="ex_xl", email="ex_xl@uni.edu", role="examiner", full_name="Prof. Lin")
    seed_user(repos, auth_gateway, uid="stu_xl", email="stu_xl@uni.edu", role="student", full_name="Stu Lin")

    # Students must not access examiner Excel endpoints
    stu_headers = login_as(client, auth_gateway, uid="stu_xl", email="stu_xl@uni.edu", role="student")
    assert client.get("/api/examiner/questions/excel-template").status_code == 403
    assert client.post(
        "/api/examiner/questions/import-excel",
        data={"file": (io.BytesIO(b"a,b\n1,2"), "q.csv")},
        content_type="multipart/form-data",
        headers=stu_headers,
    ).status_code == 403
    client.post("/api/auth/logout", json={}, headers=stu_headers)

    ex_headers = login_as(client, auth_gateway, uid="ex_xl", email="ex_xl@uni.edu", role="examiner")

    # Download sample multi-sheet template (.xlsx)
    tpl_resp = client.get("/api/examiner/questions/excel-template")
    assert tpl_resp.status_code == 200
    assert "spreadsheetml" in tpl_resp.content_type
    wb = openpyxl.load_workbook(io.BytesIO(tpl_resp.data))
    assert wb.sheetnames == [
        "Instructions",
        "All_In_One_Set",
        "1_Mark_MCQ",
        "2_Mark_Questions",
        "5_Mark_Questions",
    ]
    assert wb["Instructions"]["B4"].alignment.wrap_text is True
    assert wb["Instructions"].column_dimensions["B"].width >= 50
    # Verify All_In_One_Set has separate MCQ question cell with side-by-side options and spacer gaps
    ws_all = wb["All_In_One_Set"]
    assert ws_all["F3"].value == "1-Mark MCQ Question"
    assert [ws_all[f"{col}3"].value for col in ("G", "H", "I", "J", "K")] == [
        "Option A",
        "Option B",
        "Option C",
        "Option D",
        "Correct Option",
    ]
    assert not ws_all["E3"].value
    assert not ws_all["L3"].value
    assert not ws_all["Q3"].value
    assert ws_all["M3"].value == "2-Mark Question"
    assert ws_all["R3"].value == "5-Mark Question"
    wb.close()

    # Preview template upload
    prev_resp = client.post(
        "/api/examiner/questions/import-excel",
        data={
            "mode": "preview",
            "file": (io.BytesIO(tpl_resp.data), "RubriAssess_Question_Set_Template.xlsx"),
        },
        content_type="multipart/form-data",
        headers=ex_headers,
    )
    assert prev_resp.status_code == 200
    prev = prev_resp.get_json()["data"]
    assert prev["error_count"] == 0
    assert prev["valid_count"] == 10
    assert prev["tier_summary"] == {"1_mark": 4, "2_mark": 4, "5_mark": 2, "other": 0}
    assert prev["sets"] == ["Combined Set A", "Midterm Set A"]

    # Commit upload + automatically create draft exam from the set
    commit_resp = client.post(
        "/api/examiner/questions/import-excel",
        data={
            "mode": "commit",
            "create_exam": "true",
            "exam_title": "OS Midterm Set A Exam",
            "course_code": "CS301",
            "file": (io.BytesIO(tpl_resp.data), "RubriAssess_Question_Set_Template.xlsx"),
        },
        content_type="multipart/form-data",
        headers=ex_headers,
    )
    assert commit_resp.status_code == 201
    imported = commit_resp.get_json()["data"]
    assert imported["imported_count"] == 10
    assert imported["created_exam"]["title"] == "OS Midterm Set A Exam"
    assert imported["created_exam"]["total_marks"] == 22.0
    assert [q["marks"] for q in imported["created_questions"]] == [
        1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 2.0, 5.0, 5.0
    ]

    # Filtering Question Bank by Set and Marks returns expected tiers
    resp_2m = client.get("/api/examiner/questions?question_set=Midterm+Set+A&marks=2")
    assert resp_2m.status_code == 200
    assert len(resp_2m.get_json()["data"]["questions"]) == 2
    assert all(q["rubric_id"] for q in resp_2m.get_json()["data"]["questions"])

    resp_combined_5m = client.get("/api/examiner/questions?question_set=Combined+Set+A&marks=5")
    assert resp_combined_5m.status_code == 200
    assert len(resp_combined_5m.get_json()["data"]["questions"]) == 1


def test_separate_options_sheet_and_csv_and_validation_errors(client, repos, auth_gateway):
    seed_user(repos, auth_gateway, uid="ex_opt", email="ex_opt@uni.edu", role="examiner", full_name="Prof. Rao")
    ex_headers = login_as(client, auth_gateway, uid="ex_opt", email="ex_opt@uni.edu", role="examiner")

    # Separate 1M + Options + 2M + 5M workbook
    wb_bytes = _build_custom_set_workbook()
    resp = client.post(
        "/api/examiner/questions/import-excel",
        data={"mode": "commit", "file": (io.BytesIO(wb_bytes), "dbms_set_beta.xlsx")},
        content_type="multipart/form-data",
        headers=ex_headers,
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["imported_count"] == 4
    assert data["tier_summary"] == {"1_mark": 2, "2_mark": 1, "5_mark": 1, "other": 0}
    assert data["sets"] == ["Set Beta"]

    mcqs = [q for q in data["created_questions"] if q["type"] == "mcq"]
    assert mcqs[0]["correct_option_id"] == "opt_2"
    assert len(mcqs[0]["options"]) == 4
    assert mcqs[1]["correct_option_id"] == "opt_2"
    assert [o["text"] for o in mcqs[1]["options"]] == ["Hash Table", "B+ Tree", "Heap File"]

    # CSV upload + error reporting + skip_invalid mode
    csv_text = (
        "Set Name,Subject,Type,Question Prompt,Marks,Option A,Option B,Correct Option,Expected Keywords\n"
        "Set CSV,Algorithms,mcq,Which sort uses divide and conquer with O(n log n) worst case?,1,Bubble Sort,Merge Sort,B,\n"
        "Set CSV,Algorithms,mcq,Broken MCQ with bad key?,1,Yes,No,Z,\n"
        "Set CSV,Algorithms,descriptive,Explain asymptotic Big-O notation with one example.,5,,,,upper bound, growth rate\n"
    ).encode("utf-8")

    err_preview = client.post(
        "/api/examiner/questions/import-excel",
        data={"mode": "commit", "skip_invalid": "false", "file": (io.BytesIO(csv_text), "algo.csv")},
        content_type="multipart/form-data",
        headers=ex_headers,
    )
    assert err_preview.status_code == 400
    assert len(err_preview.get_json()["error"]["details"]["errors"]) == 1

    partial_commit = client.post(
        "/api/examiner/questions/import-excel",
        data={"mode": "commit", "skip_invalid": "true", "file": (io.BytesIO(csv_text), "algo.csv")},
        content_type="multipart/form-data",
        headers=ex_headers,
    )
    assert partial_commit.status_code == 201
    part_data = partial_commit.get_json()["data"]
    assert part_data["imported_count"] == 2
    assert part_data["skipped_count"] == 1

