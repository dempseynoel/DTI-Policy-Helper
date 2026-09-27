# Lesson 08 — Grounded generation: citations, conflicts, multi-hop, cross-references

**Objective:** turn correct retrieval into correct, cited, honest answers — including the
cases where good retrieval still produces wrong answers.

**Deliverable:** `generate(query, chunks, mode)` producing a cited answer or an abstention.

---

## The premise shift

Lessons 5–7 were about getting the right text. This lesson assumes you have it and asks a
different question: **given the right context, what still goes wrong?**

Quite a lot, and the failures are more interesting:

- The model does arithmetic by mixing facts from two editions.
- It stops at the first relevant-looking chunk instead of following an explicit cross-reference.
- It trusts a summary that's incomplete.
- It quotes "£350" when the retrieved text says "£300" — a transcription error inside an
  otherwise correct answer.
- It asserts cover for a section marked Reserved because a table said so.

These are reasoning and instruction-following failures. Prompt design handles some; the rest
need structural fixes in code.

---

## Prompt rules (encoding the Lesson 2 policies)

Your system prompt encodes the three policies. Rules that matter, and why:

**Answer only from retrieved context; abstain if insufficient.** Standard, necessary, not
sufficient on its own.

**Cite `doc_id` + `section_id` + effective range for every figure.** Not a footnote — the
thing that makes the answer auditable. A handler must be able to open the PDF and check.
Requiring a citation *per figure* also makes the multi-edition contamination in DTI-015
visible: if two figures cite different `doc_id`s in an answer that should use one edition,
that's detectable in code.

**Quote figures exactly.** `must_include` / `must_not_include` are exact substring checks.
"£300" and "300 pounds" and "£300.00" are not the same string. Beyond eval mechanics, an
insurance answer that paraphrases a monetary figure is a bad answer.

**Wording overrides tables.** Never assert cover for a Reserved section regardless of what
any table says. This is DTI-014 and it needs to be explicit and emphatic — the model has no
reason to privilege one source over another unless you tell it.

**For ambiguous queries, present both editions with date ranges.** Never collapse to one
value, even a correct one.

**Never introduce a figure or section number not in the context.** Stated in the prompt
here, *enforced in code* in Lesson 11. Both, and know which is which.

### Prompt engineering notes

Version your prompts as constants in `prompts.py`. When Lesson 10's scorecard moves, you
need to know which prompt produced which score — and a prompt change is a deploy that needs
the same rigour as a code change.

Different prompts per mode. An abstention doesn't need citation rules; it needs "explain
what you can't answer and why, and cite the nearest relevant clause." One prompt with
branching instructions is harder to test than three prompts.

Put the context **after** the instructions and delimit each chunk with its metadata:

```
[DTI-HOME-PW-2024-v1.0 | §3.4 | in force 1 Jan 2024 – 31 Dec 2024 | p.5]
The standard excess for an escape of water claim is £300. …
```

That header is what makes per-figure citation possible and cross-edition contamination
visible. Without it the model has a wall of text and no way to attribute anything.

---

## The reasoning traps

### Multi-hop numeric (DTI-015, 016, 017)

**DTI-015:** *"One storm caused two items of damage 80 hours apart. How many excesses in
2024, and in 2025?"*

Correct: 2024's window is 72 hours → 80 falls outside → two claims → 2 × £300 = £600. 2025's
window is 96 hours → 80 falls inside → one claim → £350.

The classic failure is **cross-edition contamination**: applying 2025's 96-hour window to
2024's £300 excess. Both numbers are in context, both are correct facts, and the combination
is wrong.

The structural fix: **tag each retrieved fact with its `doc_id` and refuse to combine
mismatched editions.** Don't rely on the prompt alone. Options worth weighing:

- Run **one generation pass per edition** with only that edition's chunks, then combine the
  two grounded answers. Contamination becomes *impossible* rather than discouraged.
- Or one pass with strict per-figure citation, then a post-check that flags an arithmetic
  step whose inputs cite different `doc_id`s.

The first is more robust and costs an extra call. On a question class where the wrong answer
is a mis-statement of cover, take the robust one.

**DTI-016** is different — it's *intra*-edition and tests specificity:

> Wet-room leak, £4,000 damage, £1,200 trace-and-access. Current wording. What's paid?

£1,200 is within the £10,000 trace limit → gross £5,200. The escape originated **from a wet
room**, so £600 applies, not the £350 standard → **£4,600**.

The expected wrong answer is £4,850 (deducting £350). Two general-purpose lessons here:
**the more specific rule beats the more general one**, and both excesses are in the same
retrieved chunk, so this isn't retrieval — it's reading comprehension. State the
specific-over-general rule explicitly in the prompt.

**DTI-017** tests exclusion precedence: an 18-day leak under 2023 v1.1 (14-day bar) is
excluded; under 2024 (21-day bar) it's payable. Section 9.7 says general exclusions override
cover grants — the model must apply Section 9 *after* Section 3, not treat them as peers.

### Cross-reference following (DTI-018, 019)

**The top-ranked chunk is often not the answer.**

**DTI-018:** ceiling collapsed because a loft pipe burst. Section 7.2 is the strongest hit
for "ceiling" — and 7.2 says:

> "Where a ceiling collapse was caused by escaping water, the claim is assessed under
> **Section 3** instead, and the escape of water excess and conditions apply."

