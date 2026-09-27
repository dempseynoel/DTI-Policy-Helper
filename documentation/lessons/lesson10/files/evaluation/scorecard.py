"""Turn a scored run into a scorecard: retrieval, generation and behaviour, never blended."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from pydantic import BaseModel

from evaluation.evaluators import EVALUATORS, weak_includes
from evaluation.qa_bank import QAItem
from evaluation.rows import Run, RunMeta

RETRIEVAL = ("retrieval_recall", "retrieval_section_hit", "retrieval_purity")
GENERATION = ("must_include", "must_not_include", "edition_correct")
BEHAVIOUR = ("abstention_correct", "ambiguity_handled", "over_abstained")


class Scorecard(BaseModel):
    meta: RunMeta
    metrics: dict[str, float | None]  # rate over items the metric applies to
    counts: dict[str, str]  # "n/m", so small denominators stay visible
    by_category: dict[str, float]  # share of items passing every applicable generation check
    per_question: dict[str, dict[str, Any]]
    weak_checks: dict[str, list[str]]
    failed_rows: list[str]


def _rate(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def score(run: Run, bank: list[QAItem]) -> Scorecard:
    items = {i.id: i for i in bank}
    per_question: dict[str, dict[str, Any]] = {}
    collected: dict[str, list[bool]] = defaultdict(list)
    by_category: dict[str, list[bool]] = defaultdict(list)

    for row in run.rows:
        item = items[row.qa_id]
        results = {name: fn(row, item) for name, fn in EVALUATORS.items()}
        results["groundedness"] = row.groundedness
        results["probe_filtered_hit"] = row.probe_filtered_hit
        results["probe_unfiltered_hit"] = row.probe_unfiltered_hit
        results["mode"] = row.mode
        per_question[row.qa_id] = results
        for name in EVALUATORS:
            if results[name] is not None:
                collected[name].append(bool(results[name]))
        checks = [
            results[n]
            for n in ("must_include", "must_not_include", "abstention_correct", "ambiguity_handled")
        ]
        by_category[item.category].append(all(c is not False for c in checks))
        for probe in ("probe_filtered_hit", "probe_unfiltered_hit"):
            if results[probe] is not None:
                collected[probe].append(results[probe])

    metrics = {name: _rate(values) for name, values in collected.items()}
    judged = [r.groundedness for r in run.rows if r.groundedness is not None]
    metrics["groundedness_mean"] = round(mean(judged), 2) if judged else None
    return Scorecard(
        meta=run.meta,
        metrics=metrics,
        counts={name: f"{sum(v)}/{len(v)}" for name, v in collected.items()},
        by_category={c: round(sum(v) / len(v), 2) for c, v in sorted(by_category.items())},
        per_question=per_question,
        weak_checks={i.id: w for i in bank if (w := weak_includes(i))},
        failed_rows=[r.qa_id for r in run.rows if r.error],
    )


def render(card: Scorecard, reference: Scorecard | None = None) -> str:
    def cell(name: str, source: Scorecard | None) -> str:
        if source is None or source.metrics.get(name) is None:
            return "—"
        return f"{source.metrics[name]:.2f} ({source.counts.get(name, '')})".replace(" ()", "")

    m = card.meta
    lines = [
        f"## Scorecard: {m.pipeline} via {m.target} in {m.app_env}",
        "",
        f"git `{m.git_sha[:12]}` · prompt `{m.prompt_version}` · started {m.started_at} · "
        f"throttled responses: {m.throttled_responses}",
        "",
        "| Group | Metric | " + ("Reference | " if reference else "") + "This run |",
        "|---|---|" + ("---|" if reference else "") + "---|",
    ]
    groups = [
        ("retrieval", (*RETRIEVAL, "probe_filtered_hit", "probe_unfiltered_hit")),
        ("generation", (*GENERATION, "groundedness_mean")),
        ("behaviour", BEHAVIOUR),
    ]
    for group, names in groups:
        for name in names:
            ref = f"{cell(name, reference)} | " if reference else ""
            lines.append(f"| {group} | {name} | {ref}{cell(name, card)} |")
    lines += ["", "**By category** (all applicable generation and behaviour checks pass):", ""]
    for category, rate in card.by_category.items():
        before = f"{reference.by_category.get(category, 0):.2f} → " if reference else ""
        lines.append(f"- `{category}`: {before}{rate:.2f}")
    if card.weak_checks:
        weak = ", ".join(f"{k} {v}" for k, v in card.weak_checks.items())
        lines += ["", f"Weak `must_include` entries (pair with the judge): {weak}"]
    if card.failed_rows:
        lines += ["", f"**Rows that errored:** {', '.join(card.failed_rows)}"]
    return "\n".join(lines) + "\n"
