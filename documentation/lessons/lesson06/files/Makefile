# Targets that touch Azure need ENV set explicitly, e.g. `make smoke ENV=dev`.
# There is deliberately no default: a command that defaults to an environment will one day
# default to the wrong one.

PY ?= python

.PHONY: setup test test-integration lint smoke chunks index baseline require-env

setup:
	$(PY) -m pip install -e ".[dev]"
	pre-commit install

test:
	$(PY) -m pytest

test-integration: require-env
	APP_ENV=$(ENV) $(PY) -m pytest -m integration

lint:
	ruff check src tests scripts evaluation

require-env:
	@case "$(ENV)" in dev|test|prod) ;; \
	  *) echo "Set ENV to dev, test or prod, e.g. make $(MAKECMDGOALS) ENV=dev"; exit 1;; esac

smoke: require-env
	APP_ENV=$(ENV) $(PY) scripts/smoke_test.py

chunks:
	$(PY) -m dti_rag.ingestion

index: require-env
	APP_ENV=$(ENV) $(PY) -m dti_rag.search.loader

baseline: require-env
	APP_ENV=$(ENV) $(PY) -m evaluation.run_baseline
