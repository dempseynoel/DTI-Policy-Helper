"""Integration tests run against a live environment named by APP_ENV.

    make test-integration ENV=dev     (your laptop)
    APP_ENV=test pytest -m integration   (CI, as the eval identity)

The test code is the same in every environment; only the configuration changes.
"""

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("APP_ENV"):
        return
    skip = pytest.mark.skip(reason="APP_ENV not set: integration tests need a live environment")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
