# Lesson 04 — Build and load the Azure AI Search index

**Objective:** a searchable index with a vector field *and* filterable metadata, loaded two
different ways so you understand both.

**Deliverable:** a populated index, plus a notebook showing a vector query and the same
query with `edition_year eq 2024` returning different results.

---

## What the index has to support

Work backwards from Lessons 6 and 7. The retriever will need to:

- Search text with BM25 → `content` must be **searchable**
- Search vectors → `contentVector` with an HNSW profile
- Filter by loss date → `effective_from` / `effective_to` **filterable** and typed as dates
- Filter by "current" → `status` **filterable**
- Filter by named edition → `edition_year` **filterable**, `version` **filterable**
- Rerank semantically → a **semantic configuration**
- Return citations → `doc_id`, `section_id`, `page` **retrievable**

Every one of those is a schema decision you cannot change later without rebuilding. Azure AI
Search will not let you make an existing field filterable — you drop and recreate the index.
On a corpus this size that's two minutes, so it isn't fatal; on a real one it's an outage.
Get into the habit of thinking it through now.

---

## Field-by-field

| Field | Type | Attributes | Notes |
|---|---|---|---|
| `id` | `Edm.String` | key | Letters, digits, `_`, `-`, `=` only |
| `content` | `Edm.String` | searchable | BM25 target. English analyzer. |
| `contentVector` | `Collection(Edm.Single)` | searchable, vector | Dims **must** match your embedding deployment |
| `doc_id` | `Edm.String` | filterable, facetable, retrievable | The join key |
| `edition_year` | `Edm.Int32` | filterable, facetable, sortable | Int, not string — you want range queries |
| `version` | `Edm.String` | filterable, retrievable | String: `"1.1"` is not a float |
| `status` | `Edm.String` | filterable, facetable, retrievable | Case-sensitive in filters |
| `effective_from` | `Edm.DateTimeOffset` | filterable, sortable | **Not a string** |
| `effective_to` | `Edm.DateTimeOffset` | filterable, sortable | **Not a string** |
| `section_id` | `Edm.String` | filterable, retrievable | Meaningful only with `doc_id` |
| `section_title` | `Edm.String` | searchable, retrievable | Semantic config title field |
| `page` | `Edm.Int32` | retrievable | Human-verifiable citations |
| `supersedes` / `superseded_by` | `Edm.String` | retrievable | Change history |

### Three decisions worth dwelling on

**Vector dimensions are immutable.** `text-embedding-3-large` gives 3072. If you later use
the `dimensions` parameter to truncate to 1024 for cost, that's a **new index**. Decide now.
For this corpus, take the full 3072.

**`Edm.DateTimeOffset` needs ISO 8601 with an offset.** `"2024-01-01T00:00:00Z"`, not
`"1 January 2024"`. Your Lesson 3 metadata parser is where the conversion happens — this
field is why.

**Think about `effective_to` boundary semantics.** The 2023 v1.0 edition runs to
30 June 2023. Stored as `2023-06-30T00:00:00Z`, a filter of `effective_to ge 2023-06-30`
includes it, but a loss at 6pm on 30 June — `2023-06-30T18:00:00Z` — does **not** match
`effective_to ge <date>`. Either store `effective_to` as end-of-day
(`2023-06-30T23:59:59Z`) or normalise query dates to midnight. Pick one, write it in
`SCHEMA.md`, and test both boundary days in Lesson 7.

### Semantic configuration

Needed for Lesson 6's L2 reranker. Set `section_title` as the title field and `content` as
the content field. It costs nothing to configure now and requires an index rebuild if you
forget.

Two separate things have to exist for semantic ranking to work, and they live in different
places. The **billing plan** is a service setting you chose in the portal in Lesson 1
(Settings → Premium features → Standard). The **semantic configuration** is part of the
index, defined by your loader. You need both, in every environment. A missing plan fails in
that one environment only, which makes it look like a code bug.

---

## Two loading paths — do both, in this order

### 1. Push model first

Embed each chunk yourself with `text-embedding-3-large`, then upload with
`azure-search-documents`.

