from pathlib import Path

import pytest

from dti_rag import config
from dti_rag.config import Settings, load_settings

REQUIRED = {
    "APP_ENV": "dev",
    "AZURE_OPENAI_ENDPOINT": "https://ai-dti-rag-dev.openai.azure.com/",
    "AZURE_OPENAI_API_VERSION": "2024-10-21",
    "AZURE_OPENAI_CHAT_DEPLOYMENT": "chat",
    "AZURE_OPENAI_EMBED_DEPLOYMENT": "embed",
    "AZURE_SEARCH_ENDPOINT": "https://srch-dti-rag-dev.search.windows.net",
    "AZURE_SEARCH_API_VERSION": "2024-07-01",
}


def write_env(root: Path, env: str, values: dict[str, str]) -> None:
    (root / "deploy").mkdir(exist_ok=True)
    (root / "deploy" / f"{env}.env").write_text("\n".join(f"{k}={v}" for k, v in values.items()))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    for key in REQUIRED:
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def test_loads_the_committed_file(repo):
    write_env(repo, "dev", REQUIRED)
    settings = load_settings("dev")
    assert settings.app_env == "dev"
    assert settings.azure_openai_chat_deployment == "chat"


def test_committed_file_beats_a_stale_shell_export(repo, monkeypatch):
    write_env(repo, "dev", REQUIRED)
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://srch-dti-rag-test.search.windows.net")
    assert "dev" in load_settings("dev").azure_search_endpoint


def test_environment_variables_are_used_when_there_is_no_file(repo, monkeypatch):
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    assert load_settings("dev").azure_openai_embed_deployment == "embed"


@pytest.mark.parametrize("env", ["", "staging", "Dev"])
def test_no_default_environment(repo, env):
    with pytest.raises(RuntimeError, match="APP_ENV"):
        load_settings(env)


def test_file_for_the_wrong_environment_is_rejected(repo):
    write_env(repo, "test", REQUIRED)  # says APP_ENV=dev inside test.env
    with pytest.raises(RuntimeError, match="app_env=dev"):
        load_settings("test")


def test_missing_required_value_fails_at_startup(repo):
    values = dict(REQUIRED)
    del values["AZURE_SEARCH_ENDPOINT"]
    write_env(repo, "dev", values)
    with pytest.raises(Exception, match="azure_search_endpoint"):
        load_settings("dev")


def test_require_names_the_missing_variable():
    settings = Settings(**{k.lower(): v for k, v in REQUIRED.items()})
    with pytest.raises(RuntimeError, match="AZURE_STORAGE_ACCOUNT"):
        settings.require("azure_storage_account")


def test_blank_values_mean_not_set(repo):
    write_env(repo, "dev", {**REQUIRED, "AZURE_OPENAI_JUDGE_DEPLOYMENT": "", "GIT_SHA": ""})
    settings = load_settings("dev")
    assert settings.azure_openai_judge_deployment is None
    assert settings.git_sha is None


def test_a_blank_required_value_fails(repo):
    write_env(repo, "dev", {**REQUIRED, "AZURE_SEARCH_ENDPOINT": ""})
    with pytest.raises(Exception, match="azure_search_endpoint"):
        load_settings("dev")
