# Cost report – team `bcellaj`

**Subscription:** Azure for Students (integration subscription owned by Apiramy Jeyaharan)
**Resource group:** `rg-projet-bcellaj` – region `francecentral` – tags `projet=dscc`, `equipe=bcellaj`
**Envelope:** $25 maximum · **Budget:** `budget-bcellaj`, $25, alerts at 20 % ($5), 50 % ($12.50), 80 % ($20) – see `budget.png`

## 1. Initial estimate (15 days)

| Service | Configuration | Free grant used | Estimate |
|---|---|---|---|
| Functions (Flex Consumption) | 1 app, 512 MB, 3 functions | 250,000 executions + 100,000 GB-s / month | $0.00 |
| Container Apps (Consumption) | 0.25 vCPU / 0.5 GiB, **min 0 replicas** | 180,000 vCPU-s + 360,000 GiB-s + 2 M requests / month | $0.00 |
| Event Grid | system topic, 1 subscription | 100,000 operations / month | $0.00 |
| Storage (blob, queues, `$web`) | Standard LRS, a few MB, a few thousand transactions | – | < $0.20 |
| Cosmos DB | **Free Tier**, 400 RU/s shared | 1,000 RU/s + 25 GB | $0.00 |
| Log Analytics + Application Insights | **daily cap 0.2 GB** | 5 GB ingestion / month | $0.00 |
| Log alert (every 15 min) | 1 rule | – | < $0.50 |
| GitHub Actions + GHCR | public repository | free | $0.00 |
| ACR | **not used** (GHCR instead) | – | $0.00 |
| **Total** | | | **≈ $0 – $1** |

## 2. Actual cost on D15

Source: Cost Management → **Cost analysis**, scope = subscription, **filter tag `projet = dscc`**, period = project dates. Screenshot: `cost_analysis_d15.png`.

| Service | Actual cost |
|---|---|
| _fill in from Cost analysis (group by service name)_ | _$_ |
| | |
| **Total** | **$ _____** |

## 3. Gap between estimate and actual

| | |
|---|---|
| Estimate | ≈ $0 – $1 |
| Actual | $ _____ |
| Gap | $ _____ |

Explanation (adapt to the real numbers):
- Most services stayed within their monthly free grants (Functions, Container Apps at 0 replicas when idle, Event Grid, Cosmos DB Free Tier, App Insights below 5 GB).
- The small amounts come from: storage transactions and capacity (the Flex Consumption deployment package is also stored in the account), the log alert rule (billed per rule and per evaluation frequency), and Log Analytics ingestion if any.
- Cost Management data can lag by 24–48 h, so the D15 figure may slightly under-report the last day.

## 4. Proof of deletion (after the defence)

```bash
az group delete -n rg-projet-bcellaj --yes
az group exists -n rg-projet-bcellaj                 # -> false            (cleanup_group_exists.png)
az group list -o table                               # no rg-projet-bcellaj, no DefaultResourceGroup-*   (cleanup_group_list.png)
```

Also delete, outside the resource group:
- the budget `budget-bcellaj` is scoped to the group and disappears with it;
- the GitHub secrets and the `production` environment (optional, no cost);
- the GHCR package (optional, free).

Deletion date: _dd/mm/2026_ (must be within 48 h after the defence).