Do this **first** even though it's more work, because it forces you to confront exactly
what's in the index. You'll know the vector dimensions, the field names and the document
shape because you constructed every one. When retrieval misbehaves in Lesson 6, that
knowledge is what lets you debug it.

Practicalities:

- **Batch the embedding calls.** The API takes arrays. One call per chunk is slow and
  burns rate limit for no reason.
- **Batch the uploads**, respecting the ~1000-document / 16MB-per-request ceiling. You're
  well under it here, but write the batching anyway — it's the habit that matters.
- **Check the per-document results.** `upload_documents` returns a result per document and
  **partial failure is normal**: some succeed, some don't, and the call doesn't raise.
  Swallowing that gives you an index that's quietly missing the 2022 edition. Assert every
  result succeeded, loudly.
- **Make it idempotent.** `mergeOrUpload` with your deterministic Lesson 3 IDs means re-runs
  update rather than duplicate. You will re-run this many times.

### 2. Integrated vectorization second

Now build the managed path: a data source over blob storage, a **skillset** with a Text
Split skill and an **AzureOpenAIEmbedding** skill, an indexer, and a **vectorizer** attached
to the index's vector profile so you can send raw text at query time instead of embedding it
yourself.

This is the production path for most teams — it handles scheduling, change tracking and
scale without you writing a loader.

**Pin the API version:** integrated vectorization went GA in `2024-07-01`. Taking the SDK
default means your pipeline's behaviour can shift on a `pip install`.

**And here's the tension worth noticing:** the Text Split skill chunks by size, not by
section. Everything Lesson 3 taught you about section-aware chunking is lost if you hand the
whole PDF to the indexer. So the honest conclusion for *this* corpus is:

> Integrated vectorization is excellent when generic chunking is acceptable. Here it is not.
> Use the push model with your own section-aware chunks, and use the **vectorizer** part of
> integrated vectorization so query-time embedding is handled for you.

That's a real architectural judgement, arrived at by building both. Write it down — it
belongs in the Lesson 9 `FRAMEWORKS.md`.

A middle path worth trying if you have time: run the indexer over your pre-chunked
`chunks.jsonl` in blob storage (one JSON document per chunk), so you get managed
orchestration *and* your own chunk boundaries.

### Identity plumbing for integrated vectorization

The indexer reads blob storage, and the embedding skill and vectorizer call your `embed`
deployment. Both run **as the search service's managed identity**, not as you. That's why
Lesson 1 turned on the service's system-assigned identity and gave it *Storage Blob Data
Reader* on the storage account and *Cognitive Services OpenAI User* on the Foundry resource.
If you skipped that, the indexer fails with an authorisation error that names neither role.

- **Storage keys are off**, so the data source can't use an account-key connection string.
  Use the managed-identity form (`ResourceId=/subscriptions/…/storageAccounts/<name>;`).
- **The skill and vectorizer reference `embed` by deployment name**, which is identical in
  every environment. Only the Foundry endpoint differs, and that comes from
  `deploy/<env>.env`.
- **Uploading the corpus in dev:** Storage account → Storage browser → Blob containers →
  `corpus` → Upload. This works because Lesson 1 gave you *Storage Blob Data Contributor* in
  dev. In test and prod the pipeline uploads it. You have no data role there, and that's
  deliberate.

**The portal's Import wizard is fine for *seeing* integrated vectorization in dev.** It
builds a data source, skillset, indexer and index in a couple of minutes. But whatever it
builds exists in dev only. Test and prod get their index from your loader, so copy the
definitions the wizard produced (each object has a JSON view) into code, and then delete the
wizard's objects. An index that exists because someone clicked a wizard in one environment
is drift on day one.

---

## One loader, three environments

**You built the search *service* in the portal; your code owns everything *inside* it.** The
index, its schema, the semantic configuration, indexers, skillsets and documents are all
created by `make index ENV=<env>`, and by nothing else. In dev you run it. In test and prod
the pipeline runs it (Lesson 13), as that environment's pipeline identity.

Design the loader for that from the start:

- **Take the environment from settings, never a default.** It reads `deploy/<env>.env` like
  everything else, and it refuses to run if `APP_ENV` is unset. A loader that silently
  defaults to an environment will one day default to the wrong one.
