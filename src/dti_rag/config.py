"""One environment's configuration.

Locally, values come from the committed ``deploy/<APP_ENV>.env``, which ``terraform apply`` in
``infra/<APP_ENV>`` writes. In Azure there is no file and the same values arrive as environment
variables set by the pipeline. The file wins over
anything exported in your shell, so a stale ``export AZURE_OPENAI_ENDPOINT=...`` can't quietly
point you at another environment.

``app_env`` labels telemetry, scorecards and log lines, and guards destructive scripts. It must
never switch pipeline behaviour: if you write ``if settings.app_env == "prod":`` in pipeline
code, test is no longer a rehearsal for prod.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENTS = ("dev", "test", "prod")
Env = Literal["dev", "test", "prod"]


class Settings(BaseSettings):
    # A blank value in deploy/<env>.env means "not set yet", not an empty string.
    model_config = SettingsConfigDict(extra="ignore", frozen=True, env_ignore_empty=True)

    # --- Required from Lesson 01. No defaults: a missing value fails at startup. ---
    app_env: Env
    azure_openai_endpoint: str
    azure_openai_api_version: str
    azure_openai_chat_deployment: str
    azure_openai_embed_deployment: str
    azure_search_endpoint: str
    azure_search_api_version: str

    # --- Filled in when the lesson that needs them arrives. Code that needs one calls
    # settings.require(...), which fails loudly with the variable's name. ---
    azure_subscription_id: str | None = None  # L04: read serving model versions
    azure_resource_group: str | None = None  # L04
    azure_foundry_account: str | None = None  # L04
    azure_storage_account: str | None = None  # L04 experiment; L13 audit log
    azure_openai_judge_deployment: str | None = None  # L10: dev and test only, never prod
    azure_ai_services_endpoint: str | None = None  # L11: groundedness detection
    app_identity_client_id: str | None = None  # L12: the app's user-assigned identity
    git_sha: str | None = None  # L12: baked into the image at build time
    applicationinsights_connection_string: str | None = None  # L13
    trace_sampling_ratio: float = 1.0  # L13: 1.0 in dev and test; lower in prod (cost only)
    azure_search_index_override: str | None = None  # L13: throwaway PR-gate index only

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Committed file first, then process environment. In Azure there is no file.
        return (init_settings, dotenv_settings, env_settings)

    def require(self, *names: str) -> tuple[str, ...]:
        """Return the named optional settings, or fail naming every one that is missing."""
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            env_names = ", ".join(n.upper() for n in missing)
            raise RuntimeError(
                f"{env_names} not set for app_env={self.app_env}. "
                f"deploy/{self.app_env}.env is written by `terraform apply` in "
                f"infra/{self.app_env}: check deploy/environments.yaml and apply."
            )
        return tuple(getattr(self, n) for n in names)


def load_settings(env: str) -> Settings:
    if env not in ENVIRONMENTS:
        raise RuntimeError(
            f"APP_ENV must be one of {', '.join(ENVIRONMENTS)}; got {env!r}. "
            "Nothing defaults to an environment."
        )
    env_file = REPO_ROOT / "deploy" / f"{env}.env"
    settings = Settings(_env_file=env_file if env_file.is_file() else None)
    if settings.app_env != env:
        raise RuntimeError(
            f"APP_ENV={env} but the loaded configuration says app_env={settings.app_env}"
        )
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings for the environment named by APP_ENV. Loaded once per process."""
    return load_settings(os.environ.get("APP_ENV", ""))
