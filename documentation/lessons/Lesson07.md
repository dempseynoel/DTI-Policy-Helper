# Lesson 07 — The query-understanding layer (dates, freshness, ambiguity, abstention)

**Objective:** decide *what filter to apply and what mode to answer in* — before retrieving.

**Deliverable:** `route(query) → {filter, mode, notes}`, unit-tested against the ambiguity,
freshness and abstention questions.

---

## Why routing is the highest-leverage layer

Lesson 6 gave you a retriever that returns exactly the right chunks — **if** you hand it the
right filter. So far you've been handing it filters by hand. In production nobody does that.

And notice the failure mode this creates: a perfect retriever with a wrong filter returns
perfectly-retrieved, perfectly-ranked, **wrong-edition** results, with high confidence and
no error. Everything downstream then works correctly on the wrong premise.

> **Filters only help if you set them correctly.** The router is where correctness is
> decided; everything after it is execution.

There's a second job here too, and it's the one that separates this from a demo: deciding
**whether to answer at all**. Not every question should get an answer. Some need a clarifying
question back; some need a refusal. Building that as a first-class decision — rather than
hoping the generator hedges — is what makes the system safe to put in front of a claims
handler.

---

## Three modes

| Mode | When | Response shape |
|---|---|---|
| `answer` | Exactly one edition is in scope | Cited answer from that edition |
| `ask` | Genuinely ambiguous | Request the loss date, **or** return both with ranges |
| `abstain` | Out of corpus or out of scope | Explain why, cite the nearest relevant clause |

Making mode explicit means Lesson 10 can score it directly: `ambiguous == true` items must
route to `ask`, `answerable == false` items must route to `abstain`. Behaviour becomes
measurable instead of hoped-for.

---

## What the router extracts

### 1. A loss date

> "flooded on **15 March 2024**", "discovered on **3 May 2023**", "a claim arose on
> **1 February 2025**"

→ date-range filter. This is the highest-value extraction: it resolves DTI-004, 005, 006,
007, and it's the only thing that resolves the 2023 v1.0/v1.1 split.

Watch for dates that **aren't** loss dates. "A leak had been running for 18 days" (DTI-017)
is a duration, not a date. "80 hours apart" (DTI-015) is an interval. Extracting those as
dates produces a filter matching nothing.

### 2. A named edition or year

> "Under the **2024 edition**", "In the **2022 wording**", "the **second 2023 edition**"

→ edition filter. Note "the second 2023 edition" means v1.1 — worth handling, since DTI-017
phrases it that way.

**If a bare year maps to two editions (2023 only), flag ambiguous.**

### 3. Out-of-corpus or out-of-scope signals

> "the **2021 edition**, DTI-HOME-PW-2021-v1.0" → out of corpus
> "does it cover my **car**" → out of scope

→ `abstain`.

### 4. Nothing temporal at all

> "What is the standard excess on a HomeShield policy?"

→ **freshness default**: `status eq 'CURRENT'`, *and* a note instructing generation to add
"earlier editions differ". The caveat is part of the correct answer — DTI-010's
`expected_behaviour` says so explicitly.

---

## The design decision: LLM vs rules

You need both, and the split matters more than either.

```
        LLM (fuzzy, unbounded input)          Deterministic (exact, testable)
        ────────────────────────────          ──────────────────────────────
        "flooded on 15 March 2024"    ──►     date(2024, 3, 15)
                                                       │
                                                       ▼
                                              editions.resolve(date)
                                                       │
                                                       ▼
                                              DateRangeFilter(...)
```

**LLM tool-calling handles extraction.** Natural language is unbounded; you cannot regex
your way to every phrasing of a date, and you shouldn't try.

**Pure deterministic code handles resolution.** Given a date, *which edition governs* is a
lookup against the fact matrix. It has exactly one right answer, it must be identical every
time, and it must be unit-testable without a network call.

Putting resolution in the LLM is the mistake to avoid. Ask a model "which edition covers
15 March 2024?" and it'll usually be right — and occasionally, non-deterministically,
wrong, in a way no test catches and no log explains.

> **Rule of thumb worth carrying beyond this project:** use the LLM to turn language into
> structure. Use code to turn structure into decisions. The moment a decision has exactly one
> defensible answer, it belongs in code.

`src/dti_rag/query/editions.py` is that deterministic core:

- `resolve_by_date(date) → Edition` — exactly one, or raise
- `resolve_by_year(year) → list[Edition]` — 2023 returns two
- `current() → Edition`
- `is_ambiguous(editions) → bool`

Pure functions over the fact matrix. No LLM, no I/O, fully tested offline.

---

## Handling each behaviour

### Ambiguity (DTI-008, 009)

"What was the pedal cycle theft limit in 2023?" → `resolve_by_year(2023)` returns two
editions with different values → `ask`.

The response either requests the loss date or returns **both** with effective ranges.
DTI-008's `must_include` is `["£500", "£600", "v1.0", "v1.1"]` — the *ranges* are part of a
correct answer, not decoration.

**Subtlety worth getting right:** two editions in scope isn't automatically ambiguous. For
DTI-006 (burglary on 3 May 2023) the date resolves to exactly one edition anyway. And even
where two editions *are* in scope, if they agree on the fact there's nothing to disambiguate
— police notification is 24 hours in both 2023 editions.

