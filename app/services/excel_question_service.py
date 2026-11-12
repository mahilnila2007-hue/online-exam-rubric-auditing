"""Excel (.xlsx/.csv) bulk import and template generation for multi-tier question sets."""

from __future__ import annotations

import csv
from datetime import timedelta
import io
import math
import re
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.exceptions import ValidationError
from app.services.audit_service import AuditService
from app.services.exam_service import ExamService
from app.services.question_service import QuestionService
from app.services.time_utils import utc_now
from app.validators.question_validators import validate_question_payload

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_QUESTION_ROWS = 500

SKIP_SHEET_TOKENS = ("instruction", "readme", "guide", "help", "note")
OPTION_LETTERS = ("A", "B", "C", "D", "E", "F")

# Maps normalized Excel column headers -> canonical field names
HEADER_ALIASES: dict[str, str] = {
    "set": "question_set",
    "set_name": "question_set",
    "question_set": "question_set",
    "exam_set": "question_set",
    "group": "question_set",
    "qno": "question_no",
    "q_no": "question_no",
    "q_id": "question_no",
    "qid": "question_no",
    "question_no": "question_no",
    "question_number": "question_no",
    "sl_no": "question_no",
    "sno": "question_no",
    "subject": "subject",
    "course": "subject",
    "topic": "topic",
    "unit": "topic",
    "difficulty": "difficulty",
    "level": "difficulty",
    "type": "type",
    "question_type": "type",
    "q_type": "type",
    "prompt": "prompt",
    "question": "prompt",
    "question_prompt": "prompt",
    "question_text": "prompt",
    "marks": "marks",
    "mark": "marks",
    "max_marks": "marks",
    "score": "marks",
    # Combined All-in-One sheet multi-tier columns
    "1_mark_mcq_question": "mcq_prompt",
    "1_mark_question": "mcq_prompt",
    "1m_mcq_question": "mcq_prompt",
    "1m_question": "mcq_prompt",
    "mcq_question": "mcq_prompt",
    "1_mark_mcq_prompt": "mcq_prompt",
    "2_mark_question": "q2_prompt",
    "2_marks_question": "q2_prompt",
    "2m_question": "q2_prompt",
    "two_mark_question": "q2_prompt",
    "2m_criterion": "q2_criterion",
    "2_mark_criterion": "q2_criterion",
    "2m_expected_keywords": "q2_keywords",
    "2_mark_keywords": "q2_keywords",
    "expected_keywords_2m": "q2_keywords",
    "2m_keywords": "q2_keywords",
    "2m_alternative_phrases": "q2_alternatives",
    "2_mark_alternative_phrases": "q2_alternatives",
    "alternative_phrases_2m": "q2_alternatives",
    "2m_model_answer": "q2_model_answer",
    "2_mark_model_answer": "q2_model_answer",
    "model_answer_2m": "q2_model_answer",
    "5_mark_question": "q5_prompt",
    "5_marks_question": "q5_prompt",
    "5m_question": "q5_prompt",
    "five_mark_question": "q5_prompt",
    "5m_criterion": "q5_criterion",
    "5_mark_criterion": "q5_criterion",
    "5m_expected_keywords": "q5_keywords",
    "5_mark_keywords": "q5_keywords",
    "expected_keywords_5m": "q5_keywords",
    "5m_keywords": "q5_keywords",
    "5m_alternative_phrases": "q5_alternatives",
    "5_mark_alternative_phrases": "q5_alternatives",
    "alternative_phrases_5m": "q5_alternatives",
    "5m_model_answer": "q5_model_answer",
    "5_mark_model_answer": "q5_model_answer",
    "model_answer_5m": "q5_model_answer",
    # Options columns
    "option_a": "option_a",
    "opt_a": "option_a",
    "option_1": "option_a",
    "a": "option_a",
    "option_b": "option_b",
    "opt_b": "option_b",
    "option_2": "option_b",
    "b": "option_b",
    "option_c": "option_c",
    "opt_c": "option_c",
    "option_3": "option_c",
    "c": "option_c",
    "option_d": "option_d",
    "opt_d": "option_d",
    "option_4": "option_d",
    "d": "option_d",
    "option_e": "option_e",
    "opt_e": "option_e",
    "option_5": "option_e",
    "e": "option_e",
    "option_f": "option_f",
    "opt_f": "option_f",
    "option_6": "option_f",
    "f": "option_f",
    "option_label": "option_label",
    "option_letter": "option_label",
    "label": "option_label",
    "option_text": "option_text",
    "choice_text": "option_text",
    "is_correct": "is_correct",
    "correct": "is_correct",
    "correct_option": "correct_option",
    "correct_option_a_b_c_d": "correct_option",
    "correct_answer": "correct_option",
    "correct_answer_a_d": "correct_option",
    "answer": "correct_option",
    "answer_key": "correct_option",
    "explanation": "explanation",
    "rationale": "explanation",
    "solution": "explanation",
    "rubric_criterion": "criterion_1_title",
    "criterion_title": "criterion_1_title",
    "criteria": "criterion_1_title",
    "criterion": "criterion_1_title",
    "criterion_1_title": "criterion_1_title",
    "criterion_1_marks": "criterion_1_marks",
    "criterion_1_keywords": "criterion_1_keywords",
    "expected_keywords": "criterion_1_keywords",
    "keywords": "criterion_1_keywords",
    "key_concepts": "criterion_1_keywords",
    "criterion_1_alternative_phrases": "criterion_1_alternatives",
    "criterion_1_alternatives": "criterion_1_alternatives",
    "alternative_phrases": "criterion_1_alternatives",
    "alternatives": "criterion_1_alternatives",
    "alt_phrases": "criterion_1_alternatives",
    "criterion_2_title": "criterion_2_title",
    "criterion_2_marks": "criterion_2_marks",
    "criterion_2_keywords": "criterion_2_keywords",
    "criterion_2_alternative_phrases": "criterion_2_alternatives",
    "criterion_2_alternatives": "criterion_2_alternatives",
    "criterion_3_title": "criterion_3_title",
    "criterion_3_marks": "criterion_3_marks",
    "criterion_3_keywords": "criterion_3_keywords",
    "criterion_3_alternative_phrases": "criterion_3_alternatives",
    "criterion_3_alternatives": "criterion_3_alternatives",
    "model_answer": "model_answer",
    "sample_answer": "model_answer",
    "reference_answer": "model_answer",
    "rubric_title": "rubric_title",
    "tags": "tags",
}

