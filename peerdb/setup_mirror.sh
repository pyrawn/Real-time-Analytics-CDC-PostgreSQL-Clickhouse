#!/bin/bash
# Creates the PeerDB peers (Postgres source, ClickHouse target) and the CDC mirror.
# Runs from the peerdb-init service. Every statement is idempotent (IF NOT EXISTS),
# so re-running `docker compose up` is safe.
set -euo pipefail

export PGPASSWORD="${PEERDB_PASSWORD:-peerdb}"
PEERDB=(psql -v ON_ERROR_STOP=1 -h peerdb-server -p 9900 -U postgres)

echo "Waiting for PeerDB server on port 9900..."
until "${PEERDB[@]}" -c '\q' >/dev/null 2>&1; do
  sleep 2
done

echo "PeerDB is up! Creating peers and mirror..."

# peerdb-server can accept connections before the flow API/workers are ready,
# so retry the whole block for a while before giving up.
for attempt in $(seq 1 30); do
  if "${PEERDB[@]}" <<EOF
CREATE PEER IF NOT EXISTS postgres_peer FROM POSTGRES WITH (
    host = 'postgres',
    port = '5432',
    user = '${REPLICATOR_USER:-replicator}',
    password = '${REPLICATOR_PASSWORD:-changeme}',
    database = '${POSTGRES_DB:-ecommerce}'
);

CREATE PEER IF NOT EXISTS clickhouse_peer FROM CLICKHOUSE WITH (
    host = 'clickhouse',
    port = 9000,
    user = '${CLICKHOUSE_USER:-default}',
    password = '${CLICKHOUSE_PASSWORD:-changeme}',
    database = '${CLICKHOUSE_DB:-ecommerce}',
    disable_tls = true
);

CREATE MIRROR IF NOT EXISTS postgres_to_clickhouse
FROM postgres_peer TO clickhouse_peer
WITH TABLE MAPPING (
    public.categories:categories,
    public.products:products,
    public.customers:customers,
    public.orders:orders,
    public.order_items:order_items,
    public.payments:payments
)
WITH (
    do_initial_copy = true,
    publication_name = 'peerdb_pub',
    sync_interval = 10
);
EOF
  then
    echo "CDC setup completed!"
    exit 0
  fi
  echo "Attempt ${attempt}/30 failed, retrying in 5s..."
  sleep 5
done

echo "CDC setup failed after 30 attempts." >&2
exit 1
