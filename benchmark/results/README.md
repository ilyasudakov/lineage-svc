# Raw k6 Results

Per-scenario JSON dumps produced by `k6 run --summary-export`. Each file
contains the full set of k6 metrics (HTTP, iterations, custom trends,
errors) at the moment the run finished.

| File | Scenario | Backend | Duration | Rate |
| --- | --- | --- | --- | --- |
| `steady_write_lineage.json` | `steady_write` | data-lineage | 60 s | 100 rps |
| `steady_write_marquez.json` | `steady_write` | Marquez 0.50.0 | 60 s | 100 rps |
| `read_lineage.json` | `read_only_baseline` | data-lineage | 60 s | 100 rps |
| `read_marquez.json` | `read_only_baseline` | Marquez 0.50.0 | 60 s | 100 rps |

See [`docs/benchmark/results.md`](../../docs/benchmark/results.md) for
the curated comparison tables and
[`docs/benchmark/methodology.md`](../../docs/benchmark/methodology.md)
for how these were produced.
