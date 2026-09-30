"""Smoke-test a DEPLOYED app through its API. Deterministic checks only.

    uv run python scripts/smoke_api.py --base-url https://ca-dti-rag-dev.<...>.azurecontainerapps.io
    uv run python scripts/smoke_api.py --base-url ... --token "$(az account get-access-token \
        --resource "$APP_AUDIENCE" --query accessToken -o tsv)"      # behind Entra ID auth

Checks the things only a deployment can get wrong: the image, the identity's roles, the
environment variables, the loaded index, and that the guardrails are wired in.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

DATED = (
    "A customer's kitchen flooded on 15 March 2024 when a dishwasher hose burst. "
    "What excess applies?"
)
UNHELD = "What was the standard excess under the 2021 edition, DTI-HOME-PW-2021-v1.0?"


def wait_for_health(client: httpx.Client, env: str | None, timeout: int = 300) -> None:
    """Scale-to-zero apps cold-start: poll until warm rather than failing the first request."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            r = client.get("/health")
            if r.status_code == 200:
                body = r.json()
                if env and body["app_env"] != env:
                    sys.exit(f"FAIL: expected app_env={env}, the app says {body['app_env']}")
                print(f"health: {body}")
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            sys.exit("FAIL: /health never answered")
        time.sleep(10)


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {label}{': ' + detail if detail and not ok else ''}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token")
    parser.add_argument("--env", help="the app_env the deployment must report")
    args = parser.parse_args()
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    client = httpx.Client(base_url=args.base_url.rstrip("/"), headers=headers, timeout=180)

    wait_for_health(client, args.env)
    results = []

    editions = client.get("/editions").json()
    results.append(check("editions registry is in the image", len(editions) == 5, str(editions)))

    r = client.post("/chat", json={"question": DATED}).json()
    results.append(
        check(
            "dated question selects the 2024 edition",
            r["governing_editions"] == ["DTI-HOME-PW-2024-v1.0"],
            str(r["governing_editions"]),
        )
    )
    results.append(
        check("answer carries a citation (index loaded, roles work)", bool(r["citations"]))
    )
    results.append(
        check(
            "edition_reason names the loss date",
            "15 March 2024" in r["edition_reason"],
            r["edition_reason"],
        )
    )

    r = client.post("/chat", json={"question": UNHELD}).json()
    results.append(check("unheld edition abstains", r["mode"] == "abstain", r["mode"]))

    # A request the guardrails MUST reject, deterministically: proves they're wired in.
    status = client.post("/chat", json={"question": "\x00" * 10}).status_code
    results.append(check("input guardrail rejects an empty question", status == 422, str(status)))

    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
