# Lesson 04 — Build and load the Azure AI Search index

**Objective:** a versioned index with a vector field, filterable metadata and a semantic
configuration, loaded two ways so you understand both, with a manifest recording exactly
what it holds.

**Deliverables:**

- `src/dti_rag/search/`: `schema.py`, `documents.py`, `loader.py`, `manifest.py`
- `make index ENV=dev`: builds the index from nothing; a second run changes nothing
- `scripts/compare_filters.py`: the same query unfiltered, by year and by date
- the integrated-vectorization experiment, run in dev and then deleted

---

## Work backwards from what retrieval needs

| Lessons 06–08 need to… | So the index needs |
|---|---|
| Search text with BM25 | `content` searchable (English analyzer) |
| Search vectors | `contentVector`, HNSW, **3072** dimensions |
| Embed query text without code | A **vectorizer** on the vector profile |
| Filter by loss date | `effective_from` / `effective_to` as **`Edm.DateTimeOffset`**, filterable |
| Filter by edition / status | `doc_id`, `edition_year`, `version`, `status` filterable |
| Retrieve a whole section (Lesson 08 signposts) | `section_group` filterable |
| Rerank semantically | A semantic configuration: `section_title` as title, `content` as content |
| Cite | `doc_id`, `section_id`, `page` retrievable |

Every one of those is a decision you can't change without rebuilding: Azure AI Search won't
make an existing field filterable. On this corpus a rebuild takes two minutes; on a real one
it's an outage. So the index **name is versioned in code**: `dti-policy-v{SCHEMA_VERSION}`.

### Decisions worth dwelling on

- **Vector dimensions are immutable.** Truncating `text-embedding-3-large` to 1024 later is a
  new index. Take the full 3072 now; `constants.EMBED_DIMENSIONS` and the smoke test already
  assert it.
- **`DateTimeOffset` needs ISO 8601 with an offset**: `2024-01-01T00:00:00Z`, not
  `1 January 2024`. `documents.to_offset()` does it, at midnight UTC as `SCHEMA.md` decided.
- **Semantic ranking needs two things in two places.** The **plan** is a service setting
  (`semantic_ranker` in `environments.yaml`, applied by Terraform); the **configuration** is
  in the index, created by the loader. A missing plan
  fails in one environment only and looks like a code bug.
- **`metadata_json`** is a retrievable JSON copy of the metadata. LlamaIndex requires such a
  field (Lesson 09). It's in the schema from the start so Lesson 09 doesn't force a
  `SCHEMA_VERSION` bump.

---

## Loading path 1: push (build this first)

`src/dti_rag/search/loader.py`, run with `make index ENV=dev`. Build it first, even though
it's more work: you'll know the field names, the vector size and the document shape because
you constructed every one, and that's what lets you debug retrieval in Lesson 06.

What it does, in order:

1. **Refuses to run without `APP_ENV`.** A loader that defaults to an environment will one
   day load the wrong one.
2. Reads `deploy/<env>.env`, `artifacts/chunks.jsonl` and its SHA-256.
3. **Reads the `embed` deployment's model and version from the Foundry resource** (the
   management plane, via `runinfo.py`) and checks it's `text-embedding-3-large`.
4. Creates or updates the index and the small `dti-manifest` index from code.
5. **Skips everything else if the manifest already records this corpus, schema and embedding
   model.** A second run is a no-op.
6. Embeds in batches of 16 with *this environment's* `embed` deployment. Vectors are never
   copied between environments: the model is pinned identically everywhere, so they're
   equivalent, and each environment stays self-contained.
7. Uploads with `mergeOrUpload` in batches, and **checks every per-document result.**
   Partial failure is normal and doesn't raise; swallowing it gives you an index quietly
   missing the 2022 edition.
8. **Deletes orphans.** `mergeOrUpload` never deletes, so a chunk from an old chunking
   strategy would stay retrievable for ever.
9. Writes the manifest: schema version, chunks SHA-256 and count, embedding deployment, model
   and version, load time, git SHA.

"Which corpus, embedded by which model, is prod serving?" now has an answer that doesn't
depend on anyone's memory. The smoke test prints it, and every scorecard records it.

