# Benchmarking — Leonora

This folder benchmarks equivalent analytical queries in PostgreSQL and ClickHouse
while the generator keeps writing to PostgreSQL.

## Before running

Start the full pipeline from the repository root:

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
docker compose logs --tail 20 generator
```

Wait until PeerDB is replicating and the generator is active. The assignment target
is approximately 200,000 INSERT/UPDATE/DELETE operations across the run. At the
default rate, let the generator continue until its logs reach that total, or raise
`GEN_RATE_PER_SEC`/`GEN_DURATION_SECONDS` in the ignored `.env` and record the
values used.

Do not stop the generator during the benchmark.

## Run

```bash
python3 benchmark/run_benchmark.py
```

The runner executes one unmeasured equivalence check, captures PostgreSQL
`EXPLAIN (ANALYZE, BUFFERS)` and ClickHouse `EXPLAIN`, then makes five measured
runs per engine/query. It alternates engine order each iteration and starts with
a UTC cutoff five minutes before the run, backing off one minute at a time to a
maximum of fifteen minutes until every pair agrees on the same non-empty settled
portion of the live dataset.

Use `--repetitions N` to change the number of measured runs.

## Query contract

Each `queries/*.pg.sql` file has a matching `queries/*.ch.sql` file with the same
business meaning. ClickHouse queries always use `FINAL` and filter
`_peerdb_is_deleted = 0` for every source table, matching the CDC current-row
semantics.

The generator can update older rows at any time, so the paired queries use a
terminal cohort: delivered orders, and for payment success, completed or refunded
payments. Those rows no longer transition, which makes a cutoff reproducible while
the generator continues running.

The runner requires matching row counts and text fields. It permits only a
one-cent difference in calculated decimals, accounting for ClickHouse's
floating-point average rounding; larger numeric differences fail the run.

Revenue comes from `order_items.quantity * order_items.unit_price`; it intentionally
does not use `payments.amount`.

## Evidence

The runner writes these generated files to `benchmark/results/`:

```text
01_revenue_by_category.postgres.explain.txt
01_revenue_by_category.clickhouse.explain.txt
... one plan pair for each query
timings.csv
run_metadata.json
summary.md
workload.md
```

`summary.md` is the starting point for the final report: add observations from the
captured plans, including row-store/index behavior in PostgreSQL, columnar execution
in ClickHouse, and the cost of `FINAL`.

If CPU/memory observations are required, capture them as workload-level snapshots:

```bash
docker stats --no-stream
```
