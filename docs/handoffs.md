# Handoffs — U1T01 Real-Time Analytics CDC

**How to use this file:** you are one agent among five, each possibly running in a
different tool (Claude Code, Codex, etc.) with no memory of the others' sessions.
Read **Section 0** in full — it's the contract everyone shares — then read **only your
own numbered section**. Don't edit another owner's folder or service block in
`docker-compose.yml` without flagging it to that person first. If something here
conflicts with what you find in the repo, the repo wins — but say so before you deviate,
don't silently improvise.

Full assignment context: [instructions.pdf](instructions.pdf). Schema/architecture
rationale: [requirements.md](requirements.md).

---

## Section 0 — Shared contract (read this first, every part)

**Project:** CDC pipeline from PostgreSQL → PeerDB → ClickHouse for an e-commerce
schema, fed by a continuous Python generator, benchmarked, optionally visualized.

**Repo layout (owner in brackets):**
```
docker-compose.yml        # shared file — see rule below
.env.example
postgres/          [Julio]     init/*.sql, roles/publication setup
generator/         [Julio]     generator.py, Dockerfile, requirements.txt
peerdb/             [Valeria]  setup scripts / mirror config
clickhouse/         [Jose Angel] init/*.sql (target schema)
benchmark/          [Leonora]  queries/, results/, scripts
dashboard/          [Lorena]   app + Dockerfile
docs/                          requirements.md, handoffs.md, report.pdf (final)
```

**Editing `docker-compose.yml`:** it's one shared file. Only add/edit the service
block(s) that belong to your part. Use `depends_on` + healthchecks so your service
waits for its dependencies. If you need a healthcheck added to someone else's service
(e.g. Postgres) because your service depends on it, add the healthcheck, don't
restructure their block.

**Naming you must not invent your own version of** (see requirements.md §5 for the
full table): Postgres service `postgres`, db `ecommerce`, replication role
`replicator`, publication `peerdb_pub`, ClickHouse service `clickhouse`, db
`ecommerce`. All credentials come from a root `.env` (create `.env.example` with
placeholder values, real `.env` stays untracked).

