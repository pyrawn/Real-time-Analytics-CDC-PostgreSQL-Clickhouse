#!/bin/bash

PG_PWD="${REPLICATOR_PASSWORD:-changeme}"
CH_PWD="${CLICKHOUSE_PASSWORD:-changeme}"

echo "Waiting for PeerDB server on port 9900..."
until psql -h peerdb-server -p 9900 -U postgres -c '\q' >/dev/null 2>&1; do
  sleep 2
done

echo "PeerDB is up! Creating peers and mirror..."

psql -h peerdb-server -p 9900 -U postgres <<EOF
CREATE PEER IF NOT EXISTS postgres_peer FROM postgres (
    host = 'postgres',
    port = 5432,
    user = 'replicator',
    password = '${PG_PWD}',
    database = 'ecommerce'
);

CREATE PEER IF NOT EXISTS clickhouse_peer FROM clickhouse (
    host = 'clickhouse',
    port = 9000,
    user = 'default',
    password = '${CH_PWD}',
    database = 'ecommerce'
);

CREATE MIRROR IF NOT EXISTS postgres_to_clickhouse FROM postgres_peer TO clickhouse_peer WITH TABLE MAPPING (
    public.categories:categories,
    public.products:products,
    public.customers:customers,
    public.orders:orders,
    public.order_items:order_items,
    public.payments:payments
) WITH (
    publication_name = 'peerdb_pub'
);
EOF

echo "CDC setup completed!"
