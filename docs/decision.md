# IMD-60352 — Decision Document (DRAFT)

**Status:** _to be filled after Week 3 benchmark run_
**Author:** Ilya Sudakov
**Jira:** [IMD-60352](https://improvado.atlassian.net/browse/IMD-60352)

---

## TL;DR

> **Decision:** _SHIP / ITERATE / ABORT_
>
> One paragraph: did `lineage-svc` strictly beat Marquez on all 9 performance
> metrics under identical 10x synthetic load? If yes — ship dual-write to prod.
> If partially — list which targets missed and how far. If no — abort.

## Comparative results

Run conditions: 10x prod load, identical fixture (5M edges, power-law, depth ~8),
matched resource caps (app 2 CPU / 2G, Postgres 4 CPU / 4G). Each scenario run
for its full duration; numbers below are p95/p99 across the steady-state window.

| # | Metric | Target | Marquez (local 10x) | lineage-svc | Δ | Pass? |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Write throughput sustained | ≥ 300 events/s, zero backlog |     |     |     |     |
| 2 | Write p95 latency | < 50 ms |     |     |     |     |
| 3 | Read p95 `direct` | < 50 ms |     |     |     |     |
| 4 | Read p95 depth=3 | < 100 ms |     |     |     |     |
| 5 | Read p95 depth=10 | < 500 ms |     |     |     |     |
| 6 | Read p99 depth=10 | < 2,000 ms |     |     |     |     |
| 7 | Postgres CPU under 10x | < 50% |     |     |     |     |
| 8 | Sequential scans on edge table | 0 |     |     |     |     |
| 9 | 5xx error rate | < 0.1% |     |     |     |     |

## Side-by-side dashboards

_Embed screenshots of the Grafana dashboard `lineage-vs-marquez` for each
scenario. One per row, before/after style:_

- Write p95 over time
- Read direct p95 over time
- Read depth=10 p99 over time
- Postgres commits/s (proxy for write throughput)
- Sequential scans on `lineage_edge`
- k6 error rate

## Correctness

Diff harness (`benchmark/diff_harness.py`) run against 1000 sampled nodes:

| | lineage-svc vs Marquez |
| --- | --- |
| Checked | 1000 |
| Match | _N_ |
| Mismatch | _N_ |
| Error | _N_ |
| Match rate | _NN.N%_ |

**Definition-of-Done requirement:** 100% match. If we are below, the
mismatch list (in `diff_report.json`) must be triaged and either:

- explained by a known semantic difference (and ticketed), or
- fixed before ship.

## Recovery

Postgres restart test (`benchmark/recovery_test.sh`):

- Restart command: `docker compose restart lineage-pg`
- Time until `/health` returns 200: _Ns_
- Target: < 30s — _PASS / FAIL_

## Risks / caveats

- Synthetic fixture only — final validation against a Marquez prod dump is
  pending devops read-only access.
- Resource caps in local docker-compose may not perfectly mirror Kubernetes
  limits in `dts`/`marquez` namespaces.
- Marquez 0.50.0 vs prod version — pin the prod version here once confirmed.

## Recommendation

- **If all 9 metrics pass AND match rate = 100%:** open ticket for dual-write
  rollout in DTS — `dts/openlineage/openlineage_client.py` emits to both
  endpoints with a feature flag.
- **If 1–2 metrics miss by < 20%:** iterate (CTE tuning, connection pooling,
  asyncpg statement cache) and re-benchmark.
- **If ≥ 3 metrics miss OR match rate < 99%:** abort PoC, escalate.

## Appendix

- Raw k6 summaries: `benchmark/results/*.json`
- Diff harness output: `benchmark/results/diff_report.json`
- Grafana snapshot URL: _link after run_
