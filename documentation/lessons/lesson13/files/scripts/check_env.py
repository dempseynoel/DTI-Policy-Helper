"""Compare an environment's LIVE Azure configuration with deploy/environments.yaml.

    uv run python scripts/check_env.py --env test

Prints every difference and exits 1 if there are any. Read-only: Reader on the resource
groups is enough. The pipeline runs it before every deploy and blocks on drift; drift.yml
runs it nightly. Terraform builds each environment from the same file, so this is the
pipeline's plan: one that needs no Terraform state and no write access.

Structure: collect_live() makes the SDK calls and returns plain facts; compare() and
check_config_file() are pure and unit-tested offline (tests/unit/test_check_env.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "deploy" / "environments.yaml"

# Built-in role definition IDs (the same in every tenant).
ROLES = {
    "53ca6127-db72-4b80-b1b0-d745d6d5456d": "Foundry User",
    "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd": "Cognitive Services OpenAI User",
    "1407120a-92aa-4202-b7e9-c0e197c71c8f": "Search Index Data Reader",
    "8ebe5a00-799e-43f5-93ac-243d3dce84a7": "Search Index Data Contributor",
    "7ca78c08-252a-4471-8644-bb5ff32d4ba0": "Search Service Contributor",
    "ba92f5b4-2d11-453d-a403-e96b0029c9fe": "Storage Blob Data Contributor",
    "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1": "Storage Blob Data Reader",
    "7f951dda-4ed3-4680-a7ca-43fe172d538d": "AcrPull",
    "8311e382-0749-4cb8-b61a-304f252e45ec": "AcrPush",
    "acdd72a7-3385-48ef-bd42-f606fba81ae7": "Reader",
    "b24988ac-6180-42a0-ab88-20f7382dd24c": "Contributor",
    "8e3af657-a8ff-443c-a75c-2fe8c4bcb635": "Owner",
}
DATA_ROLES = {
    "Foundry User",
    "Cognitive Services OpenAI User",
    "Search Index Data Reader",
    "Search Index Data Contributor",
    "Storage Blob Data Contributor",
    "Storage Blob Data Reader",
}
APP_FORBIDDEN = {
    "Search Index Data Contributor",
    "Search Service Contributor",
    "Contributor",
    "Owner",
}


def load_expected(env: str, path: Path = EXPECTED) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if env not in data["environments"]:
        raise SystemExit(f"{env} is not in {path}")
    return {**data, "env": env, "this": data["environments"][env]}


def resource_ids(expected: dict[str, Any]) -> dict[str, str]:
    sub, e = expected["subscription_id"], expected["this"]
    rg = f"/subscriptions/{sub}/resourceGroups/{e['resource_group']}"
    return {
        "rg": rg,
        "foundry": f"{rg}/providers/Microsoft.CognitiveServices/accounts/{e['foundry']}",
        "search": f"{rg}/providers/Microsoft.Search/searchServices/{e['search']}",
        "storage": f"{rg}/providers/Microsoft.Storage/storageAccounts/{e['storage']}",
        "audit": f"{rg}/providers/Microsoft.Storage/storageAccounts/{e['storage']}"
        "/blobServices/default/containers/audit",
        "registry": f"/subscriptions/{sub}/resourceGroups/{expected['registry']['resource_group']}"
        f"/providers/Microsoft.ContainerRegistry/registries/{expected['registry']['name']}",
    }


# --------------------------------------------------------------------------- pure checks


def compare(expected: dict[str, Any], live: dict[str, Any]) -> list[str]:
    shared, this = expected["shared"], expected["this"]
    ids = resource_ids(expected)
    diffs: list[str] = []

    def want(label: str, expect: Any, actual: Any) -> None:
        if str(expect).lower() != str(_value(actual)).lower():
            diffs.append(f"{label}: expected {expect}, found {actual}")

    for resource, region in live["locations"].items():
        want(f"{resource} region", shared["region"], region)
    want(
        "Foundry key access disabled",
        shared["foundry_local_auth_disabled"],
        live["foundry_local_auth_disabled"],
    )
    want(
        "Search key access disabled",
        shared["search_local_auth_disabled"],
        live["search"]["local_auth_disabled"],
    )
    want("semantic ranker plan", shared["semantic_ranker"], live["search"]["semantic"])
    want("Search replicas", this["search_replicas"], live["search"]["replicas"])
    want(
        "Storage shared-key access",
        shared["storage_shared_key_access"],
        live["storage"]["shared_key_access"],
    )
    want(
        "Storage public blob access",
        shared["storage_public_blob_access"],
        live["storage"]["public_blob_access"],
    )
    want("Key Vault purge protection", this["purge_protection"], live["purge_protection"])
    want("resource-group delete lock", this["delete_lock"], live["delete_lock"])
    want("Container App min replicas", this["app_replicas"]["min"], live["app_replicas"]["min"])
    want("Container App max replicas", this["app_replicas"]["max"], live["app_replicas"]["max"])

    expected_deployments = set(this["capacity"])
    for name in sorted(expected_deployments | set(live["deployments"])):
        if name not in live["deployments"]:
            diffs.append(f"deployment `{name}` is missing")
            continue
        if name not in expected_deployments:
            diffs.append(f"deployment `{name}` exists but isn't expected in {expected['env']}")
            continue
        spec, found = shared["deployments"][name], live["deployments"][name]
        for key in ("model", "version", "sku", "upgrade", "content_filter"):
            want(f"`{name}` {key}", spec[key], found.get(key))
        want(f"`{name}` capacity (K TPM)", this["capacity"][name], found.get("capacity"))

    diffs += compare_roles(expected, live, ids)
    return diffs


def compare_roles(expected: dict[str, Any], live: dict[str, Any], ids: dict[str, str]) -> list[str]:
    this, diffs = expected["this"], []
    principals = live["principals"]
    app = principals.get("app")
    assignments = live["role_assignments"]

    def has(principal: str | None, role: str, scope: str) -> bool:
        return any(
            a["principal_id"] == principal
            and a["role"] == role
            and a["scope"].lower() == scope.lower()
            for a in assignments
        )

    if app is None:
        diffs.append(f"app identity {this['app_identity']} not found")
    else:
        for role, scope in (
            ("Foundry User", ids["foundry"]),
            ("Search Index Data Reader", ids["search"]),
            ("Storage Blob Data Contributor", ids["audit"]),
            ("AcrPull", ids["registry"]),
        ):
            if not has(app, role, scope):
                diffs.append(f"app identity is missing {role} on {scope.rsplit('/', 1)[-1]}")
        for a in assignments:
            if a["principal_id"] == app and a["role"] in APP_FORBIDDEN:
                diffs.append(f"app identity must not hold {a['role']} ({a['scope']})")

    if not this["human_data_roles_allowed"]:
        for a in assignments:
            if a["principal_type"] == "User" and a["role"] in DATA_ROLES:
                diffs.append(f"a human holds {a['role']} on {a['scope'].rsplit('/', 1)[-1]}")

    rg = ids["rg"].lower()
    for other_env, principal in principals.get("other_environments", {}).items():
        for a in assignments:
            if a["principal_id"] == principal and a["scope"].lower().startswith(rg):
                diffs.append(f"an identity from {other_env} holds {a['role']} in {expected['env']}")
    return diffs


def check_config_file(expected: dict[str, Any], env_file: dict[str, str]) -> list[str]:
    """deploy/<env>.env must point only at this environment's resources."""
    this, diffs = expected["this"], []
    checks = {
        "APP_ENV": (env_file.get("APP_ENV"), expected["env"]),
        "AZURE_RESOURCE_GROUP": (env_file.get("AZURE_RESOURCE_GROUP"), this["resource_group"]),
        "AZURE_FOUNDRY_ACCOUNT": (env_file.get("AZURE_FOUNDRY_ACCOUNT"), this["foundry"]),
        "AZURE_STORAGE_ACCOUNT": (env_file.get("AZURE_STORAGE_ACCOUNT"), this["storage"]),
        "AZURE_OPENAI_ENDPOINT host": (
            (urlparse(env_file.get("AZURE_OPENAI_ENDPOINT", "")).hostname or "").split(".")[0],
            this["foundry"],
        ),
        "AZURE_SEARCH_ENDPOINT host": (
            (urlparse(env_file.get("AZURE_SEARCH_ENDPOINT", "")).hostname or "").split(".")[0],
            this["search"],
        ),
    }
    for label, (found, want) in checks.items():
        if found != want:
            diffs.append(f"deploy/{expected['env']}.env {label} is {found!r}, expected {want!r}")
    if expected["env"] == "prod" and env_file.get("AZURE_OPENAI_JUDGE_DEPLOYMENT"):
        diffs.append("deploy/prod.env names a judge deployment; prod has none")
    return diffs


