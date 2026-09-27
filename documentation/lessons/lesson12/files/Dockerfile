# Built ONCE per commit, tagged with the git SHA, promoted by digest.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Dependencies first, from pyproject.toml, so this layer is cached across code changes.
# Only the core dependencies and the runtime extras: no ingestion, evaluation or frameworks.
COPY pyproject.toml .
RUN python -c "import tomllib; p = tomllib.load(open('pyproject.toml', 'rb'))['project']; \
e = p['optional-dependencies']; \
print('\n'.join(p['dependencies'] + e['api'] + e.get('observability', [])))" > requirements.txt \
 && pip install -r requirements.txt \
 && rm requirements.txt

COPY data/fact_matrix/editions_fact_matrix.csv data/fact_matrix/editions_fact_matrix.csv
COPY src/ src/

# Which code gave this answer? Stamped into every response, trace and audit record.
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
CMD ["uvicorn", "dti_rag.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
