# Observability

Traces go to each environment's own Application Insights. The audit log is a separate store (blob, `audit/<trace_id>.json`), described in `src/dti_rag/observability/audit.py`.

| | Traces | Audit log |
|---|---|---|
| Purpose | Operations: what's slow, what's failing | Accountability: why was the customer told £300? |
| Completeness | Sampled in prod (`TRACE_SAMPLING_RATIO`) | Every answer; the API fails closed without it |
| Retention | Short (Log Analytics) | Complaint-handling timeframe (blob lifecycle rule) |
| Personal data | Question text never attached to spans | Redacted before writing |

## Spans

`chat` (per request) → `route` → `retrieve` → `generate` → `guardrail_check`. Custom spans land in the `dependencies` table; attributes are in `customDimensions`.

| Attribute | On span | Why |
|---|---|---|
| `dti.mode` | route, guardrail_check | Mode distribution is a health signal |
| `dti.editions`, `dti.governing_editions` | route, guardrail_check | Which editions are asked about |
| `dti.filters` | retrieve | Debugging a wrong answer starts with the filter |
| `dti.chunks_retrieved`, `dti.top_score` | retrieve | Retrieval quality proxy |
| `gen_ai.usage.input_tokens` / `output_tokens` | route, generate | Cost attribution |
| `dti.guardrail_status` | guardrail_check | Groundedness and block rate over time |
| `dti.trace_id` | chat | Ties the trace to the API response and the audit record |
| `dti.prompt_version` | generate | Which prompt produced it |

## Workbook queries

Build the workbook once, in dev. Then copy its JSON (the workbook's **Advanced editor**) into `deploy/workbook.json` and import it into test and prod. Three hand-built dashboards drift like three hand-built environments.

**Latency by stage (p50 / p95):**

```kusto
dependencies
| where timestamp > ago(1d) and name in ("route", "retrieve", "generate", "guardrail_check")
| summarize p50 = percentile(duration, 50), p95 = percentile(duration, 95), calls = count() by name
| order by p95 desc
```

**Tokens per request, and per day:**

```kusto
dependencies
| where timestamp > ago(7d) and name in ("route", "generate")
| extend input = toint(customDimensions["gen_ai.usage.input_tokens"]),
         output = toint(customDimensions["gen_ai.usage.output_tokens"])
| summarize input = sum(input), output = sum(output) by operation_Id, bin(timestamp, 1d)
| summarize avg_input = avg(input), avg_output = avg(output), requests = count() by timestamp
```

**Guardrail outcomes (groundedness and block rate):**

```kusto
dependencies
| where timestamp > ago(7d) and name == "guardrail_check"
| summarize count() by status = tostring(customDimensions["dti.guardrail_status"]), bin(timestamp, 1h)
| render timechart
```

**Mode distribution (a spike in abstentions = retrieval broke, or the question mix changed):**

```kusto
dependencies
| where timestamp > ago(7d) and name == "guardrail_check"
| summarize count() by mode = tostring(customDimensions["dti.mode"]), bin(timestamp, 1h)
| render timechart
```

## Alerts

**Portal:** App Insights → **Alerts** → **Create** → **Alert rule** → Custom log search. Record each rule's threshold in the table below. Alert rules aren't in Terraform yet (`infra/README.md`): once the thresholds settle, they belong there.

| Alert | Query (above) | Condition | prod | test | dev |
|---|---|---|---|---|---|
| Guardrail blocks | Guardrail outcomes, `status == "blocked"` | > ____ per hour | ✔ | — | — |
| Abstention spike | Mode distribution, `mode == "abstain"` share | > ____ % over 1 h | ✔ | — | — |
| p95 latency | Latency by stage, `name == "generate"` | > ____ s | ✔ | — | — |
| 5xx rate | `requests | where resultCode startswith "5"` | > ____ % | ✔ | ✔ | — |
| 429 rate | `dependencies | where resultCode == "429"` | > ____ per 5 min | ✔ | ✔ | — |
