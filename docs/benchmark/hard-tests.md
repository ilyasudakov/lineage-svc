# Hard Tests — Beyond Latency

The smoke benchmark showed `data-lineage` is fast. These hard tests
answer the questions latency numbers don't: does it stay *correct* and
*recoverable* under stress?

**Status:** all four test suites PASS on the smoke fixture (225k–405k edges).
**Date:** 2026-05-23
**Raw output:** [`benchmark/results/hard_tests_summary.txt`](../../benchmark/results/hard_tests_summary.txt)
**Code:** [`benchmark/hard_tests/`](../../benchmark/hard_tests/)

## Why these tests

The smoke benchmark proved data-lineage beats Marquez on **latency / throughput**.
It did not prove the service is **correct** under contention, **robust** to
weird graph shapes, **scalable** as the graph grows, or **recoverable** after
process / DB failures. Each test below targets one of those.

| Test | What it stresses | Risk if skipped |
| --- | --- | --- |
| `concurrent_writes` | Idempotency under PK contention | 4 DTS workers writing the same edge can leak duplicates or surface PK errors |
| `adversarial_graphs` | CTE correctness on weird topologies | Real lineage graphs sometimes cycle (bugs in producers); very deep / wide branches can hang the planner |
| `growing_graph` | Index health vs graph size | Linear read-latency growth = `seq_scan` somewhere — would only show at prod scale |
| `chaos` | Recovery after kill -9 | DoD requires < 30s recovery; not testing it means we promise something we don't know |

---

## 1. Concurrent writes — 64 threads × 200 reps × same edge

[`benchmark/hard_tests/concurrent_writes.py`](../../benchmark/hard_tests/concurrent_writes.py)

12,800 simultaneous POSTs of the same OL event (one `j1` job, one input,
one output → 3 edges). Verify the DB ends up with exactly 3 rows and
the client never sees a 4xx/5xx.

| Metric | Value |
| --- | --- |
| POSTs | 12,800 |
| Wall time | 70.06 s |
| Throughput | 183 POSTs/sec |
| Client errors | **0** |
| Latency p50 / p95 / p99 | 171 / 1,094 / 1,760 ms |
| Rows in DB after | **3** (expected: 3) |

**Result: PASS.** Idempotency holds under heavy contention. The high p95 (~1 s)
is the cost of 64 producers fighting for the same PK row — expected on
deliberate hot-row contention; the smoke benchmark hits unique rows and
sees p95 = 8 ms.

---

## 2. Adversarial graphs — cycle, deep, wide

[`benchmark/hard_tests/adversarial_graphs.py`](../../benchmark/hard_tests/adversarial_graphs.py)

### Cycle: A → B → C → A

Three OL events building a 3-node cycle. Traverse `depth=10` from A.
Recursive CTE must terminate (no infinite recursion).

→ status=200, **9 edges returned in 13 ms**. PASS.

### Deep: linear chain of length 100

100 OL events, each `n_i → j_i → n_{i+1}`. Traverse `depth=50` from n0.

→ status=200, **149 edges in 33 ms** at depth=50.
→ depth=51 returns **422** — the API caps depth at 50 ([`app/main.py`](../../app/main.py)),
  guardrail held. PASS.

### Wide: 1 root → 1000 children

One OL event with 1 input and 1000 outputs. Traverse `depth=1` from root.

→ status=200, **1001 edges in 18 ms** (1 `consumes` job-edge + 1000
  `derives_from` leaf-edges). PASS.

---

## 3. Growing graph degradation

[`benchmark/hard_tests/growing_graph.py`](../../benchmark/hard_tests/growing_graph.py)

Load in 5 batches of 15k events (~45k edges each). Sample 500 random reads
between each batch. The question: does read p95 grow as the graph grows?

| Step | Cumulative edges | Read p50 | Read p95 | Read p99 |
| --- | --- | --- | --- | --- |
| 1 | 45,000 | 10.03 ms | 11.77 ms | 13.09 ms |
| 2 | 90,000 | 9.75 ms | 10.37 ms | 10.96 ms |
| 3 | 135,000 | 9.89 ms | 10.86 ms | 12.05 ms |
| 4 | 179,999 | 9.92 ms | 10.89 ms | 11.93 ms |
| 5 | 224,997 | 9.80 ms | 10.51 ms | 12.39 ms |

**p95 growth ratio first → last: 0.89×.** Read latency is **flat** as the
graph grows 5×. Indexes are healthy; the recursive CTE does index lookups,
not sequential scans. PASS.

CSV at [`benchmark/results/growing_graph.csv`](../../benchmark/results/growing_graph.csv).

The next milestone here is repeating this test up to 5M edges to confirm
the curve stays flat at the target volume — but the trend is unambiguous
at 225k.

---

## 4. Chaos — kill app, kill DB

[`benchmark/hard_tests/chaos.sh`](../../benchmark/hard_tests/chaos.sh)

Each scenario: start a background writer producing 60k events, sleep 8 s
to let some rows in, `docker compose kill <service>`, restart, poll
`/health` until 200. Measure recovery time and rows added.

| Scenario | Recovery time | Rows before | Rows after | Added | DoD target |
| --- | --- | --- | --- | --- | --- |
| `kill_app` (kill `data-lineage`) | **6 s** | 224,997 | 226,485 | 1,488 | < 30 s |
| `kill_pg` (kill `lineage-pg`) | **3 s** | 226,485 | 404,904 | 178,419 | < 30 s |

**Both PASS.**

- `kill_app`: writer was firing during the outage, most POSTs failed
  during the down window — only 1,488 rows survived. That's expected; the
  service can't accept what it isn't running. Important finding: when it
  came back, it served traffic immediately, no stuck queues.
- `kill_pg`: writer survived the PG outage too. After PG came back at 3 s,
  the writer's queued events flushed and 178k rows landed. Confirms that
  asyncpg's connection pool reconnects cleanly without restarting the app.

---

## What we still haven't proved

- **Volume:** `growing_graph` only ran to 225k edges. The 5M-edge full run
  is needed before we promise prod-scale behaviour.
- **Multi-tenant isolation:** writes in namespace A are not visible to
  reads in namespace B. Not exercised — currently `/api/v1/lineage/direct`
  doesn't filter by namespace; a follow-up test should confirm whether
  this is correct behaviour or a leak.
- **Adversarial at scale:** the wide test used fanout=1000; real prod has
  hub datasets touched by 10k+ jobs. Not tested.
- **Data loss accounting under chaos:** we counted rows added but didn't
  diff the writer's expected events vs what the DB received. The 178k for
  `kill_pg` could include silent drops we'd want to catch.

These all belong in the next round.

---

## Reproduction

The stack must be up (`docker compose -f benchmark/docker-compose.yml up -d`)
and Alembic must have been applied to `lineage-pg` (see
[reproduction.md](reproduction.md)).

```bash
# Test 1: concurrent writes
.venv/Scripts/python.exe benchmark/hard_tests/concurrent_writes.py \
  --threads 64 --reps 200

# Test 2: adversarial graphs
.venv/Scripts/python.exe benchmark/hard_tests/adversarial_graphs.py

# Test 3: growing graph (CSV → benchmark/results/growing_graph.csv)
.venv/Scripts/python.exe benchmark/hard_tests/growing_graph.py \
  --reset --steps 5 --batch-events 15000 --samples-per-step 500

# Test 4: chaos
MSYS_NO_PATHCONV=1 bash benchmark/hard_tests/chaos.sh
```