KNOWN_CANONICAL_HEADERS = set(HEADER_ALIASES.values())

SHEET_TIER_RULES: list[tuple[tuple[str, ...], str, float | None]] = [
    (("all_in_one", "combined", "master", "question_set"), "combined", None),
    (("option", "choice"), "options", None),
    (("1_mark", "1mark", "1m", "one_mark", "part_a", "parta", "mcq", "objective"), "mcq", 1.0),
    (("2_mark", "2mark", "2m", "two_mark", "short", "part_b", "partb"), "descriptive", 2.0),
    (("5_mark", "5mark", "5m", "five_mark", "long", "essay", "part_c", "partc"), "descriptive", 5.0),
]

THIN_BORDER = Border(
    left=Side(style="thin", color="CBD5E1"),
    right=Side(style="thin", color="CBD5E1"),
    top=Side(style="thin", color="CBD5E1"),
    bottom=Side(style="thin", color="CBD5E1"),
)


def _normalize_header(raw: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(raw or "").strip().lower()).strip("_")
    return HEADER_ALIASES.get(text, text)


def _cell_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val).strip()


def _parse_float(raw: Any) -> float | None:
    text = _cell_str(raw)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _split_csv_phrases(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[,;\n]+", raw)
    return [p.strip() for p in parts if p.strip()]


def _is_truthy(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "y", "correct", "x"}


def _infer_sheet_role(sheet_name: str, headers: set[str]) -> tuple[str, float | None]:
    norm_name = re.sub(r"[^a-z0-9]+", "_", sheet_name.strip().lower()).strip("_")
    if any(tok in norm_name for tok in SKIP_SHEET_TOKENS):
        return "skip", None

    tier_prompt_cols = {"mcq_prompt", "q2_prompt", "q5_prompt"}
    if len(headers & tier_prompt_cols) >= 2:
        return "combined", None

    # Sheet without question prompt but with option rows/columns acts as external options table
    has_prompt = "prompt" in headers
    has_option_rows = ("option_text" in headers or "option_a" in headers) and "question_no" in headers
    if not has_prompt and has_option_rows:
        return "options", None

    for tokens, mode, default_marks in SHEET_TIER_RULES:
        if any(tok in norm_name for tok in tokens):
            if mode == "options" and has_prompt:
                continue
            if mode == "combined" and len(headers & tier_prompt_cols) == 0:
                continue
            return mode, default_marks

    return "mixed", None


def _read_tabular_sheets(file_bytes: bytes, filename: str) -> list[tuple[str, list[dict[str, str]]]]:
    if not file_bytes:
        raise ValidationError("Uploaded file is empty.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ValidationError("Uploaded file exceeds the 5 MB size limit.")

    lower_name = (filename or "").strip().lower()
    if lower_name.endswith(".csv"):
        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValidationError("CSV files must be UTF-8 encoded.") from exc
        reader = list(csv.reader(io.StringIO(text)))
        return [("CSV", _rows_to_dicts(reader))]

    if lower_name.endswith(".xls") and not lower_name.endswith((".xlsx", ".xlsm")):
        raise ValidationError(
            "Legacy binary .xls files are not supported. Please save as .xlsx (Excel Workbook) or .csv."
        )

    if not lower_name.endswith((".xlsx", ".xlsm")):
        raise ValidationError("Unsupported file type. Upload an Excel (.xlsx) or .csv file.")

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as exc:
        raise ValidationError(f"Could not read Excel workbook: {exc}") from exc

    try:
        sheets: list[tuple[str, list[dict[str, str]]]] = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            raw_rows = list(ws.iter_rows(values_only=True))
            if not raw_rows:
                continue
            sheets.append((sheet_name, _rows_to_dicts(raw_rows)))
        return sheets
    finally:
        wb.close()


def _rows_to_dicts(raw_rows: list[Any]) -> list[dict[str, str]]:
    """Detect the true header row (skipping banner/group rows) and parse data rows cleanly."""
    header_idx: int | None = None
    first_nonempty_idx: int | None = None
    headers: list[str] = []

    for idx, row in enumerate(raw_rows[:15]):
        cells = [_cell_str(c) for c in row]
        if not any(cells):
            continue
        if first_nonempty_idx is None:
            first_nonempty_idx = idx
        normalized = [_normalize_header(c) for c in cells]
        known_hits = sum(1 for h in normalized if h and h in KNOWN_CANONICAL_HEADERS)
        if known_hits >= 2:
            header_idx = idx
            headers = normalized
            break

    if header_idx is None:
        if first_nonempty_idx is None:
            return []
        header_idx = first_nonempty_idx
        headers = [_normalize_header(c) for c in [_cell_str(x) for x in raw_rows[first_nonempty_idx]]]

    records: list[dict[str, str]] = []
    for offset, row in enumerate(raw_rows[header_idx + 1 :], start=header_idx + 2):
        row_dict: dict[str, str] = {"_row_num": str(offset)}
        has_data = False
        for col_idx, header in enumerate(headers):
            if not header:
                continue  # Skips blank spacer columns cleanly
            val = _cell_str(row[col_idx]) if col_idx < len(row) else ""
            if val:
                has_data = True
            row_dict[header] = val
        if has_data:
            records.append(row_dict)
    return records


def _collect_external_options(
    sheets: list[tuple[str, list[dict[str, str]]]],
    default_set: str,
    override_set: bool,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Index options from any separate Options sheet by (set_name, question_no)."""
    indexed: dict[tuple[str, str], dict[str, Any]] = {}

    for sheet_name, rows in sheets:
        if not rows:
            continue
        headers = set(rows[0].keys())
        mode, _ = _infer_sheet_role(sheet_name, headers)
        if mode != "options":
            continue

        for row in rows:
            q_no = row.get("question_no", "").strip().lower()
            if not q_no:
                continue
            raw_set = row.get("question_set", "").strip()
            q_set = default_set if (override_set or not raw_set) else raw_set
            key = (q_set.lower(), q_no)
            bucket = indexed.setdefault(key, {"options": [], "correct": ""})

            wide_opts = [row.get(f"option_{letter.lower()}", "").strip() for letter in OPTION_LETTERS]
            if any(wide_opts):
                for idx, text in enumerate(wide_opts):
                    if text:
                        bucket["options"].append({"id": f"opt_{idx + 1}", "text": text})
                if row.get("correct_option"):
                    bucket["correct"] = row["correct_option"].strip()
                continue

            opt_text = row.get("option_text", "").strip()
            if opt_text:
                opt_id = f"opt_{len(bucket['options']) + 1}"
                bucket["options"].append({"id": opt_id, "text": opt_text})
                if _is_truthy(row.get("is_correct", "")) or _is_truthy(row.get("correct_option", "")):
                    bucket["correct"] = opt_id

    return indexed


def _resolve_correct_option_id(raw_correct: str, options: list[dict[str, str]]) -> str:
    if not raw_correct or not options:
        return ""
    lower = raw_correct.strip().lower()

    for idx, opt in enumerate(options):
        letter = OPTION_LETTERS[idx].lower() if idx < len(OPTION_LETTERS) else ""
        if lower in {
            opt["id"].lower(),
            str(idx + 1),
            letter,
            f"opt_{letter}",
            f"option_{letter}",
            f"option {letter}",
        }:
            return opt["id"]

    for opt in options:
        if opt["text"].strip().lower() == lower:
            return opt["id"]

    return ""


def _build_inline_rubric(
    row: dict[str, str],
    *,
    subject: str,
    marks: float,
    prompt: str,
) -> dict[str, Any]:
    """Construct validated criterion breakdown summing exactly to question marks."""
    raw_criteria: list[dict[str, Any]] = []
    for idx in (1, 2, 3):
        title = row.get(f"criterion_{idx}_title", "").strip()
        keywords = _split_csv_phrases(row.get(f"criterion_{idx}_keywords", ""))
        alts = _split_csv_phrases(row.get(f"criterion_{idx}_alternatives", ""))
        c_marks = _parse_float(row.get(f"criterion_{idx}_marks", ""))

        if title or keywords or alts or c_marks is not None:
            raw_criteria.append(
                {
                    "title": title or f"Criterion {idx}",
                    "description": f"Rubric criterion {idx} for: {prompt[:80]}",
                    "max_marks": c_marks,
                    "key_concepts": keywords,
                    "alternative_phrases": alts,
                }
            )

    if not raw_criteria:
        default_title = "Core Concept & Accuracy" if marks <= 2.5 else "Concept Explanation & Analysis"
        raw_criteria.append(
            {
                "title": default_title,
                "description": f"Analytical rubric criteria ({marks:g} marks)",
                "max_marks": marks,
                "key_concepts": [],
                "alternative_phrases": [],
            }
        )
    else:
        specified = [c for c in raw_criteria if c["max_marks"] is not None]
        unspecified = [c for c in raw_criteria if c["max_marks"] is None]
        if unspecified:
            used = round(sum(float(c["max_marks"]) for c in specified), 2)
            remaining = round(max(0.0, marks - used), 2)
            count = len(unspecified)
            if count == 1:
                unspecified[0]["max_marks"] = remaining if remaining > 0 else marks
            else:
                each = round((remaining / count) * 2) / 2
                running = 0.0
                for item in unspecified[:-1]:
                    item["max_marks"] = max(0.5, each)
                    running = round(running + item["max_marks"], 2)
                unspecified[-1]["max_marks"] = round(max(0.5, remaining - running), 2)

    rubric_title = row.get("rubric_title", "").strip() or f"{marks:g}M Rubric — {prompt[:48]}"
    return {
        "title": rubric_title[:160],
        "subject": subject,
        "model_answer": row.get("model_answer", "").strip(),
        "criteria": raw_criteria,
    }


def _tier_bucket(marks: float) -> str:
    if abs(marks - 1.0) <= 0.01:
        return "1_mark"
    if abs(marks - 2.0) <= 0.01:
        return "2_mark"
    if abs(marks - 5.0) <= 0.01:
        return "5_mark"
    return "other"


def _apply_row_height_and_borders(
    ws: Any,
    row_idx: int,
    col_widths: dict[int, float],
    spacer_cols: set[int],
    *,
    min_height: float = 24.0,
    is_data_row: bool = True,
) -> None:
    """Apply wrapping, borders (except spacer gaps), and dynamic row height so text never clips."""
    max_lines = 1
    for col_idx in range(1, ws.max_column + 1):
        cell = ws.cell(row=row_idx, column=col_idx)
        if col_idx in spacer_cols:
            cell.fill = PatternFill(fill_type=None)
            continue
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        if is_data_row:
            cell.border = THIN_BORDER
        text = str(cell.value or "")
        if text:
            width = max(12.0, col_widths.get(col_idx, 20.0) - 2.0)
            explicit_lines = text.splitlines() or [text]
            wrapped = sum(max(1, math.ceil(len(line) / width)) for line in explicit_lines)
            if wrapped > max_lines:
                max_lines = wrapped

    ws.row_dimensions[row_idx].height = max(min_height, min(140.0, max_lines * 16.0 + 10.0))


class ExcelQuestionService:
    """Handles downloadable multi-tier Excel templates and batch question-set imports."""

    def __init__(
        self,
        question_service: QuestionService,
        audit_service: AuditService,
        exam_service: ExamService | None = None,
    ) -> None:
        self.question_service = question_service
        self.audit_service = audit_service
        self.exam_service = exam_service

    def build_excel_template(self) -> bytes:
        """Build a cleanly spaced, wrapped Excel workbook covering All-in-One and per-tier sheets."""
        wb = openpyxl.Workbook()

        navy_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        title_font = Font(bold=True, size=13, color="0F172A")
        header_font = Font(color="FFFFFF", bold=True, size=10.5)
        group_font = Font(color="0F172A", bold=True, size=10)

        group_fills = {
            "meta": PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid"),
            "mcq": PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid"),
            "two": PatternFill(start_color="CCFBF1", end_color="CCFBF1", fill_type="solid"),
            "five": PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid"),
            "notes": PatternFill(start_color="EDE9FE", end_color="EDE9FE", fill_type="solid"),
        }

        # 1. Instructions Sheet (generous column widths + wrapped rows, zero text clipping)
        ws_info = wb.active
        ws_info.title = "Instructions"
        ws_info["A1"] = "RubriAssess — Multi-Tier Excel Question Set Template & Guide"
        ws_info["A1"].font = title_font
        ws_info.merge_cells("A1:D1")
        ws_info.row_dimensions[1].height = 30
        ws_info.row_dimensions[2].height = 10

        guide_rows = [
            ("Sheet Name", "How This Sheet Is Structured", "Marks & Question Type", "Grouping Into the Same Set"),
            (
                "All_In_One_Set",
                "One complete sheet with Set Details, a dedicated 1-Mark MCQ Question cell + Options A–D side-by-side, blank spacer columns, 2-Mark Questions, and 5-Mark Questions.",
                "All Tiers (1M MCQ, 2M, 5M) on one sheet",
                "Every populated tier cell on a row shares that row's Set Name (e.g. Combined Set A).",
            ),
            (
                "1_Mark_MCQ",
                "Dedicated 1-Mark MCQ sheet with Question Prompt in its own column, Options A–D right beside it, blank spacer columns, and Correct Option / Explanation.",
                "1 Mark (MCQ)",
                "Use the same Set Name (e.g. Midterm Set A) across 1_Mark_MCQ, 2_Mark_Questions & 5_Mark_Questions.",
            ),
            (
                "2_Mark_Questions",
                "2-Mark short descriptive questions with blank spacer gap before Rubric Criterion Title, Expected Keywords, Alternative Phrases, and Model Answer.",
                "2 Marks (Descriptive + Auto Rubric)",
                "Auto-creates 2-mark evaluation rubrics ready for Phase 2 scoring & Phase 3 NLP auditing.",
            ),
            (
                "5_Mark_Questions",
                "5-Mark long descriptive questions with clearly separated blocks for Criterion 1, Criterion 2, and Model Answer.",
                "5 Marks (Multi-Criterion Rubric)",
                "Supports split marks (e.g. 2.5 + 2.5 = 5) cleanly across weighted rubric criteria.",
            ),
            (
                "Optional: Options Sheet",
                "If you add a separate 'Options' sheet keyed by Set Name + Question No, the importer automatically matches those options onto 1-mark questions.",
                "Optional Separate Options Sheet",
                "Works with either wide (Option A–D) rows or long (one option per row) formats.",
            ),
        ]
        info_widths = {1: 24.0, 2: 56.0, 3: 26.0, 4: 50.0}
        for col_idx, w in info_widths.items():
            ws_info.column_dimensions[get_column_letter(col_idx)].width = w

        for r_idx, row in enumerate(guide_rows, start=3):
            for c_idx, val in enumerate(row, start=1):
                cell = ws_info.cell(row=r_idx, column=c_idx, value=val)
                cell.border = THIN_BORDER
                if r_idx == 3:
                    cell.fill = navy_fill
                    cell.font = header_font
                    cell.alignment = Alignment(wrap_text=True, vertical="center")
                else:
                    cell.alignment = Alignment(wrap_text=True, vertical="center")
            _apply_row_height_and_borders(
                ws_info, r_idx, info_widths, set(), min_height=28.0 if r_idx == 3 else 46.0
            )
        ws_info.freeze_panes = "A4"

        # 2. All-In-One Combined Sheet (MCQ + side Options | spacer | 2-Mark | spacer | 5-Mark)
        ws_all = wb.create_sheet("All_In_One_Set")
        all_groups = [
            (1, 4, "SET DETAILS", group_fills["meta"]),
            (6, 11, "1-MARK MCQ QUESTION & SIDE-BY-SIDE OPTIONS", group_fills["mcq"]),
            (13, 16, "2-MARK SHORT QUESTIONS & RUBRIC", group_fills["two"]),
            (18, 21, "5-MARK LONG QUESTIONS & RUBRIC", group_fills["five"]),
        ]
        all_headers = [
            "Set Name",
            "Subject",
            "Topic",
            "Difficulty",
            "",  # Col E spacer
            "1-Mark MCQ Question",
            "Option A",
            "Option B",
            "Option C",
            "Option D",
            "Correct Option",
            "",  # Col L spacer
            "2-Mark Question",
            "2M Expected Keywords",
            "2M Alternative Phrases",
            "2M Model Answer",
            "",  # Col Q spacer
            "5-Mark Question",
            "5M Expected Keywords",
            "5M Alternative Phrases",
            "5M Model Answer",
        ]
        all_widths = {
            1: 20, 2: 20, 3: 20, 4: 13,
            5: 4,
            6: 42, 7: 22, 8: 22, 9: 22, 10: 22, 11: 16,
            12: 4,
            13: 42, 14: 26, 15: 26, 16: 38,
            17: 4,
            18: 44, 19: 28, 20: 28, 21: 42,
        }
        all_rows = [
            [
                "Combined Set A", "Computer Networks", "Transport Layer", "easy", "",
                "Which transport-layer protocol provides connection-oriented reliable byte-stream delivery?",
                "UDP", "TCP", "ICMP", "ARP", "B", "",
                "State two key functions of the TCP three-way handshake.",
                "connection establishment, sequence number synchronization",
                "SYN ACK exchange, initial sequence agreement",
                "The TCP three-way handshake (SYN, SYN-ACK, ACK) establishes a reliable connection and synchronizes initial sequence numbers.", "",
                "Compare TCP congestion control slow start and congestion avoidance phases with congestion window behavior.",
                "slow start exponential growth, ssthresh, congestion avoidance linear growth, packet loss",
                "cwnd doubles each RTT, additive increase multiplicative decrease",
                "Slow start grows cwnd exponentially per RTT until ssthresh is reached; congestion avoidance then increases cwnd linearly per RTT and reduces it on congestion.",
            ],
            [
                "Combined Set A", "Computer Networks", "Network Layer", "medium", "",
                "Which protocol translates private IPv4 addresses to public IPv4 addresses at a gateway router?",
                "DNS", "DHCP", "NAT", "BGP", "C", "",
                "Why is subnetting used in IPv4 network administration?",
                "reduce broadcast traffic, efficient IP allocation",
                "smaller broadcast domains, avoid address wastage",
                "Subnetting partitions a network block into smaller subnetworks to reduce broadcast domains and allocate IP addresses efficiently.", "",
                "", "", "", "",
            ],
        ]
        self._populate_grouped_sheet(
            ws_all,
            title="All-in-One Question Set (Separate MCQ Question + Options Side-by-Side, Spaced 2-Mark & 5-Mark Sections)",
            groups=all_groups,
            headers=all_headers,
            sample_rows=all_rows,
            col_widths=all_widths,
            spacer_cols={5, 12, 17},
            navy_fill=navy_fill,
            header_font=header_font,
            title_font=title_font,
            group_font=group_font,
        )

        # 3. 1-Mark MCQ Sheet (Question cell + Options A-D beside it + spaced Key/Notes)
        ws_1m = wb.create_sheet("1_Mark_MCQ")
        self._populate_grouped_sheet(
            ws_1m,
            title="1-Mark MCQ Question Sheet (Question Cell with Options A–D Side-by-Side)",
            groups=[
                (1, 4, "SET DETAILS", group_fills["meta"]),
                (6, 11, "1-MARK QUESTION & OPTIONS (SIDE BY SIDE)", group_fills["mcq"]),
                (13, 15, "ANSWER KEY & RATIONALE", group_fills["notes"]),
            ],
            headers=[
                "Set Name", "Subject", "Topic", "Difficulty", "",
                "Question Prompt", "Marks", "Option A", "Option B", "Option C", "Option D", "",
                "Correct Option", "Explanation", "Tags",
            ],
            sample_rows=[
                [
                    "Midterm Set A", "Operating Systems", "Process Scheduling", "easy", "",
                    "Which CPU scheduling algorithm can suffer from indefinite starvation of low-priority processes?",
                    1, "Round Robin", "Priority Scheduling", "First-Come First-Served", "Multilevel Feedback Queue", "",
                    "B", "Priority scheduling without aging can starve low-priority tasks indefinitely.", "unit-1,mcq,1m",
                ],
                [
                    "Midterm Set A", "Operating Systems", "Deadlocks", "medium", "",
                    "Which Coffman condition is violated when a process must release held resources before requesting new ones?",
                    1, "Mutual Exclusion", "Hold and Wait", "Circular Wait", "No Preemption", "",
                    "B", "Requiring release of held resources breaks the Hold and Wait condition.", "unit-1,mcq,1m",
                ],
            ],
            col_widths={
                1: 20, 2: 20, 3: 20, 4: 13, 5: 4,
                6: 44, 7: 10, 8: 22, 9: 22, 10: 22, 11: 22, 12: 4,
                13: 16, 14: 38, 15: 18,
            },
            spacer_cols={5, 12},
            navy_fill=navy_fill,
            header_font=header_font,
            title_font=title_font,
            group_font=group_font,
        )

        # 4. 2-Mark Questions Sheet
        ws_2m = wb.create_sheet("2_Mark_Questions")
        self._populate_grouped_sheet(
            ws_2m,
            title="2-Mark Short Descriptive Questions Sheet",
            groups=[
                (1, 4, "SET DETAILS", group_fills["meta"]),
                (6, 7, "2-MARK QUESTION", group_fills["two"]),
                (9, 13, "2-MARK RUBRIC & MODEL ANSWER", group_fills["notes"]),
            ],
            headers=[
                "Set Name", "Subject", "Topic", "Difficulty", "",
                "Question Prompt", "Marks", "",
                "Criterion Title", "Expected Keywords", "Alternative Phrases", "Model Answer", "Tags",
            ],
            sample_rows=[
                [
                    "Midterm Set A", "Operating Systems", "Deadlocks", "easy", "",
                    "Define aging in CPU scheduling and state why it is used.", 2, "",
                    "Definition & Purpose",
                    "gradually increasing priority, prevent starvation",
                    "boost waiting process priority, avoid indefinite blocking",
                    "Aging gradually increases the priority of waiting processes over time to prevent starvation.",
                    "unit-1,short,2m",
                ],
                [
                    "Midterm Set A", "Operating Systems", "Memory Management", "medium", "",
                    "Differentiate between internal fragmentation and external fragmentation in memory allocation.", 2, "",
                    "Core Distinction",
                    "fixed partition unused space, contiguous free holes",
                    "wasted allocated block space, scattered free memory",
                    "Internal fragmentation wastes unused space inside fixed blocks; external fragmentation leaves scattered non-contiguous free holes.",
                    "unit-2,short,2m",
                ],
            ],
            col_widths={
                1: 20, 2: 20, 3: 20, 4: 13, 5: 4,
                6: 44, 7: 10, 8: 4,
                9: 24, 10: 28, 11: 28, 12: 42, 13: 18,
            },
            spacer_cols={5, 8},
            navy_fill=navy_fill,
            header_font=header_font,
            title_font=title_font,
            group_font=group_font,
        )

        # 5. 5-Mark Questions Sheet (clean naming, generous spacing between criteria blocks)
        ws_5m = wb.create_sheet("5_Mark_Questions")
        self._populate_grouped_sheet(
            ws_5m,
            title="5-Mark Long Descriptive Questions Sheet (Multi-Criterion Analytical Rubric)",
            groups=[
                (1, 4, "SET DETAILS", group_fills["meta"]),
                (6, 7, "5-MARK QUESTION", group_fills["five"]),
                (9, 12, "CRITERION 1 RUBRIC", group_fills["mcq"]),
                (14, 17, "CRITERION 2 RUBRIC", group_fills["two"]),
                (19, 20, "MODEL ANSWER & TAGS", group_fills["notes"]),
            ],
            headers=[
                "Set Name", "Subject", "Topic", "Difficulty", "",
                "Question Prompt", "Marks", "",
                "Criterion 1 Title", "Criterion 1 Marks", "Criterion 1 Keywords", "Criterion 1 Alternative Phrases", "",
                "Criterion 2 Title", "Criterion 2 Marks", "Criterion 2 Keywords", "Criterion 2 Alternative Phrases", "",
                "Model Answer", "Tags",
            ],
            sample_rows=[
                [
                    "Midterm Set A", "Operating Systems", "Deadlocks", "hard", "",
                    "Explain Coffman's four necessary conditions for deadlock and illustrate one strategy to prevent each.",
                    5, "",
                    "Four Coffman Conditions", 2.5,
                    "mutual exclusion, hold and wait, no preemption, circular wait",
                    "exclusive access, wait while holding resources, ordered locking", "",
                    "Deadlock Prevention Strategies", 2.5,
                    "spooling, total resource ordering, preemption",
                    "hierarchical numbering, release held locks", "",
                    "Deadlock occurs only when mutual exclusion, hold and wait, no preemption, and circular wait hold simultaneously. Each can be negated via resource spooling, all-or-nothing acquisition, forced preemption, or strict lock ordering.",
                    "unit-1,long,5m",
                ],
            ],
            col_widths={
                1: 20, 2: 20, 3: 20, 4: 13, 5: 4,
                6: 44, 7: 10, 8: 4,
                9: 24, 10: 16, 11: 30, 12: 30, 13: 4,
                14: 26, 15: 16, 16: 30, 17: 30, 18: 4,
                19: 46, 20: 18,
            },
            spacer_cols={5, 8, 13, 18},
            navy_fill=navy_fill,
            header_font=header_font,
            title_font=title_font,
            group_font=group_font,
        )

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    @staticmethod
    def _populate_grouped_sheet(
        ws: Any,
        *,
        title: str,
        groups: list[tuple[int, int, str, PatternFill]],
        headers: list[str],
        sample_rows: list[list[Any]],
        col_widths: dict[int, float],
        spacer_cols: set[int],
        navy_fill: PatternFill,
        header_font: Font,
        title_font: Font,
        group_font: Font,
    ) -> None:
        ws.cell(row=1, column=1, value=title).font = title_font
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
        ws.row_dimensions[1].height = 28

        for start_c, end_c, label, fill in groups:
            if end_c > start_c:
                ws.merge_cells(start_row=2, start_column=start_c, end_row=2, end_column=end_c)
            for c_idx in range(start_c, end_c + 1):
                cell = ws.cell(row=2, column=c_idx)
                cell.fill = fill
                cell.font = group_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = THIN_BORDER
            ws.cell(row=2, column=start_c, value=label)
        ws.row_dimensions[2].height = 24

        for c_idx, heading in enumerate(headers, start=1):
            ws.column_dimensions[get_column_letter(c_idx)].width = col_widths.get(c_idx, 18)
            cell = ws.cell(row=3, column=c_idx, value=heading)
            if c_idx in spacer_cols:
                continue
            cell.fill = navy_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            cell.border = THIN_BORDER
        ws.row_dimensions[3].height = 30

        for r_offset, row in enumerate(sample_rows, start=4):
            for c_idx, val in enumerate(row, start=1):
                ws.cell(row=r_offset, column=c_idx, value=val)
            _apply_row_height_and_borders(
                ws, r_offset, col_widths, spacer_cols, min_height=44.0, is_data_row=True
            )

        ws.freeze_panes = "A4"

    def parse_uploaded_workbook(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        default_set_name: str = "",
        override_set_name: bool = False,
        default_subject: str = "",
        default_topic: str = "Core Concepts",
        default_difficulty: str = "medium",
    ) -> dict[str, Any]:
        """Parse and validate multi-sheet Excel or CSV rows into question payloads without persisting."""
        sheets = _read_tabular_sheets(file_bytes, filename)
        if not sheets:
            raise ValidationError("The uploaded file contains no readable sheets or rows.")

        clean_default_set = default_set_name.strip()
        clean_default_subject = default_subject.strip()
        clean_default_topic = default_topic.strip() or "Core Concepts"
        clean_default_diff = (
            default_difficulty.strip().lower()
            if default_difficulty.strip().lower() in {"easy", "medium", "hard"}
            else "medium"
        )

        external_options = _collect_external_options(sheets, clean_default_set, override_set_name)

        valid_items: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        preview_rows: list[dict[str, Any]] = []
        row_counter = 0

        for sheet_name, rows in sheets:
            if not rows:
                continue
            headers = set(rows[0].keys())
            sheet_mode, sheet_marks = _infer_sheet_role(sheet_name, headers)
            if sheet_mode in {"skip", "options"}:
                continue

            carried_set = ""
            carried_subject = ""

            for row in rows:
                excel_row = int(row.get("_row_num", "0") or 0)
                if sheet_mode == "combined":
                    if row.get("question_set", "").strip():
                        carried_set = row["question_set"].strip()
                    if row.get("subject", "").strip():
                        carried_subject = row["subject"].strip()
                    outcomes = self._parse_combined_row(
                        sheet_name=sheet_name,
                        excel_row=excel_row,
                        row=row,
                        default_set=clean_default_set or carried_set,
                        override_set=override_set_name,
                        default_subject=clean_default_subject or carried_subject,
                        default_topic=clean_default_topic,
                        default_difficulty=clean_default_diff,
                        external_options=external_options,
                    )
                else:
                    outcomes = [
                        self._parse_single_row(
                            sheet_name=sheet_name,
                            excel_row=excel_row,
                            row=row,
                            sheet_mode=sheet_mode,
                            sheet_marks=sheet_marks,
                            default_set=clean_default_set,
                            override_set=override_set_name,
                            default_subject=clean_default_subject,
                            default_topic=clean_default_topic,
                            default_difficulty=clean_default_diff,
                            external_options=external_options,
                        )
                    ]

                for parsed_payload, row_error in outcomes:
                    row_counter += 1
                    if row_counter > MAX_QUESTION_ROWS:
                        raise ValidationError(f"Uploads cannot exceed {MAX_QUESTION_ROWS} questions per batch.")

                    if row_error:
                        errors.append(row_error)
                        preview_rows.append(
                            {
                                "sheet": sheet_name,
                                "row": excel_row,
                                "valid": False,
                                "error": row_error["message"],
                                "question_set": row_error.get("question_set", ""),
                                "prompt": row_error.get("prompt", "")[:100],
                                "type": row_error.get("type", ""),
                                "marks": row_error.get("marks"),
                            }
                        )
                    elif parsed_payload:
                        valid_items.append({"sheet": sheet_name, "row": excel_row, "payload": parsed_payload})
                        preview_rows.append(
                            {
                                "sheet": sheet_name,
                                "row": excel_row,
                                "valid": True,
                                "question_set": parsed_payload.get("question_set", ""),
                                "subject": parsed_payload["subject"],
                                "type": parsed_payload["type"],
                                "marks": parsed_payload["marks"],
                                "prompt": parsed_payload["prompt"][:100],
                                "criteria_count": len(parsed_payload.get("rubric", {}).get("criteria", [])),
                                "options_count": len(parsed_payload.get("options", [])),
                            }
                        )

        if not preview_rows and not errors:
            raise ValidationError(
                "No question rows were found. Check column headers (Question Prompt, Option A-D / Marks, etc.)."
            )

        tier_summary = {"1_mark": 0, "2_mark": 0, "5_mark": 0, "other": 0}
        mcq_count = 0
        descriptive_count = 0
        sets_seen: list[str] = []

        for entry in valid_items:
            p = entry["payload"]
            tier_summary[_tier_bucket(float(p["marks"]))] += 1
            if p["type"] == "mcq":
                mcq_count += 1
            else:
                descriptive_count += 1
            q_set = p.get("question_set", "").strip()
            if q_set and q_set not in sets_seen:
                sets_seen.append(q_set)

        return {
            "valid_items": valid_items,
            "preview_result": {
                "filename": filename,
                "valid_count": len(valid_items),
                "error_count": len(errors),
                "mcq_count": mcq_count,
                "descriptive_count": descriptive_count,
                "sets": sets_seen,
                "tier_summary": tier_summary,
                "preview_rows": preview_rows,
                "errors": errors,
            },
        }

    def _validate_question_item(
        self,
        *,
        sheet_name: str,
        excel_row: int,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        try:
            validate_question_payload(payload)
        except ValidationError as exc:
            first_field = next(iter((exc.details or {}).get("fields", {}).values()), exc.message)
            return None, {
                "sheet": sheet_name,
                "row": excel_row,
                "question_set": payload.get("question_set", ""),
                "type": payload.get("type", ""),
                "marks": payload.get("marks"),
                "prompt": payload.get("prompt", ""),
                "message": f"[{sheet_name} row {excel_row}] {first_field}",
            }
        return payload, None

    def _build_mcq_outcome(
        self,
        *,
        sheet_name: str,
        excel_row: int,
        question_set: str,
        subject: str,
        topic: str,
        difficulty: str,
        prompt: str,
        marks: float,
        row: dict[str, str],
        external_options: dict[tuple[str, str], dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        inline_opt_texts = [row.get(f"option_{l.lower()}", "").strip() for l in OPTION_LETTERS]
        has_inline_options = any(inline_opt_texts)
        q_no = row.get("question_no", "").strip().lower()
        ext_entry = (
            external_options.get((question_set.lower(), q_no)) or external_options.get(("", q_no))
            if q_no
            else None
        )

        if has_inline_options:
            options = [
                {"id": f"opt_{idx + 1}", "text": txt}
                for idx, txt in enumerate(inline_opt_texts)
                if txt
            ]
            raw_correct = row.get("correct_option", "").strip()
        elif ext_entry:
            options = ext_entry["options"]
            raw_correct = row.get("correct_option", "").strip() or ext_entry.get("correct", "")
        else:
            return None, {
                "sheet": sheet_name,
                "row": excel_row,
                "question_set": question_set,
                "type": "mcq",
                "marks": marks,
                "prompt": prompt,
                "message": f"[{sheet_name} row {excel_row}] MCQ row is missing answer options (Option A/B/C/D).",
            }

        correct_id = _resolve_correct_option_id(raw_correct, options)
        if raw_correct and not correct_id:
            return None, {
                "sheet": sheet_name,
                "row": excel_row,
                "question_set": question_set,
                "type": "mcq",
                "marks": marks,
                "prompt": prompt,
                "message": (
                    f"[{sheet_name} row {excel_row}] Correct Option '{raw_correct}' "
                    "does not match any provided option (use A/B/C/D or option text)."
                ),
            }

        payload = {
            "question_set": question_set,
            "subject": subject,
            "topic": topic,
            "difficulty": difficulty,
            "type": "mcq",
            "prompt": prompt,
            "marks": marks,
            "explanation": row.get("explanation", "").strip(),
            "tags": _split_csv_phrases(row.get("tags", "")),
            "options": options,
            "correct_option_id": correct_id,
        }
        return self._validate_question_item(sheet_name=sheet_name, excel_row=excel_row, payload=payload)

    def _parse_combined_row(
        self,
        *,
        sheet_name: str,
        excel_row: int,
        row: dict[str, str],
        default_set: str,
        override_set: bool,
        default_subject: str,
        default_topic: str,
        default_difficulty: str,
        external_options: dict[tuple[str, str], dict[str, Any]],
    ) -> list[tuple[dict[str, Any] | None, dict[str, Any] | None]]:
        """Extract 1-Mark MCQ, 2-Mark, and 5-Mark questions arranged side-by-side in one row."""
        raw_set = row.get("question_set", "").strip()
        question_set = default_set if (override_set or not raw_set) else raw_set
        subject = row.get("subject", "").strip() or default_subject
        topic = row.get("topic", "").strip() or default_topic
        difficulty = row.get("difficulty", "").strip().lower() or default_difficulty
        tags = _split_csv_phrases(row.get("tags", ""))

        outcomes: list[tuple[dict[str, Any] | None, dict[str, Any] | None]] = []

        mcq_prompt = row.get("mcq_prompt", "").strip()
        has_any_opt = any(row.get(f"option_{l.lower()}", "").strip() for l in OPTION_LETTERS)
        if mcq_prompt or has_any_opt:
            outcomes.append(
                self._build_mcq_outcome(
                    sheet_name=sheet_name,
                    excel_row=excel_row,
                    question_set=question_set,
                    subject=subject,
                    topic=topic,
                    difficulty=difficulty,
                    prompt=mcq_prompt,
                    marks=1.0,
                    row=row,
                    external_options=external_options,
                )
            )

        for prefix, tier_marks in (("q2", 2.0), ("q5", 5.0)):
            q_prompt = row.get(f"{prefix}_prompt", "").strip()
            if not q_prompt:
                continue
            synthetic_rubric_row = {
                "criterion_1_title": row.get(f"{prefix}_criterion", "").strip(),
                "criterion_1_keywords": row.get(f"{prefix}_keywords", "").strip(),
                "criterion_1_alternatives": row.get(f"{prefix}_alternatives", "").strip(),
                "model_answer": row.get(f"{prefix}_model_answer", "").strip(),
            }
            payload = {
                "question_set": question_set,
                "subject": subject,
                "topic": topic,
                "difficulty": difficulty,
                "type": "descriptive",
                "prompt": q_prompt,
                "marks": tier_marks,
                "explanation": "",
                "tags": tags,
                "rubric": _build_inline_rubric(
                    synthetic_rubric_row,
                    subject=subject or "General",
                    marks=tier_marks,
                    prompt=q_prompt,
                ),
            }
            outcomes.append(
                self._validate_question_item(sheet_name=sheet_name, excel_row=excel_row, payload=payload)
            )

        return outcomes

    def _parse_single_row(
        self,
        *,
        sheet_name: str,
        excel_row: int,
        row: dict[str, str],
        sheet_mode: str,
        sheet_marks: float | None,
        default_set: str,
        override_set: bool,
        default_subject: str,
        default_topic: str,
        default_difficulty: str,
        external_options: dict[tuple[str, str], dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        raw_set = row.get("question_set", "").strip()
        question_set = default_set if (override_set or not raw_set) else raw_set
        subject = row.get("subject", "").strip() or default_subject
        topic = row.get("topic", "").strip() or default_topic
        difficulty = row.get("difficulty", "").strip().lower() or default_difficulty
        prompt = row.get("prompt", "").strip()

        raw_type = row.get("type", "").strip().lower()
        has_inline_options = any(row.get(f"option_{l.lower()}", "").strip() for l in OPTION_LETTERS)
        q_no = row.get("question_no", "").strip().lower()
        has_ext_opts = bool(
            q_no and (external_options.get((question_set.lower(), q_no)) or external_options.get(("", q_no)))
        )

        if raw_type in {"mcq", "descriptive"}:
            q_type = raw_type
        elif sheet_mode in {"mcq", "descriptive"}:
            q_type = sheet_mode
        elif has_inline_options or has_ext_opts:
            q_type = "mcq"
        else:
            q_type = "descriptive"

        parsed_marks = _parse_float(row.get("marks", ""))
        if parsed_marks is not None:
            marks = parsed_marks
        elif sheet_marks is not None:
            marks = sheet_marks
        else:
            marks = 1.0 if q_type == "mcq" else 2.0

        if q_type == "mcq":
            return self._build_mcq_outcome(
                sheet_name=sheet_name,
                excel_row=excel_row,
                question_set=question_set,
                subject=subject,
                topic=topic,
                difficulty=difficulty,
                prompt=prompt,
                marks=marks,
                row=row,
                external_options=external_options,
            )

        payload: dict[str, Any] = {
            "question_set": question_set,
            "subject": subject,
            "topic": topic,
            "difficulty": difficulty,
            "type": "descriptive",
            "prompt": prompt,
            "marks": marks,
            "explanation": row.get("explanation", "").strip(),
            "tags": _split_csv_phrases(row.get("tags", "")),
            "rubric": _build_inline_rubric(row, subject=subject or "General", marks=marks, prompt=prompt),
        }
        return self._validate_question_item(sheet_name=sheet_name, excel_row=excel_row, payload=payload)

    def preview_upload(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        default_set_name: str = "",
        override_set_name: bool = False,
        default_subject: str = "",
        default_topic: str = "Core Concepts",
        default_difficulty: str = "medium",
    ) -> dict[str, Any]:
        parsed = self.parse_uploaded_workbook(
            file_bytes=file_bytes,
            filename=filename,
            default_set_name=default_set_name,
            override_set_name=override_set_name,
            default_subject=default_subject,
            default_topic=default_topic,
            default_difficulty=default_difficulty,
        )
        return parsed["preview_result"]

    def commit_upload(
        self,
        user: dict[str, Any],
        *,
        file_bytes: bytes,
        filename: str,
        default_set_name: str = "",
        override_set_name: bool = False,
        default_subject: str = "",
        default_topic: str = "Core Concepts",
        default_difficulty: str = "medium",
        skip_invalid: bool = False,
        create_exam: bool = False,
        exam_title: str = "",
        course_code: str = "",
        ip_address: str = "",
    ) -> dict[str, Any]:
        """Validate and persist an uploaded Excel/CSV question set, optionally creating a draft exam."""
        parsed = self.parse_uploaded_workbook(
            file_bytes=file_bytes,
            filename=filename,
            default_set_name=default_set_name,
            override_set_name=override_set_name,
            default_subject=default_subject,
            default_topic=default_topic,
            default_difficulty=default_difficulty,
        )
        summary = parsed["preview_result"]
        valid_items = parsed["valid_items"]

        if summary["error_count"] > 0 and not skip_invalid:
            raise ValidationError(
                f"Excel validation found {summary['error_count']} error(s). Fix them or enable 'Skip invalid rows'.",
                details={"errors": summary["errors"], "preview": summary},
            )
        if not valid_items:
            raise ValidationError("No valid questions found to import.", details={"errors": summary["errors"]})

        ordered_items = sorted(valid_items, key=lambda item: float(item["payload"]["marks"]))

        created_questions: list[dict[str, Any]] = []
        for entry in ordered_items:
            q_doc = self.question_service.create_question(user, entry["payload"], ip_address=ip_address)
            created_questions.append(q_doc)

        created_exam: dict[str, Any] | None = None
        if create_exam and self.exam_service is not None:
            now = utc_now()
            start_iso = now.replace(microsecond=0).isoformat()
            end_iso_str = (now.replace(microsecond=0) + timedelta(days=7)).isoformat()
            set_label = summary["sets"][0] if summary["sets"] else "Uploaded Set"
            resolved_title = exam_title.strip() or f"{set_label} Examination"
            resolved_course = course_code.strip().upper() or "SET101"
            total_marks = sum(float(q.get("marks", 0)) for q in created_questions)
            created_exam = self.exam_service.create_exam(
                user,
                {
                    "title": resolved_title,
                    "course_code": resolved_course,
                    "description": f"Generated from Excel upload ({filename}) · Sets: {', '.join(summary['sets']) or 'General'}",
                    "status": "draft",
                    "scheduled_start": start_iso,
                    "scheduled_end": end_iso_str,
                    "duration_minutes": max(15, min(180, len(created_questions) * 5)),
                    "passing_marks": round(total_marks * 0.4, 2),
                    "question_ids": [q["question_id"] for q in created_questions],
                },
                ip_address=ip_address,
            )

        self.audit_service.record(
            actor=user,
            action="QUESTION_SET_EXCEL_IMPORTED",
            target_type="question_set",
            target_id=(summary["sets"][0] if summary["sets"] else "mixed"),
            metadata={
                "filename": filename,
                "imported_count": len(created_questions),
                "skipped_count": summary["error_count"],
                "tier_summary": summary["tier_summary"],
                "sets": summary["sets"],
                "created_exam_id": created_exam["exam_id"] if created_exam else None,
            },
            ip_address=ip_address,
        )

        return {
            "imported_count": len(created_questions),
            "skipped_count": summary["error_count"],
            "mcq_count": summary["mcq_count"],
            "descriptive_count": summary["descriptive_count"],
            "sets": summary["sets"],
            "tier_summary": summary["tier_summary"],
            "created_questions": created_questions,
            "created_exam": created_exam,
            "errors": summary["errors"],
        }
