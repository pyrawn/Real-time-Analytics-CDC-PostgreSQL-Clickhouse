# Real-Time Analytics with PostgreSQL CDC & ClickHouse

U1T01 — Trends in Data Science. CDC pipeline from PostgreSQL (OLTP) to ClickHouse
(OLAP) via PeerDB, fed by a continuous e-commerce data generator, benchmarked, with
an optional real-time dashboard.

Start here:
- [docs/instructions.pdf](docs/instructions.pdf) — original assignment
- [docs/requirements.md](docs/requirements.md) — schema, architecture, shared contract
- [docs/handoffs.md](docs/handoffs.md) — numbered instructions per team member

Team → part mapping: Julio (1: modeling & generator), Valeria (2: CDC/PeerDB),
Jose Angel (3: ClickHouse), Leonora (4: benchmarking), Lorena (5: dashboard).

## Running

```bash
cp .env.example .env   # fill in real values
docker compose up --build
```