- **Version the index name in code.** Use `dti-policy-v<SCHEMA_VERSION>`, with `SCHEMA_VERSION`
  defined next to the schema. A schema change bumps it, so the new index is built *alongside*
  the old one, and the app version that expects it is deployed afterwards. Rollback is
  redeploying the previous app version, whose index still exists. The name is the same in
  every environment, so it isn't environment config. Delete old versions once nothing
  points at them.
- **Upsert doesn't delete.** `mergeOrUpload` is idempotent for chunks that still exist. A
  chunk that disappears after you change the chunking (and you will, in Lesson 11) stays in
  the index for good, still retrievable. After uploading, the loader deletes any document
  ID that isn't in the artefact.
- **Write a manifest.** After a successful load, record the schema version, the
  `chunks.jsonl` SHA-256 (Lesson 3), the embedding deployment's model version, and the load
  time. Put it in the environment's storage account or a small manifest index. The smoke
  test and the Lesson 10 scorecards read it. "Which corpus, embedded by which model, is prod
  serving?" then has an answer that doesn't depend on memory.
- **Each environment embeds with its own deployment.** Never copy vectors between
  environments. The model and version are pinned identically everywhere (Lesson 1), so the
  vectors are equivalent. Re-embedding a few hundred chunks costs pennies, and it keeps each
  environment self-contained: prod never depends on anything in dev.

---

## The deliverable that proves it works

A notebook running the same query three ways:

1. Pure vector query, no filter → expect cross-edition noise: near-identical 3.4 clauses
   from several editions, in essentially arbitrary order.
2. Same query with `edition_year eq 2024` → expect only 2024 chunks.
3. Same query with a date filter `effective_from le 2024-03-15T00:00:00Z and effective_to ge
   2024-03-15T00:00:00Z` → expect only the 2024 edition.

**Look at result #1 properly.** Note the score gaps between the five near-identical clauses.
They'll be tiny — often in the third decimal place. That's the visceral demonstration of the
Lesson 2 argument: the ranking between editions is noise, and no reranker fixes noise.
Screenshot it; it's the best slide in your capstone presentation.

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Vector dims ≠ embedding deployment dims | Upload rejected, or garbage similarity |
| Dates as `Edm.String` | Range filters silently wrong |
| Forgetting the semantic config | Lesson 6 needs an index rebuild |
| Free-tier Search service | No managed identity for indexers; one per subscription, so no dev/test/prod |
| Not checking per-document upload results | Silently missing documents |
| Non-deterministic IDs | Duplicates on every re-run |
| `.` in the key field | Upload rejected |
| Unpinned Search API version | Behaviour changes under you |
| `status eq 'Current'` vs stored `CURRENT` | Zero results, no error |
| Search identity missing its storage or OpenAI role | Indexer fails with an unhelpful authorisation error |
| Index or indexer built with the portal wizard | Exists in dev only; test and prod silently differ |
| Upsert without deleting orphans | Chunks from old chunking still retrievable |
| Loader with a default environment | Someday it loads the wrong one |
| Rebuilding an index in place | Queries fail mid-rebuild; no rollback. Version the name instead |

---

## Done when

Search Explorer returns the correct single-edition clause when you add a metadata filter,
and cross-edition noise when you don't — and you can explain the score gap in the unfiltered
case.

And: `make index ENV=dev` builds the index from nothing, a second run changes nothing, and
the manifest records which `chunks.jsonl` and which embedding model version it holds.

## Check yourself

1. Why does `effective_to` need boundary-semantics thought, and what's your rule?
2. Why build the push loader first when integrated vectorization is less work?
3. What does the Text Split skill cost you on *this* corpus?
4. `upload_documents` returned without raising. Why isn't that sufficient?
5. Which schema changes force an index rebuild?
6. In the unfiltered vector query, the top five results are five editions of the same
   clause with scores within 0.002 of each other. What does that tell you, and what does it
   rule out as a fix?
7. Why is the index name versioned in code rather than set per environment in config?
8. You built a working indexer in dev with the portal's Import wizard. What has to happen
   before test and prod can have it?

---

**Next:** [Lesson 05 — Baseline pipeline, and watch it fail on purpose](Lesson05.md)
