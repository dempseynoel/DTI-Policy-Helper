"""Score the whole bank in one command.

    make eval ENV=dev                                         # current pipeline, in-process, judged
    uv run python -m evaluation.run_eval --pipeline baseline  # the naive control group
    uv run python -m evaluation.run_eval --target api --base-url https://...  (Lesson 13)
    uv run python -m evaluation.run_eval --rescore artifacts/eval/<run>/run.json   # no regeneration
    uv run python -m evaluation.run_eval --compare evaluation/baselines/reference-test.json

Running the pipeline and scoring it are separate steps: the run is cached as run.json, so
evaluators can be iterated on without paying for generation again.

Exits non-zero if --compare finds a regression (or can't compare), so CI can gate on it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from dti_rag.clients import throttled_response_count
from dti_rag.config import get_settings
from evaluation.compare import gate
from evaluation.qa_bank import load_bank
from evaluation.rows import Run, RunRow
from evaluation.runmeta import collect_meta
from evaluation.scorecard import Scorecard, render, score
from evaluation.targets import ApiTarget, BaselineTarget, LocalTarget, Target

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "eval"
BASELINES = ROOT / "evaluation" / "baselines"


def prompt_version(pipeline: str) -> str:
    if pipeline == "baseline":
        from dti_rag.retrieval.baseline import PROMPT_VERSION
    else:
        from dti_rag.generation.prompts import PROMPT_VERSION
    return PROMPT_VERSION


def execute(target: Target, only: set[str] | None) -> Run:
    settings = get_settings()
    meta = collect_meta(
        settings,
        target=target.name,
        pipeline=target.pipeline,
        prompt_version=prompt_version(target.pipeline),
    )
    rows: list[RunRow] = []
    for item in load_bank():
        if only and item.id not in only:
            continue
        try:
            rows.append(target.run(item))
            print(f"  {item.id} {rows[-1].mode:8} {rows[-1].latency_ms} ms")
        except Exception as exc:  # noqa: BLE001 - a failed row is a result, recorded and gated
            rows.append(
                RunRow(
                    qa_id=item.id,
                    category=item.category,
                    question=item.question,
                    pipeline=target.pipeline,
                    mode="error",
                    answer="",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            print(f"  {item.id} ERROR {exc}")
    meta.throttled_responses = throttled_response_count()
    return Run(meta=meta, rows=rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--target", choices=["local", "api"], default="local")
    parser.add_argument("--pipeline", choices=["current", "baseline"], default="current")
    parser.add_argument("--base-url", help="deployed app URL, for --target api")
    parser.add_argument("--token", help="bearer token for an app behind Entra ID authentication")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM-judge metrics")
    parser.add_argument("--rescore", type=Path, help="score an existing run.json; generate nothing")
    parser.add_argument("--compare", type=Path, help="reference scorecard.json to gate against")
    parser.add_argument(
        "--save-reference",
        action="store_true",
        help="write this scorecard as the reference for this environment",
    )
    parser.add_argument(
        "--only", help="comma-separated QA ids, for quick iteration (never for a gate)"
    )
    parser.add_argument("--out", type=Path, help="output directory")
    args = parser.parse_args()

    if args.rescore:
        run = Run.load(args.rescore)
    else:
        if args.target == "api":
            if not args.base_url:
                sys.exit("--target api needs --base-url")
            from dti_rag.observability.audit import read_record

            # Retrieved context is read back from the audit log by trace_id: every promotion
            # also proves the audit trail is complete.
            target: Target = ApiTarget(args.base_url, args.token, context_reader=read_record)
        else:
            target = BaselineTarget() if args.pipeline == "baseline" else LocalTarget()
        run = execute(target, set(args.only.split(",")) if args.only else None)

    if not args.no_judge and get_settings().azure_openai_judge_deployment:
        from evaluation.judge import judge_rows

        judge_rows(run.rows)

    card = score(run, load_bank())
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = (
        args.out or ARTIFACTS / f"{stamp}-{run.meta.app_env}-{run.meta.pipeline}-{run.meta.target}"
    )
    out.mkdir(parents=True, exist_ok=True)
    run.save(out / "run.json")
    (out / "scorecard.json").write_text(card.model_dump_json(indent=2) + "\n")

    reference = Scorecard.model_validate_json(args.compare.read_text()) if args.compare else None
    report = render(card, reference)
    passed = True
    if reference:
        passed, verdict = gate(reference, card)
        report += "\n" + verdict + "\n"
    (out / "scorecard.md").write_text(report)
    print("\n" + report)
    print(f"written to {out}")

    if args.save_reference:
        path = BASELINES / f"reference-{run.meta.app_env}.json"
        path.write_text(card.model_dump_json(indent=2) + "\n")
        print(f"reference saved: {path} (commit it)")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
