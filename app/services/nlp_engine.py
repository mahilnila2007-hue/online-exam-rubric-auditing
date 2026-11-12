"""
Hybrid NLP Semantic & Alternative Phrase Detection Engine for Rubric Auditing.

Design rationale:
- Uses scikit-learn word/subword TF-IDF cosine similarity paired with morphological
  stem canonicalization, curated academic conceptual anchor projection, negation
  asymmetry filtering, and context-grounding gating.
- Specifically calibrated so:
  1) Exact rubric phrases are recognized as already covered (not flagged as gaps).
  2) Paraphrases expressing the expected concept with different words score high.
  3) Superficially overlapping unrelated phrases (e.g., sharing a single generic word
     such as 'timeout' in an unrelated domain like 'database connection timeout') are
     rejected by context-grounding checks.
- Runs deterministically and offline in milliseconds without external model downloads.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by", "can",
    "could", "did", "do", "does", "during", "for", "from", "had", "has", "have",
    "he", "her", "here", "his", "how", "i", "if", "in", "into", "is", "it", "its",
    "may", "might", "more", "most", "must", "of", "on", "or", "our", "out",
    "over", "she", "should", "so", "some", "such", "than", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "those", "to",
    "under", "up", "use", "used", "using", "was", "we", "were", "what", "when",
    "where", "which", "while", "who", "will", "with", "would", "you", "your",
}

NEGATION_CUES = {
    "not", "never", "no", "cannot", "can't", "dont", "don't", "doesnt",
    "doesn't", "without", "lack", "lacks", "lacking", "neither", "nor", "false",
}

CONCEPT_ANCHOR_GROUPS: list[tuple[str, set[str]]] = [
    ("ANCHOR_TIMEOUT_WAIT", {"timeout", "timer", "countdown", "interval", "backoff", "delay", "wait", "waiting", "duration", "period", "clock"}),
    ("ANCHOR_RANDOM", {"random", "randomized", "randomised", "stochastic", "probabilistic", "jitter", "arbitrary", "unpredictable"}),
    ("ANCHOR_CONSENSUS", {"consensus", "agreement", "agree", "quorum", "majority", "vote", "voting", "ballot", "half"}),
    ("ANCHOR_CONFLICT_TIE", {"split", "tie", "ties", "collision", "contention", "stalemate", "deadlock", "conflict"}),
    ("ANCHOR_LEADER", {"leader", "coordinator", "primary", "master", "elected", "election", "nominate", "candidate"}),
    ("ANCHOR_FAULT", {"fault", "failure", "crash", "outage", "resilient", "resilience", "tolerant", "tolerance", "recover", "recovery"}),
    ("ANCHOR_MUTEX", {"mutual", "exclusion", "exclusive", "single", "one", "only", "lock", "locking", "mutex", "semaphore", "critical", "serialized"}),
    ("ANCHOR_CONCURRENT", {"concurrent", "concurrency", "simultaneous", "simultaneously", "parallel", "multithreaded", "thread", "threads", "process", "processes"}),
    ("ANCHOR_REDUNDANCY", {"redundancy", "redundant", "duplicate", "duplication", "repeated", "repetition", "normalize", "normalization"}),
    ("ANCHOR_IMMUTABLE", {"immutable", "immutability", "unchangeable", "readonly", "frozen", "constant", "unaltered", "modify", "modified"}),
    ("ANCHOR_COMPLEXITY", {"complexity", "runtime", "asymptotic", "logarithmic", "linear", "quadratic", "exponential", "efficiency", "scaling", "growth"}),
    ("ANCHOR_MEMORY", {"memory", "allocation", "reclaim", "reclamation", "garbage", "collection", "deallocate", "free", "heap", "leak"}),
    ("ANCHOR_SECURITY", {"encrypt", "encryption", "cipher", "decrypt", "cryptographic", "confidentiality", "authenticate", "authentication", "verify", "integrity"}),
    ("ANCHOR_STABLE_ORDER", {"stable", "stability", "preserve", "preserves", "preserved", "order", "ordering", "relative", "position"}),
    ("ANCHOR_DATA_PARTITION", {"partition", "sharding", "shard", "split", "fragment", "slice", "distribute", "distributed"}),
    ("ANCHOR_SPEED_PERF", {"latency", "throughput", "bandwidth", "speed", "faster", "overhead", "bottleneck", "performance"}),
    ("ANCHOR_CACHE", {"cache", "caching", "buffer", "memoize", "memoization", "lookup"}),
    ("ANCHOR_INHERIT_POLY", {"polymorphism", "override", "overriding", "dynamic", "dispatch", "inherit", "inheritance", "subclass", "interface"}),
]

TOKEN_TO_ANCHORS: dict[str, list[str]] = {}
for anchor_tag, vocab in CONCEPT_ANCHOR_GROUPS:
    for word in vocab:
        TOKEN_TO_ANCHORS.setdefault(word, []).append(anchor_tag)


def _stem_token(token: str) -> str:
    """Lightweight deterministic multi-pass suffix normalization."""
    w = token.lower().strip()
    if len(w) <= 3:
        return w
    for _ in range(2):
        changed = False
        for suffix in (
            "izations", "ization", "ational", "fulness", "ousness", "iveness",
            "ically", "ements", "ement", "ments", "ment", "ations", "ation",
            "ating", "ities", "ity", "iness", "ings", "ing", "ated", "ates",
            "edly", "ally", "ers", "ies", "ied", "ly", "al", "ic", "es", "ed", "s",
        ):
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                base = w[: -len(suffix)]
                w = base + "y" if suffix in {"ies", "ied"} else base
                changed = True
                break
        if not changed:
            break
    return w


def tokenize_words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9][a-zA-Z0-9\-\+]*", (text or "").lower())


def content_tokens(text: str) -> list[str]:
    return [t for t in tokenize_words(text) if t not in STOPWORDS and len(t) > 1]


def canonical_concept_units(text: str) -> list[str]:
    """Map content tokens to conceptual anchors when available, else normalized stems."""
    units: list[str] = []
    for tok in content_tokens(text):
        stem = _stem_token(tok)
        anchors = TOKEN_TO_ANCHORS.get(tok) or TOKEN_TO_ANCHORS.get(stem)
        if anchors:
            units.extend(anchors)
        else:
            units.append(stem)
    return units


def expand_conceptual_representation(text: str) -> str:
    """Build combined stem + conceptual anchor text for TF-IDF vectorization."""
    expanded: list[str] = []
    for tok in content_tokens(text):
        stem = _stem_token(tok)
        expanded.append(stem)
        anchors = set(TOKEN_TO_ANCHORS.get(tok, [])) | set(TOKEN_TO_ANCHORS.get(stem, []))
        expanded.extend(sorted(anchors))
    return " ".join(expanded)


def extract_candidate_clauses_and_phrases(answer_text: str) -> list[dict[str, str]]:
    """
    Segment descriptive answer into sentences/clauses and extract candidate n-gram
    phrases (2 to 5 tokens) paired with their containing clause excerpt.
    """
    if not (answer_text or "").strip():
        return []

    raw_clauses = [
        c.strip()
        for c in re.split(
            r"[.!?\n;]+|(?:\s*,\s*(?:while|whereas|because|since|so|and|which|that)\s+)",
            answer_text,
        )
        if c.strip()
    ]
    if not raw_clauses:
        raw_clauses = [answer_text.strip()]

    candidates: list[dict[str, str]] = []
    seen_phrases: set[str] = set()

    for clause in raw_clauses:
        words = tokenize_words(clause)
        if len(words) < 2:
            continue
        if len(words) <= 6:
            key = " ".join(words)
            if key not in seen_phrases:
                seen_phrases.add(key)
                candidates.append({"phrase": clause, "excerpt": clause})

        for win in (2, 3, 4, 5):
            if len(words) < win:
                continue
            for idx in range(0, len(words) - win + 1):
                span = words[idx : idx + win]
                if span[0] in STOPWORDS or span[-1] in STOPWORDS:
                    continue
                content = [w for w in span if w not in STOPWORDS]
                if len(content) < 2:
                    continue
                phrase_str = " ".join(span)
                if phrase_str in seen_phrases:
                    continue
                preceding = words[max(0, idx - 4) : idx]
                if any(p in NEGATION_CUES for p in preceding):
                    continue
                seen_phrases.add(phrase_str)
                candidates.append({"phrase": phrase_str, "excerpt": clause})

    return candidates


def exact_phrase_present(text_lower: str, phrase: str) -> bool:
    needle = (phrase or "").strip().lower()
    if not needle:
        return False
    if re.match(r"^[a-z0-9][a-z0-9\s\-_]*[a-z0-9]$", needle) or re.match(r"^[a-z0-9]+$", needle):
        return bool(re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", text_lower))
    return needle in text_lower


@dataclass
class PhraseMatchCandidate:
    expected_phrase: str
    suggested_phrase: str
    excerpt: str
    confidence_score: float
    phrase_similarity: float
    conceptual_similarity: float
    context_alignment: float
    explanation: str


class CalibratedHybridNlpEngine:
    """
    Calibrated hybrid NLP analyzer combining canonical concept similarity,
    word/subword TF-IDF cosine similarity, and context-grounding gating.
    """

    engine_version = "calibrated-hybrid-tfidf-v1"

    def __init__(self, *, default_threshold: float = 0.56) -> None:
        self.default_threshold = default_threshold

    def score_phrase_pair(
        self,
        *,
        expected_phrase: str,
        candidate_phrase: str,
        criterion_context: str,
    ) -> dict[str, float]:
        exp_clean = (expected_phrase or "").strip()
        cand_clean = (candidate_phrase or "").strip()
        ctx_clean = (criterion_context or "").strip()

        if not exp_clean or not cand_clean:
            return {
                "confidence": 0.0,
                "lexical_sim": 0.0,
                "conceptual_sim": 0.0,
                "char_sim": 0.0,
                "context_alignment": 0.0,
            }

        cand_words = set(tokenize_words(cand_clean))
        exp_words = set(tokenize_words(exp_clean))
        if bool(cand_words & NEGATION_CUES) != bool(exp_words & NEGATION_CUES):
            return {
                "confidence": 0.0,
                "lexical_sim": 0.0,
                "conceptual_sim": 0.0,
                "char_sim": 0.0,
                "context_alignment": 0.0,
            }

        exp_stem = " ".join(_stem_token(t) for t in content_tokens(exp_clean))
        cand_stem = " ".join(_stem_token(t) for t in content_tokens(cand_clean))
        if not exp_stem or not cand_stem:
            return {
                "confidence": 0.0,
                "lexical_sim": 0.0,
                "conceptual_sim": 0.0,
                "char_sim": 0.0,
                "context_alignment": 0.0,
            }

        lexical_sim = self._word_tfidf_cosine(exp_stem, cand_stem, ngram_range=(1, 2))
        char_sim = self._char_tfidf_cosine(exp_clean.lower(), cand_clean.lower(), ngram_range=(3, 5))

        # Canonical concept similarity (Dice + TF-IDF in concept space)
        exp_units = set(canonical_concept_units(exp_clean))
        cand_units = set(canonical_concept_units(cand_clean))
        concept_dice = (
            (2.0 * len(exp_units & cand_units)) / (len(exp_units) + len(cand_units))
            if (exp_units and cand_units)
            else 0.0
        )

        exp_concept_str = expand_conceptual_representation(exp_clean)
        cand_concept_str = expand_conceptual_representation(cand_clean)
        ctx_concept_str = expand_conceptual_representation(f"{exp_clean} {ctx_clean}")

        concept_tfidf = self._word_tfidf_cosine(exp_concept_str, cand_concept_str, ngram_range=(1, 1))
        conceptual_sim = max(concept_dice, 0.65 * concept_dice + 0.35 * concept_tfidf)

        # Context-grounding check: ensure candidate tokens belong in the exam/criterion domain
        ctx_units = set(canonical_concept_units(f"{exp_clean} {ctx_clean}"))
        cand_token_units = canonical_concept_units(cand_clean)
        grounded_count = sum(1 for u in cand_token_units if u in ctx_units)
        grounded_ratio = grounded_count / len(cand_token_units) if cand_token_units else 0.0

        context_sim = self._word_tfidf_cosine(ctx_concept_str, cand_concept_str, ngram_range=(1, 1))

        # Gate out unrelated / misleading surface matches
        if grounded_ratio < 0.50 or context_sim < 0.08:
            confidence = 0.0
        else:
            surface_sim = max(lexical_sim, char_sim)
            core_sim = max(conceptual_sim, 0.6 * conceptual_sim + 0.4 * surface_sim)
            confidence = 0.68 * core_sim + 0.32 * min(1.0, context_sim * 1.45 + 0.35 * grounded_ratio)
            confidence = round(float(min(1.0, max(0.0, confidence))), 4)

        return {
            "confidence": confidence,
            "lexical_sim": round(lexical_sim, 4),
            "conceptual_sim": round(conceptual_sim, 4),
            "char_sim": round(char_sim, 4),
            "context_alignment": round(grounded_ratio, 4),
        }

    @staticmethod
    def _word_tfidf_cosine(text_a: str, text_b: str, *, ngram_range: tuple[int, int]) -> float:
        if not text_a.strip() or not text_b.strip():
            return 0.0
        try:
            vec = TfidfVectorizer(
                analyzer="word",
                ngram_range=ngram_range,
                lowercase=True,
                token_pattern=r"(?u)\b\w+\b",
            )
            mat = vec.fit_transform([text_a, text_b])
            return float(np.clip(cosine_similarity(mat[0:1], mat[1:2])[0][0], 0.0, 1.0))
        except ValueError:
            return 0.0

    @staticmethod
    def _char_tfidf_cosine(text_a: str, text_b: str, *, ngram_range: tuple[int, int]) -> float:
        if not text_a.strip() or not text_b.strip():
            return 0.0
        try:
            vec = TfidfVectorizer(analyzer="char_wb", ngram_range=ngram_range, lowercase=True)
            mat = vec.fit_transform([text_a, text_b])
            return float(np.clip(cosine_similarity(mat[0:1], mat[1:2])[0][0], 0.0, 1.0))
        except ValueError:
            return 0.0

    def detect_alternative_phrases(
        self,
        *,
        answer_text: str,
        criterion: dict[str, Any],
        question_prompt: str,
        model_answer: str = "",
        excluded_phrases: list[str] | None = None,
        threshold: float | None = None,
    ) -> list[PhraseMatchCandidate]:
        """
        Analyze a student's descriptive answer for missing rubric key concepts
        expressed using alternative wording above the calibrated confidence threshold.
        """
        cutoff = self.default_threshold if threshold is None else float(threshold)
        text_lower = " ".join((answer_text or "").lower().split())
        if not text_lower:
            return []

        key_concepts = [str(c).strip() for c in criterion.get("key_concepts", []) if str(c).strip()]
        existing_alts = [str(a).strip() for a in criterion.get("alternative_phrases", []) if str(a).strip()]
        if not key_concepts:
            return []

        missing_concepts = [
            kc
            for kc in key_concepts
            if not exact_phrase_present(text_lower, kc)
            and not any(exact_phrase_present(text_lower, alt) for alt in existing_alts)
        ]
        if not missing_concepts:
            return []

        criterion_context = " ".join(
            [
                str(question_prompt or ""),
                str(criterion.get("title", "")),
                str(criterion.get("description", "")),
                str(model_answer or ""),
            ]
        )
        candidates = extract_candidate_clauses_and_phrases(answer_text)
        if not candidates:
            return []

        best_matches: list[PhraseMatchCandidate] = []
        existing_lower = {k.lower() for k in key_concepts + existing_alts + list(excluded_phrases or [])}

        for expected in missing_concepts:
            best_for_expected: PhraseMatchCandidate | None = None
            for cand in candidates:
                cand_phrase = cand["phrase"]
                if cand_phrase.lower() in existing_lower:
                    continue
                scores = self.score_phrase_pair(
                    expected_phrase=expected,
                    candidate_phrase=cand_phrase,
                    criterion_context=criterion_context,
                )
                if scores["confidence"] >= cutoff:
                    if best_for_expected is None or scores["confidence"] > best_for_expected.confidence_score:
                        pct = round(scores["confidence"] * 100, 1)
                        explanation = (
                            f"Expected rubric concept '{expected}' was not matched verbatim, while the answer "
                            f"expressed '{cand_phrase}' with {pct}% calibrated alignment "
                            f"(conceptual={scores['conceptual_sim']:.2f}, lexical={scores['lexical_sim']:.2f}, "
                            f"context_grounding={scores['context_alignment']:.2f})."
                        )
                        best_for_expected = PhraseMatchCandidate(
                            expected_phrase=expected,
                            suggested_phrase=cand_phrase,
                            excerpt=cand["excerpt"],
                            confidence_score=scores["confidence"],
                            phrase_similarity=scores["lexical_sim"],
                            conceptual_similarity=scores["conceptual_sim"],
                            context_alignment=scores["context_alignment"],
                            explanation=explanation,
                        )
            if best_for_expected is not None:
                best_matches.append(best_for_expected)

        return best_matches
