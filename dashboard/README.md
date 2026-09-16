# Dashboard

## Technology choice

This dashboard uses **Streamlit**. It is the best fit here because it provides a small Python application with built-in charts and periodic refreshes, without the extra configuration and provisioning required by Grafana.

## What it shows

The dashboard reads the `ecommerce` database in ClickHouse and refreshes every five seconds. It includes:

- the live count of active orders;
- revenue grouped by order date; and
- the active-order breakdown by status.

The ClickHouse tables use `ReplacingMergeTree` for CDC updates and deletes. Every query therefore uses `FINAL` and filters `_peerdb_is_deleted = 0`, ensuring the metrics reflect the latest non-deleted version of each row.

## Run and access

Start the complete stack from the repository root:

```bash
docker compose up --build
```

Once ClickHouse is healthy, open [http://localhost:8501](http://localhost:8501). The dashboard receives ClickHouse credentials from the root `.env` file and connects to the Compose service name `clickhouse`.

## Proof of near-real-time updates

_Placeholder: add before/after screenshots or a screen recording here after a run shows a generator transaction reflected by the dashboard within a few seconds._
