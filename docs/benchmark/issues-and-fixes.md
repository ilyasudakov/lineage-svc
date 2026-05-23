# Issues Found During the Smoke Benchmark

Four bugs surfaced between bringing the stack up and getting the first
green run. Documenting them here so the full Week 3 run starts clean and
so that anyone replaying this knows what to expect.

---

## 1. `metadata` column collides with SQLAlchemy `Table.metadata`

**Symptom:** First ingest POST returned `500 Internal Server Error`.
Container logs:

```
AttributeError: 'MetaData' object has no attribute '_bulk_update_tuples'
  File "/app/app/repository.py", line 26, in upsert_edges
    stmt = insert(LineageEdge).values(rows)
```

**Cause:** The DB column is named `metadata` (per the schema in the
ticket). When we use the ORM-mapped class as the insert target, SQLAlchemy's
ORM bulk-insert path treats the dict key `"metadata"` as a reference to
`Table.metadata` (the registry attribute), not the column.

**Fix:** Use the Core `__table__` for the insert. The ORM bulk resolver
isn't invoked, so the dict key lands on the column unambiguously.

```python
# before
stmt = insert(LineageEdge).values(rows)

# after
stmt = insert(LineageEdge.__table__).values(rows)
```

**Where:** [`app/repository.py:26-28`](../../app/repository.py),
landed in master via [PR #3](https://github.com/ilyasudakov/lineage-svc/pull/3)
commit `943b886`.

---

## 2. Alembic does not run automatically inside the container

**Symptom:** Same `500` as above on a fresh stack — but cause was
different: the `lineage_edge` table didn't exist.

**Cause:** PR #1 removed the `create_all` call from `app/main.py` lifespan
in favour of Alembic migrations. The `Dockerfile` only copies the `app/`
directory, not `migrations/` or `alembic.ini`, so `alembic upgrade head`
can't run inside the container.

**Fix (for now):** Run Alembic from the host against the exposed Postgres
port:

```bash
LINEAGE_DATABASE_URL="postgresql+asyncpg://lineage:lineage@localhost:5433/lineage" \
  alembic upgrade head
```

**Proper fix (TODO):** Copy `alembic.ini` and `migrations/` into the
Docker image and either (a) run `alembic upgrade head` on container start
via an entrypoint script, or (b) run migrations as a separate
docker-compose service that depends on the DB and runs to completion.

---

## 3. `K6_DURATION` / `K6_RATE` env vars silently override k6 scenarios

**Symptom:** First k6 invocation reported the right number of iterations
but every custom metric (`write_latency_ms`, `read_direct_latency_ms`)
showed `p(95)=0s` and `iteration_duration=1s`. k6 also printed:

```
level=warning msg="env level configuration overrode scenarios configuration entirely"
```

**Cause:** We named the override env vars `K6_DURATION` and `K6_RATE`,
which collide with k6's own native flags. k6 saw `K6_DURATION=60s` and
interpreted it as a global `--duration` flag, which overrides any
`scenarios:` block entirely, falling back to the default `export default
function () { sleep(1); }` for 60 seconds.

**Fix:** Rename overrides so they don't collide with the `K6_*` prefix:

```javascript
// before
const DUR_OVERRIDE = __ENV.K6_DURATION;
const RATE_OVERRIDE = __ENV.K6_RATE ? parseInt(__ENV.K6_RATE, 10) : null;

// after
const DUR_OVERRIDE = __ENV.OVERRIDE_DURATION;
const RATE_OVERRIDE = __ENV.OVERRIDE_RATE ? parseInt(__ENV.OVERRIDE_RATE, 10) : null;
```

**Where:** [`benchmark/k6/scenarios.js`](../../benchmark/k6/scenarios.js).

**Lesson:** any env var starting with `K6_` may be claimed by k6 itself —
check [the k6 reference](https://grafana.com/docs/k6/latest/using-k6/k6-options/reference/)
before naming overrides.

---

## 4. URN shape mismatch + URN pool too large

**Symptom:** Read scenarios against Marquez reported 100% errors (6,001 /
6,001 HTTP 4xx). Against lineage-svc, reads succeeded but returned empty
edge sets ~98% of the time.

**Cause(s):** Two separate issues compounded.

- **Separator:** lineage-svc URNs are formatted `dataset:<ns>/<name>`.
  Marquez expects `dataset:<ns>:<name>` (colon, not slash). The k6
  generator hardcoded the slash.
- **Pool size:** The k6 generator picked dataset IDs from a 500,000-wide
  range. The loaded fixture had only ~10,000 distinct datasets (= edges
  // 10 by the generator's own formula). 98% of generated URNs pointed
  at nothing.

**Fix:** Add a `BACKEND` env var to the k6 library, switch the separator
on it, and shrink the default pool to match the fixture (overridable via
`URN_POOL`):

```javascript
const BACKEND = __ENV.BACKEND || "lineage";
const URN_POOL = __ENV.URN_POOL ? parseInt(__ENV.URN_POOL, 10) : 10_000;
// ...
const sep = BACKEND === "marquez" ? ":" : "/";
return `dataset:${ns}${sep}${name}`;
```

The same `BACKEND` flag also switches the read URL shape — Marquez's
`/api/v1/lineage?nodeId=…&depth=1` vs lineage-svc's
`/api/v1/lineage/direct?node=…`.

**Where:** [`benchmark/k6/lib/urn.js`](../../benchmark/k6/lib/urn.js),
[`benchmark/k6/scenarios.js`](../../benchmark/k6/scenarios.js)
(`readUrl()` helper).

---

## Bonus: Git Bash on Windows mangles container paths

**Symptom:** `docker run -v "$(pwd)/benchmark/k6:/k6" grafana/k6 run /k6/scenarios.js`
failed with:

```
The moduleSpecifier "C:/Program Files/Git/k6/scenarios.js" couldn't be found
```

**Cause:** MSYS path conversion rewrites `/k6/scenarios.js` to a Windows
absolute path before Docker even sees it.

**Fix:** Prefix `MSYS_NO_PATHCONV=1` in the Bash invocation:

```bash
MSYS_NO_PATHCONV=1 docker run --rm -i --network benchmark_default \
  -v "E:/projects/lineage-svc/benchmark:/bench" \
  grafana/k6 run /bench/k6/scenarios.js
```

This is environmental, not a code bug — but the runner script
[`benchmark/run_all.sh`](../../benchmark/run_all.sh) should probably
set it for Windows users.
