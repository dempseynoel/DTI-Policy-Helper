# Built ONCE per commit, tagged with the git SHA, promoted by digest.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/src

WORKDIR /app

# Dependencies first, so this layer is cached across code changes. The versions uv.lock pins
# (--locked fails the build if it's out of date), and only the core dependencies and the
# runtime extras: no dev group, no ingestion, evaluation or frameworks.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --extra api --extra observability

COPY data/fact_matrix/editions_fact_matrix.csv data/fact_matrix/editions_fact_matrix.csv
COPY src/ src/

# Which code gave this answer? Stamped into every response, trace and audit record.
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
CMD ["uvicorn", "dti_rag.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