---

## Loading path 2: integrated vectorization (the experiment)

`scripts/experiments/integrated_vectorization.py`, **dev only** (it refuses anywhere else).
It uploads the PDFs to the `corpus` container and builds a data source, a skillset (**Text
Split** + **AzureOpenAIEmbedding**) with index projections, an index and an indexer, all
named `dti-iv-experiment`. Run it, check progress with `--status`, query the result in the
portal's Search Explorer, then **`--delete` it**.

The indexer and embedding skill run **as the Search service's managed identity**: hence
Lesson 01's roles for it (Storage Blob Data Reader, Cognitive Services OpenAI User). With
storage keys off, the data source uses the managed-identity connection string
(`ResourceId=/subscriptions/…;`).

**The tension worth noticing:** Text Split chunks by size. Look at what came back: section
IDs gone, edition metadata gone, Section 8's two lines merged into a neighbour. So the honest
conclusion for *this* corpus:

> Integrated vectorization is excellent when generic chunking is acceptable. Here it isn't.
> Use the push model with your own section-aware chunks, and use integrated vectorization's
> **vectorizer**, so query-time embedding is handled for you.

That's the design `schema.py` implements: push-loaded documents, plus an
`AzureOpenAIVectorizer` on the vector profile. Record the judgement; it belongs in Lesson
09's `FRAMEWORKS.md`.

**The portal's Import wizard is fine for *seeing* integrated vectorization in dev.** But
whatever it builds exists in dev only. An index that exists because someone clicked a wizard
in one environment is drift on day one. Delete it.

---

## The demonstration

```bash
APP_ENV=dev python scripts/compare_filters.py
```

The same query three ways: pure vector, `edition_year eq 2024`, and the loss-date range
`effective_from le 2024-03-15T00:00:00Z and effective_to ge 2024-03-15T00:00:00Z`.

**Look at run 1 properly.** Five editions of 3.4 with scores separated in the third decimal
place. That's the Lesson 02 argument made visible: the ranking between editions is noise, and
no reranker fixes noise. Screenshot it; it's the best slide in your capstone.

---

## One loader, three environments

**Terraform builds the Search *service*; the loader owns everything *inside* it.** In dev
you run `make index`; in test and prod the pipeline runs it as that environment's deploy
identity (Lesson 13).

- **Versioned index name, in code, not config.** A schema change bumps `SCHEMA_VERSION`, so
  the new index is built *alongside* the old one, and the app that expects it deploys after.
  Rollback is redeploying the previous app, whose index still exists. The name is the same in
  every environment, which is why it isn't in `deploy/<env>.env`. Delete old versions once
  nothing points at them.
- **The only override** is `AZURE_SEARCH_INDEX_OVERRIDE`, used by Lesson 13's PR gate for a
  throwaway `dti-policy-pr-<n>` index. Nothing else sets it.

---

## Files in this lesson

| File | New / changed | Purpose |
|---|---|---|
| `src/dti_rag/search/__init__.py` | new | The package |
| `src/dti_rag/search/schema.py` | new | `SCHEMA_VERSION`, index and manifest-index definitions, vectorizer, semantic config |
| `src/dti_rag/search/documents.py` | new | Chunk → Search document (dates, `metadata_json`); orphan calculation |
| `src/dti_rag/search/loader.py` | new | `make index ENV=…` |
| `src/dti_rag/search/manifest.py` | new | Read the manifest; decide whether a load is needed |
| `src/dti_rag/runinfo.py` | new | The model versions actually serving, from the Foundry resource |
| `src/dti_rag/clients.py` | changed | `search_client()`, `search_index_client()` with the pinned API version |
| `scripts/compare_filters.py` | new | The three-way demonstration |
| `scripts/experiments/integrated_vectorization.py` | new | Loading path 2; dev only; `--delete` cleans up |
| `scripts/smoke_test.py` | changed | Also prints the index manifest |
| `tests/unit/test_search_schema.py` | new | Types, filterability, vector size, date format, orphans, manifest logic |
| `pyproject.toml` | changed | `azure-search-documents`; `ops` extra (management SDK, blob) |
| `Makefile` | changed | `make index ENV=…` |

