# Benchmark Results

The benchmark compared four equivalent analytical questions against PostgreSQL
and ClickHouse while the generator and CDC pipeline were active. The final run
used five measured repetitions per engine and query, with alternating engine
order. Queries used the first settled UTC cutoff in the 5–15 minute window:
`2026-09-14 06:45:53+00`.

The generator had produced 202,597 INSERT/UPDATE/DELETE mutations before this
run. Its extension was configured with `GEN_RATE_PER_SEC=100` and averaged about
125 database mutations per second in the generator log.

## Timing results

Times are end-to-end local Docker command wall-clock measurements in milliseconds.
They include database execution, client startup, container command overhead, and
result transfer.

| Query | PostgreSQL min | PostgreSQL median | PostgreSQL max | ClickHouse min | ClickHouse median | ClickHouse max |
|---|---:|---:|---:|---:|---:|---:|
| Revenue by category | 219.07 | 298.02 | 386.57 | 283.97 | 388.74 | 427.31 |
| Top products | 259.58 | 307.00 | 336.52 | 335.68 | 358.31 | 384.75 |
| AOV by country | 216.49 | 349.55 | 365.73 | 219.87 | 302.61 | 342.60 |
| Payment success by method | 226.17 | 318.00 | 362.42 | 273.61 | 370.98 | 401.93 |

PostgreSQL had the lower median for revenue by category (23.3% lower), top
products (14.3% lower), and payment success (14.3% lower). ClickHouse had the
lower median for AOV by country (13.4% lower). These differences are specific to
this dataset, query shape, CDC-read semantics, and local Docker measurement
method; they are not a general ranking of the two systems.

## Why the plans differ

PostgreSQL's plans use the row-store index `idx_orders_status` to find delivered
orders with a bitmap index scan followed by a bitmap heap scan. The date and
`updated_at` cutoff predicates are then applied as filters. The larger fact table
`order_items` is sequentially scanned, after which PostgreSQL uses hash joins,
hash aggregation, and a final sort. The top-products query uses a top-N heapsort.
The payment query similarly sequentially scans `payments`, uses the status index
for `orders`, joins with a hash join, and finishes with a grouped sort.

ClickHouse's plans read the CDC tables through `ReadFromMergeTree` nodes. Each
table read has `FINAL: 1` and `_peerdb_is_deleted = 0`, so ClickHouse first
resolves ReplacingMergeTree versions and excludes CDC tombstones before the
aggregation. The plans then use runtime join filters and hash joins, followed by
aggregation and sorting; the top-products plan also shows a preliminary LIMIT.
This is the column-store execution path rather than PostgreSQL's indexed
row-store path. The ClickHouse `EXPLAIN` output is a logical plan and does not
report execution time, so the wall-clock timings are the separate comparison
measure.

The measured result is therefore a combination of storage-engine work, join and
aggregation work, CDC `FINAL`/tombstone handling, and local Docker command
overhead. In particular, PostgreSQL's captured internal execution times are much
lower than the end-to-end medians because the latter include process and result
handling. `FINAL` is necessary for correctness here, but it adds read-time work
that a plain ClickHouse query would not incur.

## Methodology recommendation

Retain the terminal cohort for this benchmark: delivered orders, plus completed
or refunded payments for the payment query. This is the correct choice while the
generator remains active because the generator can update an older order or
payment after the cutoff. PostgreSQL then sees the new current row before
ClickHouse necessarily receives it, so a query over mutable lifecycle states is
not a reproducible point-in-time comparison without historical snapshots.

The terminal cohort preserves the required live-write condition while making the
paired results deterministic. It is a documented limitation: the benchmark
measures the settled terminal cohort, not every pending, paid, shipped, or failed
row. A literal full-current-dataset comparison should be a separate benchmark
using coordinated PostgreSQL and ClickHouse snapshots or a CDC watermark; adding
that machinery to this live benchmark would increase complexity and change the
measurement conditions.

## Caveats

- The query runner permits a one-cent numeric difference for ClickHouse average
  rounding; larger numeric or textual differences fail the run.
- Query outputs were validated between engines before measurement and remained
  equivalent during all five repetitions.
- The plan files are the authoritative evidence for operator details:
  `*.postgres.explain.txt` contains `EXPLAIN (ANALYZE, BUFFERS)` and
  `*.clickhouse.explain.txt` contains ClickHouse `EXPLAIN`.
