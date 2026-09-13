-- ClickHouse target schema for the PeerDB mirror postgres_to_clickhouse (Part 3).
-- See clickhouse/README.md for the reasoning behind these decisions.
--
-- * Column names/types match exactly what PeerDB writes (PEERDB_NULLABLE=true), so
--   PeerDB reuses these tables instead of creating its own (CREATE TABLE IF NOT EXISTS).
-- * Postgres UPDATEs and DELETEs arrive as new rows with a higher _peerdb_version.
--   ReplacingMergeTree keeps the highest version per ORDER BY key (the Postgres PK),
--   and queries use FINAL to see only that version.
-- * The version column is _peerdb_version, not updated_at: on DELETE Postgres only
--   sends the primary key, so the delete row carries updated_at = 1970-01-01 and would
--   lose against the previous version. categories has no updated_at at all.
-- * Deletes are soft: _peerdb_is_deleted = 1. Analytical queries must filter
--   WHERE _peerdb_is_deleted = 0.
--
-- Runs only when the clickhouse_data volume is empty (docker compose down -v to re-run).

CREATE DATABASE IF NOT EXISTS ecommerce;

CREATE TABLE IF NOT EXISTS ecommerce.categories
(
    `category_id`        Int32,
    `category_name`      String,
    `created_at`         DateTime64(6),
    `_peerdb_synced_at`  DateTime64(9) DEFAULT now64(),
    `_peerdb_is_deleted` UInt8,
    `_peerdb_version`    UInt64
)
ENGINE = ReplacingMergeTree(_peerdb_version)
ORDER BY (category_id);

CREATE TABLE IF NOT EXISTS ecommerce.products
(
    `product_id`         Int32,
    `category_id`        Int32,
    `sku`                String,
    `product_name`       String,
    `price`              Decimal(10, 2),
    `created_at`         DateTime64(6),
    `updated_at`         DateTime64(6),
    `_peerdb_synced_at`  DateTime64(9) DEFAULT now64(),
    `_peerdb_is_deleted` UInt8,
    `_peerdb_version`    UInt64
)
ENGINE = ReplacingMergeTree(_peerdb_version)
ORDER BY (product_id);

CREATE TABLE IF NOT EXISTS ecommerce.customers
(
    `customer_id`        Int32,
    `full_name`          String,
    `email`              String,
    `city`               Nullable(String),
    `country`            Nullable(String),
    `created_at`         DateTime64(6),
    `updated_at`         DateTime64(6),
    `_peerdb_synced_at`  DateTime64(9) DEFAULT now64(),
    `_peerdb_is_deleted` UInt8,
    `_peerdb_version`    UInt64
)
ENGINE = ReplacingMergeTree(_peerdb_version)
ORDER BY (customer_id);

CREATE TABLE IF NOT EXISTS ecommerce.orders
(
    `order_id`           Int32,
    `customer_id`        Int32,
    `order_status`       String,
    `order_date`         DateTime64(6),
    `updated_at`         DateTime64(6),
    `_peerdb_synced_at`  DateTime64(9) DEFAULT now64(),
    `_peerdb_is_deleted` UInt8,
    `_peerdb_version`    UInt64
)
ENGINE = ReplacingMergeTree(_peerdb_version)
ORDER BY (order_id);

CREATE TABLE IF NOT EXISTS ecommerce.order_items
(
    `order_item_id`      Int32,
    `order_id`           Int32,
    `product_id`         Int32,
    `quantity`           Int32,
    `unit_price`         Decimal(10, 2),
    `updated_at`         DateTime64(6),
    `_peerdb_synced_at`  DateTime64(9) DEFAULT now64(),
    `_peerdb_is_deleted` UInt8,
    `_peerdb_version`    UInt64
)
ENGINE = ReplacingMergeTree(_peerdb_version)
ORDER BY (order_item_id);

CREATE TABLE IF NOT EXISTS ecommerce.payments
(
    `payment_id`         Int32,
    `order_id`           Int32,
    `payment_method`     String,
    `amount`             Decimal(10, 2),
    `payment_status`     String,
    `paid_at`            Nullable(DateTime64(6)),
    `updated_at`         DateTime64(6),
    `_peerdb_synced_at`  DateTime64(9) DEFAULT now64(),
    `_peerdb_is_deleted` UInt8,
    `_peerdb_version`    UInt64
)
ENGINE = ReplacingMergeTree(_peerdb_version)
ORDER BY (payment_id);