**Schema (do not redesign it in your part — if you find a real problem with it, flag
it in the group chat, don't unilaterally change column names):**

- `categories(category_id PK, category_name, created_at)`
- `products(product_id PK, category_id FK, sku, product_name, price, created_at, updated_at)`
- `customers(customer_id PK, full_name, email, city, country, created_at, updated_at)`
- `orders(order_id PK, customer_id FK, order_status, order_date, updated_at)`
- `order_items(order_item_id PK, order_id FK, product_id FK, quantity, unit_price, updated_at)`
- `payments(payment_id PK, order_id FK, payment_method, amount, payment_status, paid_at, updated_at)`

Every mutable table has `updated_at` — this is required for ClickHouse's
`ReplacingMergeTree` versioning in Part 3. Do not drop it anywhere.

**Definition of done for the whole project:** `docker compose up --build` from a
clean clone brings up Postgres with data flowing, PeerDB replicating, ClickHouse
receiving updates, and (if built) the dashboard reflecting changes — with zero manual
setup steps outside that one command. If your part can't reach full automation,
say exactly what manual step remains and why, in your part's README — don't leave it
undocumented.

---

## Section 1 — Julio: Part 1, Relational Modeling & Data Generator

**Goal:** stand up Postgres with the schema above and a script that continuously
hammers it with realistic INSERT/UPDATE/DELETE traffic.

**Inputs:** none — you go first.

**Steps:**
1. `postgres/init/01_schema.sql` — create all 6 tables exactly as specified in
   Section 0, with PK/FK constraints and `CHECK` constraints on enum-like columns
   (`order_status`, `payment_status`, `payment_method`).
2. `postgres/init/02_replication.sql` — create the `replicator` role
   (`LOGIN REPLICATION PASSWORD '...'` from env), `GRANT SELECT` on all 6 tables,
   and `CREATE PUBLICATION peerdb_pub FOR TABLE <all 6 tables>;`.
3. Add the `postgres` service to root `docker-compose.yml`: official `postgres:16`
   image, mount `postgres/init/` into `/docker-entrypoint-initdb.d/`, set
   `command: ["postgres", "-c", "wal_level=logical"]` (logical replication requires
   this — it cannot be set via `ALTER SYSTEM` after the fact without a restart, so
   set it at container start). Add a healthcheck (`pg_isready`).
4. `generator/generator.py` — Python script (psycopg2 or asyncpg + Faker) that loops
   forever: seeds some customers/products/categories first, then continuously
   inserts orders + order_items + payments, updates order/payment statuses along
   realistic transitions (see requirements.md §3), and occasionally deletes
   `order_items`/`payments` rows to exercise the DELETE path. Make rate and total
   duration configurable via env vars (`GEN_RATE_PER_SEC`, `GEN_DURATION_SECONDS`).
   Target: a couple hundred thousand total operations over the run.
5. `generator/Dockerfile` + `requirements.txt`, add `generator` service to
   `docker-compose.yml`, `depends_on: postgres` (condition: healthy).
6. `postgres/README.md`: how to connect manually (`psql`), how to verify
   `wal_level=logical` (`SHOW wal_level;`), how to check the publication
   (`\dRp+ peerdb_pub`).

**Acceptance criteria:** `docker compose up postgres generator` brings both up
cleanly; connecting with `psql` shows all 6 tables populated and growing; `SHOW
wal_level;` returns `logical`; `\dRp+ peerdb_pub` lists all 6 tables.

**Handoff to Valeria (Part 2):** Postgres host/port/db/role credentials (via `.env`),
confirmation that `wal_level=logical` is active and `peerdb_pub` exists covering all
6 tables. Tell her once this is running so she isn't blocked.

---

## Section 2 — Valeria: Part 2, CDC Pipeline Setup (PeerDB)

**Goal:** stand up PeerDB and create a working CDC mirror from Postgres's
`peerdb_pub` publication into ClickHouse.

**Inputs (from Julio, Part 1):** running `postgres` service, `replicator` role,
`peerdb_pub` publication covering all 6 tables. Don't start until you've confirmed
these exist (ask Julio or check `postgres/README.md`).

**Steps:**
1. Read PeerDB's architecture docs (https://docs.peerdb.io/architecture) and their
   quickstart/self-hosted docker-compose setup before writing anything — PeerDB's own
   compose stack has multiple services (its own catalog DB, UI, flow server, etc.).
   Do not guess service/container names from memory; pull them from the current docs.
2. Integrate PeerDB's required services into the root `docker-compose.yml` under
   clearly-named blocks (prefix `peerdb-` if there are several, e.g.
   `peerdb-server`, `peerdb-ui`). Keep PeerDB's own internal catalog database
   separate from our `postgres` service — it is infrastructure for PeerDB itself,
   not part of the e-commerce schema.
3. Register our `postgres` service as the CDC **source** and the `clickhouse`
   service (from Jose Angel, Part 3 — coordinate directly with him since your work
   is sequential) as the **destination**, using PeerDB's connector config for
   Postgres → ClickHouse.
4. Create the mirror covering all 6 tables in `peerdb_pub`. **Automate this**:
   write `peerdb/setup_mirror.sh` (or use PeerDB's API/CLI) and wire it into
   compose so it runs once, after Postgres and ClickHouse are healthy and PeerDB
   itself is up — e.g. a short-lived `peerdb-init` service with
   `depends_on: {postgres: {condition: service_healthy}, clickhouse: {condition: service_healthy}}`.
   The grader must not have to click through the PeerDB UI manually.
5. **Investigate and document PeerDB's delete-propagation behavior** (soft-delete
   marker column vs hard row delete in ClickHouse) — check current docs, don't
   assume. Write findings in `peerdb/README.md`; Jose Angel needs this for his
   ClickHouse queries (whether he needs to filter out soft-deleted rows).
6. `peerdb/README.md`: what was deployed, mirror name, how to check mirror status,
   the delete-propagation finding from step 5.

**Acceptance criteria:** after `docker compose up`, an INSERT into any of the 6
Postgres tables appears in the corresponding ClickHouse table within seconds, with
no manual step. Mirror status is queryable/checkable via a script or PeerDB's API,
not only by eyeballing the UI.

**Handoff to Jose Angel (Part 3):** which ClickHouse tables/columns PeerDB expects
to exist (column name/type mapping it needs), and the delete-propagation finding.
Coordinate on this before he finalizes the ClickHouse DDL — this is why you two are
sequenced back-to-back.

---

## Section 3 — Jose Angel: Part 3, Analytical Layer Set Up (ClickHouse)

**Goal:** stand up ClickHouse with the mirrored schema, correctly handling the
UPDATE/DELETE semantics that PeerDB's CDC stream produces.

**Inputs (from Valeria, Part 2):** the column mapping/format PeerDB's ClickHouse
connector expects, and her finding on delete propagation. **Talk to Valeria before
finalizing your DDL** — your table definitions need to match what her mirror writes.

**Steps:**
1. Add the `clickhouse` service to root `docker-compose.yml` (official
   `clickhouse/clickhouse-server` image), with a healthcheck. Valeria's PeerDB init
   step depends on this being healthy, so don't change the service name (`clickhouse`)
   or the healthcheck without telling her.
2. `clickhouse/init/01_schema.sql`: recreate all 6 tables using
   `ReplacingMergeTree(updated_at)` (or the version column PeerDB actually populates
   — confirm exact column name with Valeria, it may be prefixed, e.g. `_peerdb_synced_at`
   vs our own `updated_at`) as the engine, `ORDER BY` the primary key of each table.
   ClickHouse doesn't do row-level UPDATE/DELETE the way Postgres does — this engine
   + `FINAL` at query time is the intended workaround (per the assignment's hint).
3. Write a short verification script/query set (`clickhouse/verify.sql` or similar):
   pick a row, update it in Postgres via `psql`, and show the `SELECT ... FINAL`
   query in ClickHouse returning the new value shortly after. This is a named
   requirement in the assignment ("verify that an update... correctly updates the
   final state of that record in ClickHouse") — capture the before/after output,
   Leonora and the report will want it too.
4. `clickhouse/README.md`: schema decisions, why `ReplacingMergeTree` + `FINAL`,
   and the verification steps/output from step 3.

**Acceptance criteria:** all 6 tables exist in ClickHouse with data flowing in from
PeerDB; `SELECT ... FINAL` on a table returns the latest state after a Postgres
UPDATE, demonstrated with actual before/after query output saved somewhere (file or
screenshot) for the report.

**Handoff to Leonora (Part 4) and Lorena (Part 5):** confirmation the ClickHouse
schema is stable (table/column names), and the `FINAL` usage pattern they should
copy in their own queries.

---

## Section 4 — Leonora: Part 4, Benchmarking

**Goal:** run identical analytical queries against Postgres and ClickHouse while
the generator is actively running, capture execution plans, and produce the
comparison numbers for the report.

**Inputs (from Jose Angel, Part 3):** stable ClickHouse schema + confirmation the
pipeline is flowing live. Also depends on Julio's generator (Part 1) still running
during the benchmark — this must be run with the whole stack up, not in isolation.

**Steps:**
1. Design 3–5 analytical queries that need aggregation + grouping + filtering across
   the full dataset, in both dialects (SQL differs slightly, e.g. `FINAL` only on
   ClickHouse). Ideas: revenue by category per month, top-10 products by revenue,
   average order value by customer country, order-status funnel counts, payment
   method success-rate breakdown. Put them in `benchmark/queries/` as paired files
   (`01_revenue_by_category.pg.sql`, `01_revenue_by_category.ch.sql`) so it's clear
   which pair is "the same question."
2. Write `benchmark/run_benchmark.py` (or a shell script) that, for each query pair:
   runs it against Postgres with `EXPLAIN ANALYZE`, runs it against ClickHouse with
   `EXPLAIN` (and separately captures wall-clock time, e.g. via `clickhouse-client`'s
   timing output), and saves both outputs to `benchmark/results/`.
3. Run the full benchmark **while `generator` is actively running** (per the
   assignment) — not against a static/idle database. Note the generator's rate at
   the time you ran it, for reproducibility.
4. Summarize results in `benchmark/results/summary.md`: a table of query × engine ×
   execution time, plus your read on *why* the plans differ (e.g. row-store index
   scans vs column-store vectorized scans, ClickHouse's lack of the same kind of
   join optimizer, effect of `FINAL`). This summary feeds directly into the final
   report — write it like report-ready prose, not just raw numbers.

**Acceptance criteria:** `benchmark/results/` contains, for every query, the
Postgres `EXPLAIN ANALYZE` output, the ClickHouse `EXPLAIN` output, and a timing
number for both, all captured under live write load.

**Handoff:** `benchmark/results/summary.md` goes straight into the final report
(Section 8 below) — whoever assembles `docs/report.pdf` pulls from it directly.

---

## Section 5 — Lorena: Part 5, Real-Time Dashboard (optional but recommended)

**Goal:** a lightweight dashboard reading from ClickHouse that visibly updates
within seconds of new transactions hitting Postgres.

**Inputs (from Jose Angel, Part 3):** stable ClickHouse schema, confirmed working
CDC flow, and the `FINAL` query pattern.

**Steps:**
1. Pick Streamlit (simplest to wire to ClickHouse with autorefresh, recommended
   default) or Grafana (more polished, more setup) — your call, note which and why
   in `dashboard/README.md`.
2. `dashboard/app.py` (if Streamlit): connect to `clickhouse` service via the
   `clickhouse-connect` (or similar) client, auto-refresh every few seconds
   (`st.autorefresh` or a `time.sleep` + rerun loop), show at least: live order
   count, revenue over time chart, order-status breakdown — reading with `FINAL`
   where it matters.
3. Add `dashboard` service + Dockerfile to root `docker-compose.yml`,
   `depends_on: clickhouse` (condition: healthy), expose its port (e.g. 8501).
4. Demonstrate and capture proof (screen recording or before/after screenshots)
   that a transaction inserted by `generator` shows up on the dashboard within a
   few seconds — this is an explicit assignment requirement, not just "dashboard
   exists." Save the proof under `dashboard/` or `docs/` for the report.
5. `dashboard/README.md`: what it shows, how to access it, the proof from step 4.

**Acceptance criteria:** `docker compose up` brings up the dashboard reachable in a
browser, showing live-updating numbers as the generator runs, with saved proof of
the near-real-time reflection.

**Handoff:** dashboard screenshots/recording go into the final report as evidence
for the "optional" Part 5 credit.

---

## Section 6 — Assembling the final report (docs/report.pdf)

Whoever finishes first (likely Julio, since Part 1 is the entry point — confirm with
the group) assembles `docs/report.pdf` from everyone's material:

1. ER diagram + schema rationale — from `docs/requirements.md` §3.
2. CDC implementation steps/considerations — from `postgres/README.md` +
   `peerdb/README.md` (Valeria's delete-propagation finding belongs here).
3. ClickHouse update/delete handling + verification — from `clickhouse/README.md`
   (Jose Angel's before/after proof).
4. Benchmark results + analysis — from `benchmark/results/summary.md` (Leonora),
   verbatim where possible, since she wrote it report-ready.
5. (Optional) Dashboard proof — from `dashboard/README.md` (Lorena).

Do not re-derive numbers or re-describe decisions from scratch here — pull from each
owner's README/summary so the report matches what was actually built, not a
re-imagined version of it.
