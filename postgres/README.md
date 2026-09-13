# postgres/ — owner: Julio

See [docs/handoffs.md](../docs/handoffs.md) Section 1 for the full task and
[docs/requirements.md](../docs/requirements.md) §3 for the schema/ERD rationale.

Contents: `init/01_schema.sql` (6 tables, PK/FK/CHECK constraints, indexes on FK
columns), `init/02_replication.sh` (creates the `replicator` role and the
`peerdb_pub` publication PeerDB/Part 2 reads from).

## How to run it

```bash
cp .env.example .env   # first time only
docker compose up --build postgres generator
```

## How to connect manually

```bash
docker compose exec postgres psql -U postgres -d ecommerce
```

## Verification — commands run and their actual output

Everything below was captured from a real `docker compose up --build postgres
generator` run against this repo (dates shown are the container clock, UTC).

### Containers come up healthy

```bash
$ docker compose ps
```
```
NAME                                                        IMAGE          STATUS
...-generator-1                                              (built)       Up 9 seconds
...-postgres-1                                                postgres:16   Up 15 seconds (healthy)
```

### Schema — all 6 tables created

```bash
$ docker compose exec postgres psql -U postgres -d ecommerce -c "\dt"
```
```
            List of relations
 Schema |    Name     | Type  |  Owner
--------+-------------+-------+----------
 public | categories  | table | postgres
 public | customers   | table | postgres
 public | order_items | table | postgres
 public | orders      | table | postgres
 public | payments    | table | postgres
 public | products    | table | postgres
(6 rows)
```

### Logical replication is enabled (required for CDC)

```bash
$ docker compose exec postgres psql -U postgres -d ecommerce -c "SHOW wal_level;"
```
```
 wal_level
-----------
 logical
(1 row)
```

### Publication PeerDB (Part 2) will subscribe to

```bash
$ docker compose exec postgres psql -U postgres -d ecommerce -c "\dRp+ peerdb_pub"
```
```
                           Publication peerdb_pub
  Owner   | All tables | Inserts | Updates | Deletes | Truncates | Via root
----------+------------+---------+---------+---------+-----------+----------
 postgres | f          | t       | t       | t       | t         | f
Tables:
    "public.categories"
    "public.customers"
    "public.order_items"
    "public.orders"
    "public.payments"
    "public.products"
```

### Replication role

```bash
$ docker compose exec postgres psql -U postgres -d ecommerce -c "\du replicator"
```
```
      List of roles
 Role name  | Attributes
------------+-------------
 replicator | Replication
```

### Data is continuously growing (row counts, ~15s apart)

```bash
$ docker compose exec postgres psql -U postgres -d ecommerce -c "SELECT 'categories' t, count(*) FROM categories UNION ALL SELECT 'products', count(*) FROM products UNION ALL SELECT 'customers', count(*) FROM customers UNION ALL SELECT 'orders', count(*) FROM orders UNION ALL SELECT 'order_items', count(*) FROM order_items UNION ALL SELECT 'payments', count(*) FROM payments ORDER BY 1;"
```

T0:
```
      t      | count
-------------+-------
 categories  |     8
 customers   |   500
 order_items |  5103
 orders      |  1758
 payments    |  1669
 products    |   200
(6 rows)
```

T1 (~15s later, same query):
```
      t      | count
-------------+-------
 categories  |     8
 customers   |   500
 order_items |  5367
 orders      |  1853
 payments    |  1760
 products    |   200
(6 rows)
```

order_items +264, orders +95, payments +91 in 15 seconds — the generator is live.

### UPDATEs are actually happening (not just inserts)

`order_date` is set once at INSERT; `updated_at` only moves on a later UPDATE. Rows
where `updated_at > order_date` prove the status-transition UPDATEs are firing:

```bash
$ docker compose exec postgres psql -U postgres -d ecommerce -c "SELECT order_id, order_status, order_date, updated_at FROM orders WHERE updated_at > order_date ORDER BY updated_at DESC LIMIT 5;"
```
```
 order_id | order_status |          order_date           |          updated_at
----------+--------------+-------------------------------+-------------------------------
      868 | shipped      | 2026-09-13 02:42:17.186664+00 | 2026-09-13 02:45:50.697089+00
      465 | shipped      | 2026-09-13 02:41:08.910262+00 | 2026-09-13 02:45:50.349559+00
     1292 | shipped      | 2026-09-13 02:43:29.396449+00 | 2026-09-13 02:45:50.200853+00
     1180 | paid         | 2026-09-13 02:43:09.560092+00 | 2026-09-13 02:45:49.783952+00
      793 | shipped      | 2026-09-13 02:42:04.07287+00  | 2026-09-13 02:45:49.446859+00
(5 rows)
```

### Status distributions (confirms the full lifecycle is exercised)

```bash
$ docker compose exec postgres psql -U postgres -d ecommerce -c "SELECT order_status, count(*) FROM orders GROUP BY order_status ORDER BY order_status;"
```
```
 order_status | count
--------------+-------
 cancelled    |   464
 delivered    |    98
 paid         |   224
 pending      |   963
 shipped      |   117
```

```bash
$ docker compose exec postgres psql -U postgres -d ecommerce -c "SELECT payment_status, count(*) FROM payments GROUP BY payment_status ORDER BY payment_status;"
```
```
 payment_status | count
----------------+-------
 completed      |   430
 failed         |   187
 pending        |  1043
 refunded       |   118
```

### Generator log — throughput, plus a graceful stop/restart

```bash
$ docker compose logs generator --tail 10
```
```
generator-1  | [251s] total_ops=9793 insert=7456 update=2135 delete=202 (39.0 ops/sec avg)
generator-1  | [261s] total_ops=10212 insert=7786 update=2215 delete=211 (39.1 ops/sec avg)
generator-1  | [271s] total_ops=10620 insert=8112 update=2288 delete=220 (39.2 ops/sec avg)
generator-1  | Stopping. Final totals: total_ops=10722 {'insert': 8195, 'update': 2307, 'delete': 220}
generator-1  | Connected to Postgres.
generator-1  | Reference data already seeded, skipping.
generator-1  | Starting generator: ~20.0 events/sec, duration=3600s
generator-1  | [10s] total_ops=350 insert=255 update=87 delete=8 (34.9 ops/sec avg)
generator-1  | [20s] total_ops=758 insert=580 update=163 delete=15 (37.8 ops/sec avg)
generator-1  | [30s] total_ops=1132 insert=871 update=240 delete=21 (37.6 ops/sec avg)
```

This also demonstrates the generator handles a restart cleanly: it caught SIGTERM,
printed final totals, and on the next `up` it detected reference data already
existed (`Reference data already seeded, skipping.`) instead of re-seeding —
idempotent restarts, no duplicate categories/products/customers.

## Tear down

```bash
docker compose down        # keep the seeded data volume
docker compose down -v     # also wipe it
```
