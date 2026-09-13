#!/bin/bash
# Sets up the replication role + publication PeerDB (Part 2, Valeria) will read from.
# Runs as part of docker-entrypoint-initdb.d, after 01_schema.sql.
# REPLICATOR_USER / REPLICATOR_PASSWORD come from .env via docker-compose's env_file.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO
    \$\$
    BEGIN
       IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${REPLICATOR_USER}') THEN
          CREATE ROLE ${REPLICATOR_USER} WITH LOGIN REPLICATION PASSWORD '${REPLICATOR_PASSWORD}';
       END IF;
    END
    \$\$;

    GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${REPLICATOR_USER};
    GRANT USAGE ON SCHEMA public TO ${REPLICATOR_USER};
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${REPLICATOR_USER};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ${REPLICATOR_USER};

    CREATE PUBLICATION peerdb_pub FOR TABLE
        categories, products, customers, orders, order_items, payments;
EOSQL

echo "Replication role '${REPLICATOR_USER}' and publication 'peerdb_pub' created."
