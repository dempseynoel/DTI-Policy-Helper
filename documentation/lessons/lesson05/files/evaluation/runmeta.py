"""Collect a run's provenance: environment, serving model versions, index manifest, code."""

from __future__ import annotations

import subprocess
from dataclasses import asdict
from datetime import UTC, datetime

from dti_rag.config import Settings
from dti_rag.runinfo import serving_models
from dti_rag.search.manifest import read_manifest
from dti_rag.search.schema import index_name
from evaluation.rows import RunMeta


def git_sha(settings: Settings) -> str:
    if settings.git_sha:
        return settings.git_sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        return out.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def collect_meta(settings: Settings, *, target: str, pipeline: str, prompt_version: str) -> RunMeta:
    return RunMeta(
        app_env=settings.app_env,
        target=target,
        pipeline=pipeline,
        prompt_version=prompt_version,
        git_sha=git_sha(settings),
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        # Read from the Foundry resource now, not copied from config: record what was true.
        serving_models={name: asdict(m) for name, m in serving_models(settings).items()},
        index_manifest=read_manifest(index_name(settings)),
    )