The retrieved chunk is a **signpost**, not an answer. Correct: Section 3, £350 (or £600 wet
room), not the £200 accidental damage excess.

**DTI-019:** lightning caused a power surge, no fire. "Lightning" is lexically strongest in
Section 5, and 5.1 says: "A lightning strike causing only a power surge, with no fire, is
covered under **Section 4**."

Both need the same mechanism: **detect the signpost, retrieve the referenced section, then
generate.**

Implementation options:

| Approach | Pros | Cons |
|---|---|---|
| Regex for "under Section N" / "assessed under Section N" | Deterministic, cheap, testable | Brittle to phrasing |
| LLM decides whether a follow-up retrieval is needed | Handles any phrasing | Non-deterministic, extra call |
| Agentic loop (Lesson 9) | Most general | Most complex, hardest to audit |

Start with the regex. The wording is formulaic and consistent — it's a drafted legal
document, not free prose — so a narrow pattern gets high precision. Note where it's brittle
and revisit in Lesson 9.

The follow-up retrieval **must stay within the same edition**. `doc_id eq <same>` and
`section_id eq '3'`. A cross-reference is internal to a document.

### The incomplete summary (DTI-022)

Covered properly in Lesson 9, but the generation-side rule starts here: **a summary chunk is
evidence, not authority.** If the question is "what changed", the answer comes from
comparing the wording, with the summary as corroboration.

---

## Citations as a data structure

Return citations as **structured data**, not prose:

```
Citation: doc_id, section_id, effective_from, effective_to, page, quoted_text
```

Because Lesson 10's `edition_correct` evaluator needs to check cited `doc_id` against
`gold_doc_ids`; Lesson 11's grounding check needs to verify each figure against
`quoted_text`; Lesson 12's UI renders them as links; Lesson 13 logs them for audit. Prose
citations mean regex-parsing your own output in four places.

Have the model emit structured output (JSON / tool-calling) rather than parsing prose. Then
**validate that every cited `doc_id` and `section_id` actually exists in the chunks you
passed in.** A model can cite a plausible-looking section that wasn't retrieved, and that's
a fabricated citation — exactly the failure that gets financial-services teams in trouble.

---

## Abstention generation

`mode == "abstain"` gets its own prompt and its own quality bar. DTI-025's reference answer
declines *and* cites Section 6.5 *and* says what cover would be needed. Aim for:

1. State plainly what can't be answered, and why.
2. Cite the nearest relevant clause if one exists.
3. Say what would be needed (a different policy, a loss date, an edition not held).
4. Don't apologise at length, and don't hedge toward an answer anyway.

---

## Environments

**Prompts are code, and they're promoted like code.** Keep them as versioned constants in
`prompts.py`. They ship inside the container image, and the same image is promoted through
dev → test → prod (Lesson 13). Nobody edits a prompt in a running environment: not through
the portal, and not through a "hot-swappable" app setting someone adds later because
redeploying felt slow. If you ever move prompts out of the image, give them a version, and
promote and log that version exactly like an image digest. Otherwise "the prompt that
passed the gate in test" and "the prompt prod is using" can quietly be two different
strings.

**The content filter on the `chat` deployment is a behavioural setting, so it must match.**
It's configured per deployment in the Foundry portal (Lesson 1, step 6), and insurance
wording about fire, theft and injury is exactly the kind of text a filter can react to. A
stricter filter in prod than in test means prod can block an answer the gate passed. Record
the filter in `ENVIRONMENTS.md`, keep it identical everywhere, and Lesson 13's `check_env`
verifies it.

**Record the prompt version with every answer** (Lesson 13's audit log). "Why did it say
that?" needs the prompt, the model version and the environment, not just the text.

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Combining facts across editions | DTI-015 wrong, confidently |
| Prose citations | Four downstream parsers |
| Not validating cited IDs against retrieved chunks | Fabricated citations |
| Stopping at the top-ranked chunk | DTI-018/019 wrong |
| Follow-up retrieval crossing editions | Contamination via the back door |
| Paraphrasing figures | `must_include` fails on a correct answer |
| One prompt for all three modes | Untestable, and abstentions hedge |
| Trusting the 2025 change summary | Four missing changes |
| Applying Section 9 as a peer of Section 3 | DTI-017 exclusion precedence wrong |
| Prompt rules without code enforcement | Works until it doesn't, silently |
| Prompt edited outside the image | Prod runs a prompt the gate never saw |
| Different content filters in test and prod | Prod blocks answers test passed |

---

## Done when

- DTI-016 returns **£4,600** (wet-room excess chosen over standard)
- DTI-018 routes to **Section 3** with **£350**
- DTI-014 says **"Reserved / not offered before 2024"**
- DTI-015 gives 2×£300 for 2024 and 1×£350 for 2025, with no cross-contamination
- Every figure in every answer carries a citation that resolves to a real retrieved chunk

## Check yourself

1. Why does DTI-015 need per-edition passes rather than a prompt rule?
2. DTI-016's facts are all in one edition and one chunk. Why is it still hard?
3. What makes 7.2 a signpost rather than an answer, and how do you detect that in code?
4. Why must follow-up retrieval be constrained to the same `doc_id`?
5. Why structured citations rather than prose — name three downstream consumers.
6. Which rules here are prompt-enforced and which need code? Which are both, and why?

---

**Next:** [Lesson 09 — Orchestration with LlamaIndex and LangGraph](Lesson09.md)
