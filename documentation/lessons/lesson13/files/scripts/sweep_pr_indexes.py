"""Delete the PR gate's throwaway indexes on test's Search service.

    APP_ENV=test uv run python scripts/sweep_pr_indexes.py --index dti-policy-pr-42  # one PR's
    APP_ENV=test uv run python scripts/sweep_pr_indexes.py --all                     # nightly sweep

Basic tier has a small index limit, so a leaked PR index eventually fails an unrelated PR.
Runs in test only, and only ever touches indexes named dti-policy-pr-*.
"""

from __future__ import annotations

import argparse
import sys

from azure.core.exceptions import ResourceNotFoundError

from dti_rag.clients import search_client, search_index_client
from dti_rag.config import get_settings
from dti_rag.search.schema import MANIFEST_INDEX_NAME

PREFIX = "dti-policy-pr-"


def delete(name: str) -> None:
    if not name.startswith(PREFIX):
        sys.exit(f"refusing to delete {name}: not a PR index")
    try:
        search_index_client().delete_index(name)
        print(f"deleted index {name}")
    except ResourceNotFoundError:
        print(f"{name} already gone")
    search_client(MANIFEST_INDEX_NAME).delete_documents([{"index_name": name}])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--index")
    group.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if get_settings().app_env != "test":  # guarding a destructive script is what app_env is for
        sys.exit("PR indexes live on test's Search service; run with APP_ENV=test")
    names = (
        [args.index]
        if args.index
        else [n for n in search_index_client().list_index_names() if n.startswith(PREFIX)]
    )
    for name in names:
        delete(name)


if __name__ == "__main__":
    main()
