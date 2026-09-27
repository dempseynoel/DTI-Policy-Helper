"""check_env's comparison logic, offline, against hand-built live state."""

import copy

import pytest

from scripts.check_env import check_config_file, compare, load_expected, resource_ids

SUB = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def expected():
    e = load_expected("test")
    e["subscription_id"] = SUB
    e["shared"]["deployments"]["chat"].update(
        model="gpt-x", version="2026-01-01", sku="GlobalStandard"
    )
    e["shared"]["deployments"]["judge"].update(
        model="gpt-y", version="2026-02-01", sku="GlobalStandard"
    )
    e["shared"]["deployments"]["embed"].update(sku="GlobalStandard")
    e["this"]["capacity"] = {"chat": 100, "embed": 50, "judge": 50}
    return e


def healthy(expected) -> dict:
    ids = resource_ids(expected)
    dep = expected["shared"]["deployments"]
    app = "app-test"
    return {
        "locations": {"foundry": "uksouth", "search": "uksouth", "storage": "uksouth"},
        "foundry_local_auth_disabled": True,
        "deployments": {
            name: {
                **{
                    k: dep[name][k]
                    for k in ("model", "version", "sku", "upgrade", "content_filter")
                },
                "capacity": expected["this"]["capacity"][name],
            }
            for name in ("chat", "embed", "judge")
        },
        "search": {"replicas": 1, "local_auth_disabled": True, "semantic": "standard"},
        "storage": {"shared_key_access": False, "public_blob_access": False},
        "purge_protection": False,
        "delete_lock": False,
        "app_replicas": {"min": 0, "max": 2},
        "role_assignments": [
            {
                "principal_id": app,
                "principal_type": "ServicePrincipal",
                "role": role,
                "scope": scope,
            }
            for role, scope in (
                ("Foundry User", ids["foundry"]),
                ("Search Index Data Reader", ids["search"]),
                ("Storage Blob Data Contributor", ids["audit"]),
                ("AcrPull", ids["registry"]),
            )
        ],
        "principals": {
            "app": app,
            "other_environments": {"prod (id-dti-rag-deploy-prod)": "deploy-prod"},
        },
    }


def test_a_matching_environment_has_no_differences(expected):
    assert compare(expected, healthy(expected)) == []


def test_a_different_model_version_is_drift(expected):
    live = healthy(expected)
    live["deployments"]["chat"]["version"] = "2026-06-01"
    assert any("`chat` version" in d for d in compare(expected, live))


def test_a_missing_app_role_is_reported(expected):
    """The Lesson 13 exercise: remove Search Index Data Reader from test's app identity."""
    live = healthy(expected)
    live["role_assignments"] = [
        a for a in live["role_assignments"] if a["role"] != "Search Index Data Reader"
    ]
    assert "app identity is missing Search Index Data Reader" in " ".join(compare(expected, live))


def test_an_over_privileged_app_identity_is_reported(expected):
    live = healthy(expected)
    live["role_assignments"].append(
        {
            "principal_id": "app-test",
            "principal_type": "ServicePrincipal",
            "role": "Search Index Data Contributor",
            "scope": resource_ids(expected)["search"],
        }
    )
    assert any("must not hold Search Index Data Contributor" in d for d in compare(expected, live))


def test_a_human_with_data_roles_in_test_is_reported(expected):
    live = healthy(expected)
    live["role_assignments"].append(
        {
            "principal_id": "me",
            "principal_type": "User",
            "role": "Foundry User",
            "scope": resource_ids(expected)["foundry"],
        }
    )
    assert any("a human holds Foundry User" in d for d in compare(expected, live))


def test_another_environments_identity_is_reported(expected):
    live = healthy(expected)
    live["role_assignments"].append(
        {
            "principal_id": "deploy-prod",
            "principal_type": "ServicePrincipal",
            "role": "Reader",
            "scope": resource_ids(expected)["rg"],
        }
    )
    assert any("identity from prod" in d for d in compare(expected, live))


def test_an_unexpected_deployment_is_drift(expected):
    live = healthy(expected)
    live["deployments"]["experiment"] = copy.deepcopy(live["deployments"]["chat"])
    assert any("`experiment` exists" in d for d in compare(expected, live))


def test_config_file_pointing_at_another_environment_is_caught(expected):
    env_file = {
        "APP_ENV": "test",
        "AZURE_RESOURCE_GROUP": "rg-dti-rag-test",
        "AZURE_FOUNDRY_ACCOUNT": expected["this"]["foundry"],
        "AZURE_STORAGE_ACCOUNT": expected["this"]["storage"],
        "AZURE_OPENAI_ENDPOINT": f"https://{expected['this']['foundry']}.openai.azure.com/",
        "AZURE_SEARCH_ENDPOINT": "https://srch-dti-rag-dev-x.search.windows.net",  # dev's!
    }
    diffs = check_config_file(expected, env_file)
    assert len(diffs) == 1 and "AZURE_SEARCH_ENDPOINT" in diffs[0]