So ambiguity is properly: **multiple editions in scope AND they disagree on the fact being
asked about.** You can't fully determine that before retrieval — which means either a
conservative pre-retrieval flag confirmed after retrieval, or a post-retrieval check. Decide
which, and write down why. This is the most interesting design question in the lesson.

### Freshness default (DTI-010, 011)

No date, no edition → `status eq 'CURRENT'` plus a note that earlier editions differ.

The note has to survive into generation. Return it in `notes` and have Lesson 8's prompt
consume it. An answer of "£350" with no caveat is scored as a partial failure.

### Abstention (DTI-024, 025)

Two different kinds:

**Out of corpus** — a document that exists but isn't held. "2021 edition" is the case, and
it's dangerous precisely because retrieval *succeeds*: `DTI-HOME-PW-2021-v1.0` appears
verbatim in the 2022 control page as the `supersedes` value. Strong hit, no answer in it.

The router can catch this cheaply: a named edition that doesn't resolve to a held document →
`abstain`. **Deterministic, no LLM judgement required.** That's a satisfying result — the
scariest failure in the corpus is caught by a set-membership check.

**Out of scope** — a subject the wording doesn't cover. "Does it cover my car?" Harder,
genuinely needs the LLM, and the right answer isn't a flat refusal: DTI-025 wants Section
6.5 cited (money in a vehicle) *while* declining. "I can't answer that" scores worse than
"the wording doesn't cover vehicles; the only related clause is 6.5, which excludes money
left in a vehicle."

**Be careful not to over-abstain.** Lesson 10 scores both directions. A router that abstains
whenever it's unsure will pass DTI-024/025 and fail half the bank. Abstention is a decision,
not a fallback.

---

## Defining the tool schema

The LLM extraction step works best as tool-calling with a strict schema:

```
loss_date            date | null      ISO. Only an actual date of loss.
named_edition_year   int | null       A year the user explicitly named.
named_version        string | null    "1.1" / "second 2023 edition".
referenced_doc_id    string | null    An explicit document reference.
scope                enum             home_policy | other_insurance | unrelated
```

Design notes:

- **Every field nullable, defaulting to null.** The cost of a spurious extraction (a filter
  matching nothing) is higher than a missed one (falls through to the freshness default).
- **Don't ask the LLM for the filter.** Ask for facts; build the filter in code.
- **Don't ask it "is this ambiguous?"** Ambiguity is derivable from the extraction plus the
  edition table. Deriving it is testable; asking is not.
- **Validate everything before it reaches a filter.** Dates parse to real dates, years are
  ints in the known set. This is the OData-injection boundary from Lesson 6 — the router is
  where untrusted text becomes typed values, so it's where validation belongs.

---

## Where this sits, and the trap to avoid

The router runs **before** retrieval, and it must not retrieve. It's tempting to peek at the
index to decide — resist it for now; the seam is what makes both layers testable, and
Lesson 9's LangGraph version depends on route being a discrete node.

(Lesson 9 revisits this: a graph can loop back and re-route after retrieval, which is the
principled way to handle the post-retrieval ambiguity check. Note it now, build it there.)

---

## Environments

Nothing in the router knows which environment it's in, and that's the point. `route()` and
`editions.py` are pure. `APP_ENV` must never appear in the `query/` package. If you catch
yourself wanting it there, something that should be data has become behaviour.

What *does* vary is the model behind the extraction step, and that is why Lesson 1 pins the
`chat` model version identically in every environment. **Tool-calling behaviour is a
property of the model version.** A new version can extract "3 May 2023" differently, or
start filling a field it used to leave null. So a model upgrade is a *router change*: it
goes dev → test → prod behind the eval gate, like a code change. The router's LLM-backed
tests run in test against the same model version prod uses.

The deterministic core (`editions.py`, filter construction, ambiguity derivation) doesn't
touch a model, so its unit tests run anywhere, offline. That split is the one this lesson
argues for, and it makes the environment question easy.

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Asking the LLM which edition governs | Non-deterministic, untestable, occasionally wrong |
| Extracting durations as dates | Filter matches nothing |
| Treating "two editions in scope" as ambiguous | DTI-006 wrongly asks instead of answering |
| Losing the freshness caveat before generation | DTI-010 partial failure |
| Over-abstaining when unsure | Passes 2 questions, fails many |
| Flat refusal without citing a clause | DTI-025 wants 6.5 cited |
| Unvalidated extraction into a filter string | OData injection |
| Router touching the index | Untestable, and Lesson 9's graph has no clean node |
| Upgrading the `chat` model in one environment "just to try it" | Extraction behaviour differs between test and prod; the gate proves nothing |

---

## Done when

- DTI-008 returns "ambiguous — need the loss date" (or both values with ranges)
- DTI-010 defaults to £350 **and** notes earlier editions differ
- DTI-024 and DTI-025 route to `abstain`
- DTI-006 routes to `answer` despite two 2023 editions existing
- `tests/unit/test_editions.py` covers 30 June and 1 July 2023 explicitly

## Check yourself

1. Why does date→edition resolution belong in code rather than the LLM?
2. Two editions are in scope. Is that ambiguous? What else do you need to know?
3. How does the router catch DTI-024 *without* LLM judgement?
4. Why is a flat refusal the wrong answer to DTI-025?
5. What's the cost asymmetry between a spurious extraction and a missed one, and how does
   that shape the tool schema?
6. Where does untrusted text become typed values, and why does that location matter for
   security?

---

**Next:** [Lesson 08 — Grounded generation](Lesson08.md)