**Before running:** fill `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`,
`AZURE_FOUNDRY_ACCOUNT` and `AZURE_STORAGE_ACCOUNT` in `deploy/dev.env`.

## Project structure at the end of this lesson

```text
DTI-Policy-Helper/
├── artifacts/
│   ├── chunks.jsonl  ◇ generated
│   └── chunks.sha256  ◇ generated
├── data/
│   ├── fact_matrix/  (editions_fact_matrix.csv, fact_lookup_long.csv: convenience data)
│   ├── policy_documents/  (the 5 policy wording PDFs: authoritative)
│   └── question_answers/  (dti_rag_qa_bank.jsonl and .csv, README.md: ground truth for scoring)
├── deploy/
│   ├── dev.env  ◇ generated
│   └── environments.yaml
├── documentation/
│   ├── design/
│   │   ├── corpus_map.md
│   │   └── SCHEMA.md
│   └── lessons/  (this course)
├── infra/  (Terraform: modules/environment, shared, dev, test, prod)
├── scripts/
│   ├── experiments/
│   │   └── integrated_vectorization.py  ★ new
│   ├── build_corpus_map.py
│   ├── compare_filters.py  ★ new
│   └── smoke_test.py  ✎ changed
├── src/
│   └── dti_rag/
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── __main__.py
│       │   ├── chunk.py
│       │   └── parse.py
│       ├── search/
│       │   ├── __init__.py  ★ new
│       │   ├── documents.py  ★ new
│       │   ├── loader.py  ★ new
│       │   ├── manifest.py  ★ new
│       │   └── schema.py  ★ new
│       ├── __init__.py
│       ├── clients.py  ✎ changed
│       ├── config.py
│       ├── constants.py
│       ├── models.py
│       └── runinfo.py  ★ new
├── tests/
│   └── unit/
│       ├── test_chunking.py
│       ├── test_config.py
│       └── test_search_schema.py  ★ new
├── .gitignore
├── Makefile  ✎ changed
├── .pre-commit-config.yaml
├── pyproject.toml  ✎ changed
├── .python-version
└── README.md
```

`★ new` in this lesson · `✎ changed` in this lesson · `◇ generated` by running the code (git-ignored or produced by you) · unmarked: unchanged from earlier lessons

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Vector dimensions ≠ the embedding deployment's | Upload rejected, or garbage similarity |
| Dates as `Edm.String` | Range filters silently wrong |
| Forgetting the semantic configuration | Lesson 06 needs an index rebuild |
| Not checking per-document upload results | An index silently missing documents |
| Non-deterministic IDs | Duplicates on every re-run |
| Upsert without deleting orphans | Chunks from old chunking still retrievable |
| `status eq 'Current'` against stored `CURRENT` | Zero results, no error |
| Search identity missing its storage or OpenAI role | Indexer and vectorizer fail with unhelpful authorisation errors |
| Index built with the portal wizard | Exists in dev only; test and prod silently differ |
| Loader with a default environment | Someday it loads the wrong one |
| Rebuilding an index in place | Queries fail mid-rebuild, with no rollback. Version the name |

## Done when

Search Explorer (or `compare_filters.py`) returns the correct single-edition clause with a
metadata filter and cross-edition noise without one, and you can explain the score gap.
`make index ENV=dev` builds the index from nothing, a second run prints "Nothing to do", and
`make smoke ENV=dev` prints the manifest. The experiment's objects are deleted.

## Check yourself

1. Why does `effective_to` need boundary-semantics thought, and what's the rule here?
2. Why build the push loader first when integrated vectorization is less work?
3. What does the Text Split skill cost you on *this* corpus?
4. `merge_or_upload_documents` returned without raising. Why isn't that enough?
5. Which schema changes force a new index?
6. Unfiltered, the top five results are five editions of one clause within 0.002 of each
   other. What does that tell you, and what does it rule out as a fix?
7. Why is the index name versioned in code rather than set per environment?
8. You built a working indexer in dev with the Import wizard. What must happen before test
   and prod can have it?

---

**Next:** [Lesson 05 — The naive baseline, and watch it fail on purpose](../lesson05/README.md)