def read_env_file(env: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / "deploy" / f"{env}.env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


# --------------------------------------------------------------------------- live state


def _value(x: Any) -> Any:
    """SDK enums are (str, Enum) mixins; str() of one can be 'Class.MEMBER'. Use the value."""
    return getattr(x, "value", x)


def _first(obj: Any, *paths: str) -> Any:
    """Read an attribute that moves between SDK generations (x.a or x.properties.a)."""
    for path in paths:
        value = obj
        for part in path.split("."):
            value = getattr(value, part, None)
            if value is None:
                break
        if value is not None:
            return value
    return None


def collect_live(expected: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - Azure I/O
    from azure.core.exceptions import HttpResponseError
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.appcontainers import ContainerAppsAPIClient
    from azure.mgmt.authorization import AuthorizationManagementClient
    from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
    from azure.mgmt.keyvault import KeyVaultManagementClient
    from azure.mgmt.msi import ManagedServiceIdentityClient
    from azure.mgmt.resource.locks import ManagementLockClient
    from azure.mgmt.search import SearchManagementClient
    from azure.mgmt.storage import StorageManagementClient

    cred, sub, e = DefaultAzureCredential(), expected["subscription_id"], expected["this"]
    rg = e["resource_group"]
    ids = resource_ids(expected)

    cog = CognitiveServicesManagementClient(cred, sub)
    account = cog.accounts.get(rg, e["foundry"])
    deployments = {}
    for d in cog.deployments.list(rg, e["foundry"]):
        props = d.properties
        deployments[d.name] = {
            "model": props.model.name,
            "version": props.model.version,
            "sku": d.sku.name if d.sku else None,
            "capacity": d.sku.capacity if d.sku else None,
            "upgrade": _value(props.version_upgrade_option),
            "content_filter": props.rai_policy_name,
        }

    search = SearchManagementClient(cred, sub).services.get(rg, e["search"])
    storage = StorageManagementClient(cred, sub).storage_accounts.get_properties(rg, e["storage"])
    vault = KeyVaultManagementClient(cred, sub).vaults.get(rg, e["key_vault"])
    locks = ManagementLockClient(cred, sub).management_locks.list_at_resource_group_level(rg)
    app = ContainerAppsAPIClient(cred, sub).container_apps.get(rg, e["container_app"])
    scale = _first(app, "template.scale", "properties.template.scale")

    msi = ManagedServiceIdentityClient(cred, sub)

    def principal(group: str, name: str) -> str | None:
        """None if the identity doesn't exist yet, or if this caller can't see it: a deploy
        identity is blind to other environments by design. drift.yml, which reads every
        environment, is what proves cross-environment isolation."""
        try:
            return msi.user_assigned_identities.get(group, name).principal_id
        except HttpResponseError:
            return None

    others: dict[str, str] = {}
    for other, spec in expected["environments"].items():
        if other == expected["env"]:
            continue
        for identity, group in (
            (spec["app_identity"], spec["resource_group"]),
            (spec["deploy_identity"], expected["registry"]["resource_group"]),
        ):
            if pid := principal(group, identity):
                others[f"{other} ({identity})"] = pid

    auth = AuthorizationManagementClient(cred, sub)
    assignments = []
    for scope in (ids["rg"], ids["registry"]):
        for a in auth.role_assignments.list_for_scope(scope):
            role_id = a.role_definition_id.rsplit("/", 1)[-1]
            assignments.append(
                {
                    "principal_id": a.principal_id,
                    "principal_type": _value(a.principal_type),
                    "role": ROLES.get(role_id, role_id),
                    "scope": a.scope,
                }
            )

    shared_key = _first(storage, "allow_shared_key_access", "properties.allow_shared_key_access")
    return {
        "locations": {
            "foundry": account.location,
            "search": search.location,
            "storage": storage.location,
        },
        "foundry_local_auth_disabled": bool(_first(account, "properties.disable_local_auth")),
        "deployments": deployments,
        "search": {
            "replicas": search.replica_count,
            "local_auth_disabled": bool(search.disable_local_auth),
            "semantic": _value(search.semantic_search),
        },
        "storage": {
            # Unset means the platform default, which is ON.
            "shared_key_access": True if shared_key is None else shared_key,
            "public_blob_access": bool(
                _first(storage, "allow_blob_public_access", "properties.allow_blob_public_access")
            ),
        },
        "purge_protection": bool(_first(vault, "properties.enable_purge_protection")),
        "delete_lock": any(_value(lock.level) == "CanNotDelete" for lock in locks),
        "app_replicas": {"min": scale.min_replicas, "max": scale.max_replicas},
        "role_assignments": assignments,
        "principals": {
            "app": principal(rg, e["app_identity"]),
            "other_environments": others,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--env", required=True, choices=["dev", "test", "prod"])
    args = parser.parse_args()

    expected = load_expected(args.env)
    diffs = check_config_file(expected, read_env_file(args.env))
    diffs += compare(expected, collect_live(expected))
    if diffs:
        print(f"DRIFT in {args.env}: {len(diffs)} difference(s)")
        for d in diffs:
            print(f"  - {d}")
        sys.exit(1)
    print(f"{args.env} matches deploy/environments.yaml")


if __name__ == "__main__":
    main()
