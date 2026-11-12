"""
Phase 3 Service: Intelligent Rubric Auditing, Alternative Phrase Detection,
Examiner Approval/Rejection Workflow, Versioned Rubric Updates, and Re-evaluation.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import logging
from typing import Any

from app.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.repositories.exam_repo import ExamRepository
from app.repositories.question_repo import QuestionRepository
from app.repositories.result_repo import ResultRepository
from app.repositories.rubric_audit_repo import (
    AuditHistoryRepository,
    AuditReportRepository,
    AuditSuggestionRepository,
    NotificationRepository,
    RubricVersionRepository,
)
from app.repositories.rubric_repo import RubricRepository
from app.repositories.submission_repo import SubmissionRepository
from app.services.audit_service import AuditService
from app.services.evaluation_service import evaluate_criterion_transparently
from app.services.nlp_engine import CalibratedHybridNlpEngine, exact_phrase_present
from app.services.question_service import _build_rubric_snapshot
from app.services.result_service import ResultService
from app.services.time_utils import utc_now
from app.validators.audit_validators import (
    validate_approve_suggestion_payload,
    validate_reject_suggestion_payload,
    validate_run_audit_payload,
)

logger = logging.getLogger(__name__)


class RubricAuditService:
    def __init__(
        self,
        *,
        exam_repo: ExamRepository,
        question_repo: QuestionRepository,
        rubric_repo: RubricRepository,
        submission_repo: SubmissionRepository,
        result_repo: ResultRepository,
        audit_report_repo: AuditReportRepository,
        audit_suggestion_repo: AuditSuggestionRepository,
        rubric_version_repo: RubricVersionRepository,
        audit_history_repo: AuditHistoryRepository,
        notification_repo: NotificationRepository,
        result_service: ResultService,
        audit_service: AuditService,
        nlp_engine: CalibratedHybridNlpEngine | None = None,
    ) -> None:
        self.exam_repo = exam_repo
        self.question_repo = question_repo
        self.rubric_repo = rubric_repo
        self.submission_repo = submission_repo
        self.result_repo = result_repo
        self.audit_report_repo = audit_report_repo
        self.audit_suggestion_repo = audit_suggestion_repo
        self.rubric_version_repo = rubric_version_repo
        self.audit_history_repo = audit_history_repo
        self.notification_repo = notification_repo
        self.result_service = result_service
        self.audit_service = audit_service
        self.nlp_engine = nlp_engine or CalibratedHybridNlpEngine()

    def _assert_examiner_owns(self, owner_uid: str, user: dict[str, Any], label: str = "resource") -> None:
        if user.get("role") == "admin":
            return
        if owner_uid != user.get("uid"):
            raise AuthorizationError(f"Only the owning examiner or an administrator can access this {label}.")

    def _record_history(
        self,
        *,
        exam_id: str,
        examiner_uid: str,
        rubric_id: str | None = None,
        suggestion_id: str | None = None,
        event_type: str,
        actor: dict[str, Any],
        details: dict[str, Any],
    ) -> dict[str, Any]:
        return self.audit_history_repo.create(
            {
                "exam_id": exam_id,
                "examiner_uid": examiner_uid,
                "rubric_id": rubric_id,
                "suggestion_id": suggestion_id,
                "event_type": event_type,
                "actor_uid": actor["uid"],
                "actor_name": actor.get("full_name", actor["email"]),
                "details": details,
            },
            doc_id=self.audit_history_repo.new_id("ahist"),
        )

    @staticmethod
    def _compute_audit_signature(
        exam_id: str,
        submissions: list[dict[str, Any]],
        rubrics_by_id: dict[str, dict[str, Any]],
        threshold: float,
    ) -> str:
        sig_payload = {
            "exam_id": exam_id,
            "threshold": round(threshold, 4),
            "subs": sorted(
                (s["submission_id"], str(s.get("submitted_at") or ""), len(s.get("answers", {})))
                for s in submissions
            ),
            "rubrics": sorted(
                (rid, int(r.get("version", 1)), len(r.get("criteria", [])))
                for rid, r in rubrics_by_id.items()
            ),
        }
        raw = json.dumps(sig_payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:20]

    def _resolve_question_rubric(self, question: dict[str, Any]) -> dict[str, Any] | None:
        rubric_id = question.get("rubric_id")
        if rubric_id:
            rubric = self.rubric_repo.get_by_id(rubric_id)
            if rubric:
                return rubric
        return question.get("rubric_snapshot")

    # ------------------------------------------------------------------
    # 1. Run Intelligent Rubric Audit (Gap & Alternative Phrase Detection)
    # ------------------------------------------------------------------
    def run_exam_audit(
        self,
        exam_id: str,
        current_user: dict[str, Any],
        payload: dict[str, Any] | None = None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        validated = validate_run_audit_payload(payload)
        threshold = validated["confidence_threshold"]

        exam = self.exam_repo.get_by_id(exam_id)
        if not exam:
            raise NotFoundError("Examination not found.")
        self._assert_examiner_owns(exam.get("created_by", ""), current_user, "examination")

        all_subs = self.submission_repo.list_by_exam(exam_id)
        finalized_subs = [s for s in all_subs if s.get("status") in {"submitted", "auto_submitted"}]
        if not finalized_subs:
            raise ValidationError("No submitted student attempts exist yet for this examination.")

        questions = self.question_repo.get_many_by_ids(exam.get("question_ids", []))
        desc_questions = [q for q in questions if q.get("type") == "descriptive"]
        if not desc_questions:
            raise ValidationError("This examination contains no descriptive questions for rubric auditing.")

        rubrics_by_qid: dict[str, dict[str, Any]] = {}
        rubrics_by_id: dict[str, dict[str, Any]] = {}
        for q in desc_questions:
            rub = self._resolve_question_rubric(q)
            if rub:
                rubrics_by_qid[q["question_id"]] = rub
                if rub.get("rubric_id"):
                    rubrics_by_id[rub["rubric_id"]] = rub

        signature = self._compute_audit_signature(exam_id, finalized_subs, rubrics_by_id, threshold)
        prior_reports = self.audit_report_repo.list_by_exam(exam_id)
        if any(r.get("audit_signature") == signature for r in prior_reports):
            raise ConflictError(
                "An audit report has already been generated for the current submissions, rubric versions, and confidence threshold.",
                error_code="DUPLICATE_AUDIT_PREVENTED",
            )

        existing_suggestions = self.audit_suggestion_repo.list_suggestions(exam_id=exam_id)
        existing_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {
            (
                s["question_id"],
                s["criterion_id"],
                s["expected_phrase"].lower(),
                s["suggested_phrase"].lower(),
            ): s
            for s in existing_suggestions
        }

        grouped_matches: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        flagged_sub_ids: set[str] = set()
        now_iso = utc_now().isoformat()

        for sub in finalized_subs:
            sub_id = sub["submission_id"]
            answers = sub.get("answers", {})
            rubric_evals = sub.get("grading", {}).get("rubric_evaluations", {})
            sub_flags: list[dict[str, Any]] = []

            for q in desc_questions:
                qid = q["question_id"]
                rubric = rubrics_by_qid.get(qid)
                if not rubric:
                    continue
                text_ans = (answers.get(qid, {}) or {}).get("text_answer") or ""
                if not text_ans.strip():
                    continue

                q_eval = rubric_evals.get(qid, {})
                crit_eval_map = {c.get("criterion_id"): c for c in q_eval.get("criteria_scores", [])}
                rubric_criteria = rubric.get("criteria", [])

                for crit in rubric_criteria:
                    sibling_phrases = [
                        p
                        for other in rubric_criteria
                        if other.get("criterion_id") != crit.get("criterion_id")
                        for p in (list(other.get("key_concepts", [])) + list(other.get("alternative_phrases", [])))
                    ]
                    try:
                        detections = self.nlp_engine.detect_alternative_phrases(
                            answer_text=text_ans,
                            criterion=crit,
                            question_prompt=q.get("prompt", ""),
                            model_answer=rubric.get("model_answer", ""),
                            excluded_phrases=sibling_phrases,
                            threshold=threshold,
                        )
                    except Exception as exc:  # pragma: no cover - defensive NLP safeguard
                        logger.warning("NLP analyzer skipped criterion %s on %s: %s", crit.get("criterion_id"), sub_id, exc)
                        continue

                    crit_eval = crit_eval_map.get(crit["criterion_id"], {})
                    for match in detections:
                        key = (
                            qid,
                            crit["criterion_id"],
                            match.expected_phrase.lower(),
                            match.suggested_phrase.lower(),
                        )
                        excerpt_entry = {
                            "submission_id": sub_id,
                            "student_name": sub.get("student_name", ""),
                            "institution_id": sub.get("institution_id", ""),
                            "excerpt": match.excerpt,
                            "awarded_marks": crit_eval.get("awarded_marks"),
                            "criterion_max_marks": crit.get("max_marks", 0),
                            "similarity_score": match.confidence_score,
                        }
                        sub_flags.append(
                            {
                                "question_id": qid,
                                "criterion_id": crit["criterion_id"],
                                "criterion_title": crit.get("title", ""),
                                "expected_phrase": match.expected_phrase,
                                "suggested_phrase": match.suggested_phrase,
                                "confidence_score": match.confidence_score,
                                "explanation": match.explanation,
                            }
                        )
                        flagged_sub_ids.add(sub_id)

                        bucket = grouped_matches.setdefault(
                            key,
                            {
                                "question": q,
                                "rubric": rubric,
                                "criterion": crit,
                                "expected_phrase": match.expected_phrase,
                                "suggested_phrase": match.suggested_phrase,
                                "confidence_scores": [],
                                "explanation": match.explanation,
                                "affected_submission_ids": set(),
                                "sample_excerpts": [],
                            },
                        )
                        bucket["confidence_scores"].append(match.confidence_score)
                        if sub_id not in bucket["affected_submission_ids"]:
                            bucket["affected_submission_ids"].add(sub_id)
                            bucket["sample_excerpts"].append(excerpt_entry)

            # Update per-submission audit metadata (without modifying any marks!)
            pending_or_flagged = bool(sub_flags)
            existing_audit = dict(sub.get("rubric_audit", {}))
            max_conf = max((f["confidence_score"] for f in sub_flags), default=1.0)
            self.submission_repo.update(
                sub_id,
                {
                    "rubric_audit": {
                        **existing_audit,
                        "audit_status": "flagged" if pending_or_flagged else "audited",
                        "nlp_model_version": self.nlp_engine.engine_version,
                        "audited_at": now_iso,
                        "confidence_threshold": threshold,
                        "consistency_score": round((1.0 - max_conf * 0.25) * 100, 1) if pending_or_flagged else 100.0,
                        "detected_gaps_count": len(sub_flags),
                        "audit_notes": sub_flags,
                    }
                },
            )

        audit_id = self.audit_report_repo.new_id("aud")
        created_count = 0
        updated_pending_count = 0
        new_or_updated_suggestions: list[dict[str, Any]] = []

        for key, bucket in grouped_matches.items():
            avg_conf = round(sum(bucket["confidence_scores"]) / len(bucket["confidence_scores"]), 4)
            affected_ids = sorted(bucket["affected_submission_ids"])
            existing = existing_by_key.get(key)

            if existing:
                if existing.get("status") == "pending":
                    merged_ids = sorted(set(existing.get("affected_submission_ids", [])) | set(affected_ids))
                    merged_excerpts_by_sub = {e["submission_id"]: e for e in existing.get("sample_excerpts", [])}
                    for ex in bucket["sample_excerpts"]:
                        merged_excerpts_by_sub[ex["submission_id"]] = ex
                    updated_sug = self.audit_suggestion_repo.update(
                        existing["suggestion_id"],
                        {
                            "audit_id": audit_id,
                            "confidence_score": max(float(existing.get("confidence_score", 0)), avg_conf),
                            "affected_submission_ids": merged_ids,
                            "affected_count": len(merged_ids),
                            "sample_excerpts": list(merged_excerpts_by_sub.values())[:20],
                        },
                    )
                    if updated_sug:
                        updated_pending_count += 1
                        new_or_updated_suggestions.append(updated_sug)
                # Skip creating duplicates if an identical suggestion was already approved or rejected
                continue

            q = bucket["question"]
            rubric = bucket["rubric"]
            crit = bucket["criterion"]
            sug = self.audit_suggestion_repo.create(
                {
                    "audit_id": audit_id,
                    "exam_id": exam_id,
                    "exam_title": exam["title"],
                    "course_code": exam["course_code"],
                    "examiner_uid": exam.get("created_by", ""),
                    "question_id": q["question_id"],
                    "question_prompt": q.get("prompt", ""),
                    "question_marks": q.get("marks", 0),
                    "rubric_id": rubric.get("rubric_id") or q.get("rubric_id"),
                    "rubric_title": rubric.get("title", "Analytical Rubric"),
                    "rubric_version": int(rubric.get("version", 1)),
                    "criterion_id": crit["criterion_id"],
                    "criterion_title": crit.get("title", ""),
                    "criterion_max_marks": crit.get("max_marks", 0),
                    "expected_keywords": crit.get("key_concepts", []),
                    "existing_alternatives": crit.get("alternative_phrases", []),
                    "expected_phrase": bucket["expected_phrase"],
                    "suggested_phrase": bucket["suggested_phrase"],
                    "confidence_score": avg_conf,
                    "explanation": bucket["explanation"],
                    "affected_submission_ids": affected_ids,
                    "affected_count": len(affected_ids),
                    "sample_excerpts": bucket["sample_excerpts"][:20],
                    "status": "pending",
                    "decision": None,
                    "reevaluation_summary": None,
                },
                doc_id=self.audit_suggestion_repo.new_id("sug"),
            )
            created_count += 1
            new_or_updated_suggestions.append(sug)

        report = self.audit_report_repo.create(
            {
                "audit_id": audit_id,
                "exam_id": exam_id,
                "exam_title": exam["title"],
                "course_code": exam["course_code"],
                "examiner_uid": exam.get("created_by", ""),
                "triggered_by": current_user["uid"],
                "triggered_by_name": current_user.get("full_name", current_user["email"]),
                "nlp_engine_version": self.nlp_engine.engine_version,
                "confidence_threshold": threshold,
                "audit_signature": signature,
                "total_submissions_analyzed": len(finalized_subs),
                "flagged_submissions_count": len(flagged_sub_ids),
                "total_gaps_detected": created_count + updated_pending_count,
                "new_suggestions_created": created_count,
                "status": "completed",
            },
            doc_id=audit_id,
        )

        self._record_history(
            exam_id=exam_id,
            examiner_uid=exam.get("created_by", ""),
            event_type="AUDIT_RUN",
            actor=current_user,
            details={
                "audit_id": audit_id,
                "submissions_analyzed": len(finalized_subs),
                "new_suggestions_created": created_count,
                "updated_pending_suggestions": updated_pending_count,
                "confidence_threshold": threshold,
            },
        )
        self.audit_service.record(
            actor=current_user,
            action="RUBRIC_AUDIT_EXECUTED",
            target_type="exam",
            target_id=exam_id,
            metadata={"audit_id": audit_id, "new_suggestions": created_count},
            ip_address=ip_address,
        )

        return {
            "report": report,
            "suggestions": new_or_updated_suggestions,
        }

    # ------------------------------------------------------------------
    # 2. Audit Dashboard Query & Filters
    # ------------------------------------------------------------------
    def get_audit_dashboard(
        self,
        current_user: dict[str, Any],
        *,
        exam_id: str | None = None,
        status: str | None = None,
        criterion_id: str | None = None,
    ) -> dict[str, Any]:
        is_admin = current_user.get("role") == "admin"
        examiner_uid = None if is_admin else current_user["uid"]

        if exam_id:
            exam = self.exam_repo.get_by_id(exam_id)
            if not exam:
                raise NotFoundError("Examination not found.")
            self._assert_examiner_owns(exam.get("created_by", ""), current_user, "examination")

        all_suggestions = self.audit_suggestion_repo.list_suggestions(
            examiner_uid=examiner_uid,
            exam_id=exam_id,
        )
        filtered = [
            s
            for s in all_suggestions
            if (not status or s.get("status") == status)
            and (not criterion_id or s.get("criterion_id") == criterion_id)
        ]

        exams = self.exam_repo.list_exams(created_by=examiner_uid)
        descriptive_exams = [e for e in exams if int(e.get("descriptive_count", 0)) > 0]

        criteria_map: dict[str, str] = {}
        for s in all_suggestions:
            criteria_map[s["criterion_id"]] = s.get("criterion_title", s["criterion_id"])

        reports = (
            self.audit_report_repo.list_by_exam(exam_id)
            if exam_id
            else self.audit_report_repo.list_by_examiner(examiner_uid)
        )
        history = self.audit_history_repo.list_history(exam_id=exam_id, examiner_uid=examiner_uid, limit=100)

        return {
            "summary": {
                "total_suggestions": len(all_suggestions),
                "pending_count": sum(1 for s in all_suggestions if s.get("status") == "pending"),
                "approved_count": sum(1 for s in all_suggestions if s.get("status") == "approved"),
                "rejected_count": sum(1 for s in all_suggestions if s.get("status") == "rejected"),
                "affected_submissions": len(
                    {sid for s in all_suggestions for sid in s.get("affected_submission_ids", [])}
                ),
            },
            "suggestions": filtered,
            "exams": [
                {
                    "exam_id": e["exam_id"],
                    "title": e["title"],
                    "course_code": e["course_code"],
                    "descriptive_count": e.get("descriptive_count", 0),
                }
                for e in descriptive_exams
            ],
            "criteria_options": [{"criterion_id": cid, "title": title} for cid, title in criteria_map.items()],
            "reports": reports[:20],
            "history": history,
        }

    # ------------------------------------------------------------------
    # 3. Examiner Approval + Rubric Versioning + Re-evaluation
    # ------------------------------------------------------------------
    def approve_suggestion(
        self,
        suggestion_id: str,
        current_user: dict[str, Any],
        payload: dict[str, Any] | None = None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        validated = validate_approve_suggestion_payload(payload)
        suggestion = self.audit_suggestion_repo.get_by_id(suggestion_id)
        if not suggestion:
            raise NotFoundError("Audit suggestion not found.")
        self._assert_examiner_owns(suggestion.get("examiner_uid", ""), current_user, "audit suggestion")

        if suggestion.get("status") != "pending":
            raise ConflictError(
                f"This suggestion has already been {suggestion.get('status')}.",
                error_code="SUGGESTION_ALREADY_DECIDED",
            )

        rubric_id = suggestion.get("rubric_id")
        if not rubric_id:
            raise ValidationError("No linked rubric found for this suggestion.")
        rubric = self.rubric_repo.get_by_id(rubric_id)
        if not rubric:
            raise NotFoundError("Linked evaluation rubric not found.")

        approved_phrase = validated["phrase_override"] or suggestion["suggested_phrase"]
        prev_version = int(rubric.get("version", 1))
        now = utc_now()
        now_iso = now.isoformat()

        # Preserve immutable snapshot of previous rubric version
        version_record = self.rubric_version_repo.create(
            {
                "rubric_id": rubric_id,
                "version_number": prev_version,
                "rubric_data": deepcopy(rubric),
                "changed_by": current_user["uid"],
                "changed_by_name": current_user.get("full_name", current_user["email"]),
                "changed_reason": f"Archived before approving alternative phrase '{approved_phrase}'.",
                "suggestion_id": suggestion_id,
            },
            doc_id=self.rubric_version_repo.new_id("rver"),
        )

        updated_criteria = deepcopy(rubric.get("criteria", []))
        target_criterion: dict[str, Any] | None = None
        for crit in updated_criteria:
            if crit.get("criterion_id") == suggestion["criterion_id"]:
                alts = list(crit.get("alternative_phrases", []))
                if approved_phrase.lower() not in {a.lower() for a in alts}:
                    alts.append(approved_phrase)
                crit["alternative_phrases"] = alts
                target_criterion = crit
                break

        if not target_criterion:
            raise NotFoundError("Target rubric criterion no longer exists on the rubric.")

        next_version = prev_version + 1
        updated_rubric = self.rubric_repo.update(
            rubric_id,
            {
                "criteria": updated_criteria,
                "version": next_version,
            },
        ) or {**rubric, "criteria": updated_criteria, "version": next_version}

        # Propagate updated snapshot to linked questions
        snapshot = _build_rubric_snapshot(updated_rubric)
        for q in self.question_repo.find_where("rubric_id", "==", rubric_id):
            if abs(float(q.get("marks", 0)) - float(updated_rubric["max_marks"])) <= 0.01:
                self.question_repo.update(q["question_id"], {"rubric_snapshot": snapshot})

        self._record_history(
            exam_id=suggestion["exam_id"],
            examiner_uid=suggestion.get("examiner_uid", ""),
            rubric_id=rubric_id,
            suggestion_id=suggestion_id,
            event_type="RUBRIC_VERSION_SAVED",
            actor=current_user,
            details={
                "previous_version": prev_version,
                "new_version": next_version,
                "version_record_id": version_record["version_id"],
                "approved_phrase": approved_phrase,
                "criterion_id": suggestion["criterion_id"],
            },
        )

        # Re-evaluate affected submissions while preserving previous evaluation records
        reeval_summary = self._reevaluate_affected_submissions(
            exam_id=suggestion["exam_id"],
            question_id=suggestion["question_id"],
            updated_rubric=updated_rubric,
            target_criterion=target_criterion,
            approved_phrase=approved_phrase,
            suggestion_id=suggestion_id,
            prev_rubric_version=prev_version,
            actor=current_user,
            ip_address=ip_address,
        )

        decision = {
            "action": "approved",
            "approved_phrase": approved_phrase,
            "approval_note": validated["approval_note"],
            "decided_by": current_user["uid"],
            "decided_by_name": current_user.get("full_name", current_user["email"]),
            "decided_at": now_iso,
            "previous_rubric_version": prev_version,
            "new_rubric_version": next_version,
        }
        updated_suggestion = self.audit_suggestion_repo.update(
            suggestion_id,
            {
                "status": "approved",
                "decision": decision,
                "reevaluation_summary": reeval_summary,
            },
        )

        self._record_history(
            exam_id=suggestion["exam_id"],
            examiner_uid=suggestion.get("examiner_uid", ""),
            rubric_id=rubric_id,
            suggestion_id=suggestion_id,
            event_type="SUGGESTION_APPROVED",
            actor=current_user,
            details={
                "expected_phrase": suggestion["expected_phrase"],
                "approved_phrase": approved_phrase,
                "similarity_score": suggestion["confidence_score"],
                "previous_rubric_version": prev_version,
                "new_rubric_version": next_version,
                "approval_note": validated["approval_note"],
                "reevaluation_summary": reeval_summary,
            },
        )
        self.audit_service.record(
            actor=current_user,
            action="AUDIT_SUGGESTION_APPROVED",
            target_type="audit_suggestion",
            target_id=suggestion_id,
            metadata={
                "rubric_id": rubric_id,
                "approved_phrase": approved_phrase,
                "updated_submissions": reeval_summary["updated_count"],
            },
            ip_address=ip_address,
        )

        return {
            "suggestion": updated_suggestion,
            "rubric": updated_rubric,
            "previous_rubric_version_id": version_record["version_id"],
            "reevaluation_summary": reeval_summary,
        }

    def _reevaluate_affected_submissions(
        self,
        *,
        exam_id: str,
        question_id: str,
        updated_rubric: dict[str, Any],
        target_criterion: dict[str, Any],
        approved_phrase: str,
        suggestion_id: str,
        prev_rubric_version: int,
        actor: dict[str, Any],
        ip_address: str = "",
    ) -> dict[str, Any]:
        exam = self.exam_repo.get_by_id(exam_id)
        if not exam:
            raise NotFoundError("Examination not found.")

        submissions = self.submission_repo.list_by_exam(exam_id)
        criterion_id = target_criterion["criterion_id"]
        now_iso = utc_now().isoformat()

        affected_count = 0
        updated_count = 0
        unchanged_count = 0
        score_changes: list[dict[str, Any]] = []

        for sub in submissions:
            if sub.get("status") not in {"submitted", "auto_submitted"}:
                continue
            text_ans = (sub.get("answers", {}).get(question_id, {}) or {}).get("text_answer") or ""
            if not text_ans.strip():
                continue

            # Check whether this submission contains the newly approved phrase
            if not exact_phrase_present(" ".join(text_ans.lower().split()), approved_phrase):
                continue

            affected_count += 1
            grading = deepcopy(sub.get("grading", {}))
            rubric_evals = dict(grading.get("rubric_evaluations", {}))
            q_eval = deepcopy(rubric_evals.get(question_id, {}))
            if not q_eval:
                continue

            prev_eval_status = grading.get("evaluation_status")
            prev_desc_score = float(grading.get("descriptive_score") or 0.0)
            prev_total_score = grading.get("total_score")
            prev_q_awarded = float(q_eval.get("awarded_marks") or 0.0)

            # Preserve immutable historical evaluation snapshot before updating
            eval_history = list(grading.get("evaluation_history", []))
            eval_history.append(
                {
                    "snapshot_at": now_iso,
                    "trigger": "rubric_audit_suggestion_approved",
                    "suggestion_id": suggestion_id,
                    "rubric_version_before": prev_rubric_version,
                    "evaluation_status_before": prev_eval_status,
                    "descriptive_score_before": grading.get("descriptive_score"),
                    "total_score_before": prev_total_score,
                    "question_evaluation_before": deepcopy(q_eval),
                }
            )

            recomputed_crit = evaluate_criterion_transparently(text_ans, target_criterion)
            new_criteria_scores: list[dict[str, Any]] = []
            crit_changed = False
            prev_crit_marks = 0.0
            new_crit_marks = 0.0

            for cs in q_eval.get("criteria_scores", []):
                if cs.get("criterion_id") == criterion_id:
                    prev_crit_marks = float(cs.get("awarded_marks") or 0.0)
                    # Only increase marks when updated rubric legitimizes a higher score
                    candidate_marks = float(recomputed_crit["suggested_marks"])
                    final_crit_marks = max(prev_crit_marks, candidate_marks)
                    new_crit_marks = round(final_crit_marks, 2)
                    if new_crit_marks > prev_crit_marks + 0.001:
                        crit_changed = True
                    new_criteria_scores.append(
                        {
                            **recomputed_crit,
                            "awarded_marks": new_crit_marks,
                            "previous_awarded_marks": prev_crit_marks,
                            "evaluation_method": "rubric_audit_reevaluated",
                            "feedback": (
                                f"Re-evaluated under rubric v{updated_rubric['version']} "
                                f"after approving alternative phrase '{approved_phrase}'."
                            ),
                        }
                    )
                else:
                    new_criteria_scores.append(cs)

            if not crit_changed:
                unchanged_count += 1
                # Preserve audit trail even when score did not change
                grading["evaluation_history"] = eval_history
                self.submission_repo.update(
                    sub["submission_id"],
                    {
                        "grading": grading,
                        "rubric_audit": {
                            **sub.get("rubric_audit", {}),
                            "audit_status": "audited",
                            "last_reevaluated_at": now_iso,
                        },
                    },
                )
                continue

            updated_count += 1
            new_q_awarded = round(sum(float(c.get("awarded_marks") or 0.0) for c in new_criteria_scores), 2)
            q_eval["criteria_scores"] = new_criteria_scores
            q_eval["awarded_marks"] = new_q_awarded
            q_eval["rubric_version"] = updated_rubric["version"]
            q_eval["last_reevaluated_at"] = now_iso
            rubric_evals[question_id] = q_eval

            new_desc_score = round(
                sum(float(ev.get("awarded_marks") or 0.0) for ev in rubric_evals.values()),
                2,
            )
            mcq_score = float(grading.get("mcq_score", 0.0) or 0.0)
            new_total_score = round(mcq_score + new_desc_score, 2)

            grading["rubric_evaluations"] = rubric_evals
            grading["descriptive_score"] = new_desc_score
            grading["total_score"] = new_total_score
            grading["evaluation_history"] = eval_history

            decision_history = list(grading.get("decision_history", []))
            decision_history.append(
                {
                    "evaluated_by": actor["uid"],
                    "evaluated_by_name": actor.get("full_name", actor["email"]),
                    "evaluated_at": now_iso,
                    "mcq_score": mcq_score,
                    "descriptive_score": new_desc_score,
                    "total_score": new_total_score,
                    "examiner_feedback": f"Audit re-evaluation under rubric v{updated_rubric['version']}",
                    "trigger": "rubric_audit_approval",
                }
            )
            grading["decision_history"] = decision_history

            updated_sub = self.submission_repo.update(
                sub["submission_id"],
                {
                    "grading": grading,
                    "rubric_audit": {
                        **sub.get("rubric_audit", {}),
                        "audit_status": "audited",
                        "last_reevaluated_at": now_iso,
                    },
                },
            ) or {**sub, "grading": grading}

            existing_result = self.result_repo.get_by_exam_and_student(exam_id, sub["student_uid"])
            result_updated = False
            if existing_result and grading.get("evaluation_status") in {"evaluated", "completed"}:
                old_res_marks = float(existing_result.get("obtained_marks", 0))
                if abs(new_total_score - old_res_marks) > 0.001:
                    # Preserve previous result revision history before updating
                    rev_history = list(existing_result.get("revision_history", []))
                    rev_history.append(
                        {
                            "revised_at": now_iso,
                            "trigger": "rubric_audit_reevaluation",
                            "suggestion_id": suggestion_id,
                            "previous_obtained_marks": old_res_marks,
                            "previous_percentage": existing_result.get("percentage"),
                            "previous_grade": existing_result.get("grade"),
                        }
                    )
                    updated_result = self.result_service.upsert_result_for_submission(
                        exam=exam,
                        submission=updated_sub,
                        actor=actor,
                        publish=(existing_result.get("publication_status") == "published"),
                        ip_address=ip_address,
                    )
                    self.result_repo.update(updated_result["result_id"], {"revision_history": rev_history})
                    result_updated = True

                    if updated_result.get("publication_status") == "published":
                        self.notification_repo.create(
                            {
                                "recipient_uid": sub["student_uid"],
                                "exam_id": exam_id,
                                "result_id": updated_result["result_id"],
                                "title": f"Result Updated · {exam['course_code']}",
                                "message": (
                                    f"Following a rubric audit update for '{exam['title']}', your score "
                                    f"increased from {old_res_marks:g} to {new_total_score:g} / "
                                    f"{updated_result['total_marks']:g} (Grade {updated_result['grade']})."
                                ),
                                "previous_marks": old_res_marks,
                                "updated_marks": new_total_score,
                                "is_read": False,
                            },
                            doc_id=self.notification_repo.new_id("notif"),
                        )

            change_record = {
                "submission_id": sub["submission_id"],
                "student_name": sub.get("student_name", ""),
                "previous_criterion_marks": prev_crit_marks,
                "updated_criterion_marks": new_crit_marks,
                "previous_question_marks": prev_q_awarded,
                "updated_question_marks": new_q_awarded,
                "previous_descriptive_score": prev_desc_score,
                "updated_descriptive_score": new_desc_score,
                "previous_total_score": prev_total_score,
                "updated_total_score": new_total_score,
                "result_updated": result_updated,
            }
            score_changes.append(change_record)

            self._record_history(
                exam_id=exam_id,
                examiner_uid=exam.get("created_by", ""),
                rubric_id=updated_rubric.get("rubric_id"),
                suggestion_id=suggestion_id,
                event_type="SUBMISSION_REEVALUATED",
                actor=actor,
                details=change_record,
            )

        return {
            "affected_count": affected_count,
            "updated_count": updated_count,
            "unchanged_count": unchanged_count,
            "score_changes": score_changes,
        }

    # ------------------------------------------------------------------
    # 4. Examiner Rejection (Original Rubric & Scores Unchanged)
    # ------------------------------------------------------------------
    def reject_suggestion(
        self,
        suggestion_id: str,
        current_user: dict[str, Any],
        payload: dict[str, Any] | None = None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        validated = validate_reject_suggestion_payload(payload)
        suggestion = self.audit_suggestion_repo.get_by_id(suggestion_id)
        if not suggestion:
            raise NotFoundError("Audit suggestion not found.")
        self._assert_examiner_owns(suggestion.get("examiner_uid", ""), current_user, "audit suggestion")

        if suggestion.get("status") != "pending":
            raise ConflictError(
                f"This suggestion has already been {suggestion.get('status')}.",
                error_code="SUGGESTION_ALREADY_DECIDED",
            )

        now_iso = utc_now().isoformat()
        decision = {
            "action": "rejected",
            "reason": validated["reason"],
            "decided_by": current_user["uid"],
            "decided_by_name": current_user.get("full_name", current_user["email"]),
            "decided_at": now_iso,
        }
        updated = self.audit_suggestion_repo.update(
            suggestion_id,
            {
                "status": "rejected",
                "decision": decision,
            },
        )

        # Clear submission pending flag if no other pending suggestions affect it
        remaining_pending = self.audit_suggestion_repo.list_suggestions(
            exam_id=suggestion["exam_id"],
            status="pending",
        )
        still_flagged_subs = {sid for s in remaining_pending for sid in s.get("affected_submission_ids", [])}
        for sid in suggestion.get("affected_submission_ids", []):
            if sid not in still_flagged_subs:
                sub = self.submission_repo.get_by_id(sid)
                if sub:
                    self.submission_repo.update(
                        sid,
                        {
                            "rubric_audit": {
                                **sub.get("rubric_audit", {}),
                                "audit_status": "audited",
                            }
                        },
                    )

        self._record_history(
            exam_id=suggestion["exam_id"],
            examiner_uid=suggestion.get("examiner_uid", ""),
            rubric_id=suggestion.get("rubric_id"),
            suggestion_id=suggestion_id,
            event_type="SUGGESTION_REJECTED",
            actor=current_user,
            details={
                "expected_phrase": suggestion["expected_phrase"],
                "suggested_phrase": suggestion["suggested_phrase"],
                "similarity_score": suggestion["confidence_score"],
                "reason": validated["reason"],
            },
        )
        self.audit_service.record(
            actor=current_user,
            action="AUDIT_SUGGESTION_REJECTED",
            target_type="audit_suggestion",
            target_id=suggestion_id,
            metadata={"reason": validated["reason"]},
            ip_address=ip_address,
        )

        return {"suggestion": updated}

    def get_rubric_versions(self, rubric_id: str, current_user: dict[str, Any]) -> list[dict[str, Any]]:
        rubric = self.rubric_repo.get_by_id(rubric_id)
        if not rubric:
            raise NotFoundError("Evaluation rubric not found.")
        self._assert_examiner_owns(rubric.get("created_by", ""), current_user, "rubric")
        return self.rubric_version_repo.list_by_rubric(rubric_id)
