# KQL queries – Application Insights (`appi-bcellaj`)

Run in: Azure portal → `appi-bcellaj` → Monitoring → **Logs** (KQL mode).
Data sources: the worker function logs one line per inference
(`worker: <file> -> <prediction> (<confidence>) in <duration> ms`), and both the API
(FastAPI, OpenTelemetry) and the Function App log their HTTP requests in `requests`.

---

## 1. Inferences per hour

```kusto
traces
| where timestamp > ago(7d)
| where message startswith "worker: " and message has " -> "
| summarize inferences = count() by bin(timestamp, 1h)
| render columnchart
```

Screenshot: `docs/kql_1_inferences_per_hour.png`

---

## 2. The 5 slowest files (end-to-end pipeline time)

```kusto
traces
| where timestamp > ago(7d)
| where message startswith "worker: " and message has " -> "
| parse message with "worker: " file " -> " prediction " (" confidence ") in " duration_ms:real " ms"
| top 5 by duration_ms desc
| project timestamp, file, prediction, confidence, duration_ms
```

Screenshot: `docs/kql_2_slowest_files.png`

---

## 3. Distribution of HTTP codes (API and Function App)

```kusto
requests
| where timestamp > ago(7d)
| summarize calls = count() by resultCode, cloud_RoleName
| order by calls desc
| render piechart
```

Screenshot: `docs/kql_3_http_codes.png`

---

## Bonus – custom metrics sent by the code (OpenTelemetry)

```kusto
customMetrics
| where timestamp > ago(7d)
| where name in ("inferences_total", "model_latency_ms", "pipeline_inferences_total", "pipeline_duration_ms", "pipeline_errors_total", "prediction_errors_total")
| summarize total = sum(valueSum), avg_value = sum(valueSum) / sum(valueCount) by name, cloud_RoleName
```
