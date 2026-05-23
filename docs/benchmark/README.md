# Benchmark Report — IMD-60352 (data-lineage vs Marquez)

Comparative performance report from the local docker-compose side-by-side
benchmark. This index links to the full breakdown.

**Status:** smoke + hard tests + full benchmark complete. See [../decision.md](../decision.md) for the final SHIP recommendation.
**Date:** 2026-05-23
**Jira:** [IMD-60352](https://improvado.atlassian.net/browse/IMD-60352)

## Documents

| Doc | What it covers |
| --- | --- |
| [methodology.md](methodology.md) | What was tested, how, on what hardware, with what fixture |
| [results.md](results.md) | All measured numbers per scenario, side-by-side |
| [hard-tests.md](hard-tests.md) | Concurrency, adversarial graphs, growing-graph, chaos |
| [issues-and-fixes.md](issues-and-fixes.md) | Bugs found while testing + how they were fixed |
| [reproduction.md](reproduction.md) | Step-by-step rerun guide |
| [../decision.md](../decision.md) | Final ship/iterate/abort recommendation (in progress) |

## Executive summary

Under identical 100 rps load with a 100k-edge fixture, **data-lineage beat
Marquez on every measured metric by 1–3 orders of magnitude**:

| Metric | data-lineage | Marquez | Speedup |
| --- | --- | --- | --- |
| Loader throughput | 110 ev/s | 33 ev/s | **3.3×** |
| Write p95 @ 100 rps | **8 ms** | 21,190 ms | **2,649×** |
| Write error rate | 0.0% | 29.3% | — |
| Write iterations dropped | 0 | 3,728 / 6,001 | — |
| Read direct p95 | **4 ms** | 285.8 ms | **71×** |
| Read depth=3 p95 | **4 ms** | 287 ms | **72×** |
| Read depth=10 p95 | **4 ms** | 316 ms | **79×** |

**6 of 9 Definition-of-Done targets provisionally pass on smoke load.**
The remaining 3 (sustained 300 ev/s, Postgres CPU < 50% under 10×,
zero sequential scans) require the full 5M-edge run.

See [results.md](results.md) for the full per-scenario tables and
[issues-and-fixes.md](issues-and-fixes.md) for the four bugs found and
fixed during the smoke run.

## Raw artifacts

- k6 summary JSON per scenario: [`benchmark/results/`](../../benchmark/results/)
- Docker compose stack: [`benchmark/docker-compose.yml`](../../benchmark/docker-compose.yml)
- k6 scenarios: [`benchmark/k6/scenarios.js`](../../benchmark/k6/scenarios.js)
- Fixture generator + loader: [`benchmark/fixtures/generate.py`](../../benchmark/fixtures/generate.py)
- Diff harness (correctness check): [`benchmark/diff_harness.py`](../../benchmark/diff_harness.py)
