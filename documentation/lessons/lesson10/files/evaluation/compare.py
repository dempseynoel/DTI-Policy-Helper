"""Compare a scorecard with a reference, and gate on it.

    python -m evaluation.compare REFERENCE.json CANDIDATE.json [--summary out.md]

Refuses to compare scorecards from different sources (serving model versions, index
manifest): a "regression" that is really a model upgrade or an environment mismatch
teaches people to ignore the gate.

Gate rules, per metric, never on an aggregate:
- edition_correct, abstention_correct, ambiguity_handled: zero tolerance, per question.
  Deterministic at temperature 0, so any drop is real.
- over_abstained: zero tolerance (a new abstention on an answerable question).
- must_include: at most MUST_INCLUDE_TOLERANCE newly failing questions.
- groundedness_mean: may not drop by more than GROUNDEDNESS_TOLERANCE (LLM-judged, noisy).

Widening these until the gate stops failing decommissions it. Change them by pull request,
with a reason.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evaluation.scorecard import Scorecard

ZERO_TOLERANCE = ("edition_correct", "abstention_correct", "ambiguity_handled")
MUST_INCLUDE_TOLERANCE = 1
GROUNDEDNESS_TOLERANCE = 0.25


def comparable(reference: Scorecard, candidate: Scorecard) -> list[str]:
    """Reasons the two scorecards can't be compared. Empty means comparable."""
    problems: list[str] = []
    for deployment in ("chat", "embed", "judge"):
        ref = reference.meta.serving_models.get(deployment, {})
        cand = candidate.meta.serving_models.get(deployment, {})
        if deployment == "judge" and not (ref and cand):
            continue  # a run recorded before `judge` existed has no judge scores to compare
        if (ref.get("model"), ref.get("version")) != (cand.get("model"), cand.get("version")):
            problems.append(
                f"`{deployment}` differs: {ref.get('model')} {ref.get('version')} vs "
                f"{cand.get('model')} {cand.get('version')}"
            )
    ref_m, cand_m = reference.meta.index_manifest or {}, candidate.meta.index_manifest or {}
    for key in ("embed_model_version", "schema_version"):
        if ref_m.get(key) != cand_m.get(key):
            problems.append(
                f"index manifest `{key}` differs: {ref_m.get(key)} vs {cand_m.get(key)}"
            )
    return problems


def regressions(reference: Scorecard, candidate: Scorecard) -> list[str]:
    found: list[str] = []

    def newly(metric: str, bad: bool = False) -> list[str]:
        out = []
        for qa_id, results in candidate.per_question.items():
            before = reference.per_question.get(qa_id, {}).get(metric)
            after = results.get(metric)
            if before is None or after is None:
                continue
            if (before and not after) if not bad else (not before and after):
                out.append(qa_id)
        return out

    for metric in ZERO_TOLERANCE:
        if ids := newly(metric):
            found.append(f"{metric} regressed on {', '.join(ids)}")
    if ids := newly("over_abstained", bad=True):
        found.append(f"new abstentions on answerable questions: {', '.join(ids)}")
    if len(ids := newly("must_include")) > MUST_INCLUDE_TOLERANCE:
        found.append(f"must_include regressed on {', '.join(ids)}")
    ref_g, cand_g = (
        reference.metrics.get("groundedness_mean"),
        candidate.metrics.get("groundedness_mean"),
    )
    if ref_g is not None and cand_g is not None and cand_g < ref_g - GROUNDEDNESS_TOLERANCE:
        found.append(f"groundedness_mean dropped {ref_g} -> {cand_g}")
    if candidate.failed_rows:
        found.append(f"rows errored: {', '.join(candidate.failed_rows)}")
    return found


def gate(reference: Scorecard, candidate: Scorecard) -> tuple[bool, str]:
    problems = comparable(reference, candidate)
    if problems:
        return (
            False,
            "**Not comparable** (fix the environment, or regenerate the reference):\n"
            + "\n".join(f"- {p}" for p in problems),
        )
    found = regressions(reference, candidate)
    if found:
        return False, "**Gate failed:**\n" + "\n".join(f"- {r}" for r in found)
    return True, "**Gate passed:** no regression against the reference."


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--summary", type=Path, help="write the verdict as markdown here")
    args = parser.parse_args()
    reference = Scorecard.model_validate_json(args.reference.read_text())
    candidate = Scorecard.model_validate_json(args.candidate.read_text())
    passed, verdict = gate(reference, candidate)
    print(verdict)
    if args.summary:
        args.summary.write_text(verdict + "\n")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
