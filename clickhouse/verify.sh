#!/usr/bin/env bash
# Part 3 verification: changes made in Postgres show up as the final state of the row
# in ClickHouse (ReplacingMergeTree(_peerdb_version) + FINAL).
#
#   1. UPDATE via psql  -> SELECT ... FINAL returns the new value
#   2. DELETE via psql  -> FINAL row is marked _peerdb_is_deleted = 1
#   3. UPDATEs made by the generator -> same final state in both databases
#   4. Row counts, Postgres vs ClickHouse FINAL
#
# Usage (with the stack running, from anywhere):  ./clickhouse/verify.sh
# The output is also saved to clickhouse/verification/latest_run.txt for the report.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

OUT=clickhouse/verification/latest_run.txt
mkdir -p "$(dirname "$OUT")"
exec > >(tee "$OUT") 2>&1

pg()     { docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"; }
pg_val() { docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"; }
ch()     { docker compose exec -T clickhouse clickhouse-client -u "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" -d "$CLICKHOUSE_DB" --format PrettyCompactMonoBlock -q "$1"; }
ch_val() { docker compose exec -T clickhouse clickhouse-client -u "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" -d "$CLICKHOUSE_DB" -q "$1"; }
step()   { printf '\n$ %s\n' "$1"; }

# Polls a ClickHouse query until it returns 1 (max ~2 min).
wait_for_ch() {
  local start=$SECONDS
  for _ in $(seq 1 60); do
    if [ "$(ch_val "$1")" = "1" ]; then
      echo "-> replicated to ClickHouse after ~$((SECONDS - start))s"
      return 0
    fi
    sleep 2
  done
  echo "-> TIMEOUT: change not visible in ClickHouse after $((SECONDS - start))s" >&2
  return 1
}

echo "Run at: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

echo
echo "=================================================================="
echo " 1. UPDATE in Postgres -> SELECT ... FINAL in ClickHouse"
echo "=================================================================="
# The generator only ever updates customers.city, so email is safe to change here.
CUSTOMER_ID=$(pg_val "SELECT min(customer_id) FROM customers")
NEW_EMAIL="cdc-verify-$(date +%s)@example.com"

echo "--- BEFORE"
step "psql: SELECT customer_id, email, city, updated_at FROM customers WHERE customer_id = $CUSTOMER_ID"
pg "SELECT customer_id, email, city, updated_at FROM customers WHERE customer_id = $CUSTOMER_ID"
step "clickhouse: SELECT ... FROM customers FINAL WHERE customer_id = $CUSTOMER_ID"
ch "SELECT customer_id, email, city, updated_at, _peerdb_version, _peerdb_is_deleted FROM customers FINAL WHERE customer_id = $CUSTOMER_ID"

echo "--- UPDATE"
step "psql: UPDATE customers SET email = '$NEW_EMAIL', updated_at = now() WHERE customer_id = $CUSTOMER_ID"
pg "UPDATE customers SET email = '$NEW_EMAIL', updated_at = now() WHERE customer_id = $CUSTOMER_ID RETURNING customer_id, email, updated_at"
wait_for_ch "SELECT count() = 1 FROM customers FINAL WHERE customer_id = $CUSTOMER_ID AND email = '$NEW_EMAIL'"

echo "--- AFTER"
step "clickhouse (no FINAL): every stored version of the row, until a background merge collapses them"
ch "SELECT customer_id, email, city, updated_at, _peerdb_version, _peerdb_is_deleted FROM customers WHERE customer_id = $CUSTOMER_ID ORDER BY _peerdb_version"
step "clickhouse (FINAL): only the latest version"
ch "SELECT customer_id, email, city, updated_at, _peerdb_version, _peerdb_is_deleted FROM customers FINAL WHERE customer_id = $CUSTOMER_ID"

echo
echo "=================================================================="
echo " 2. DELETE in Postgres -> soft delete (_peerdb_is_deleted = 1)"
echo "=================================================================="
# The generator only deletes 'failed' payments, so a 'refunded' one won't be touched.
PAYMENT_ID=$(pg_val "SELECT min(payment_id) FROM payments WHERE payment_status = 'refunded'")
if [ -z "$PAYMENT_ID" ]; then
  echo "No refunded payment yet, skipping (let the generator run a bit longer)."
else
  echo "--- BEFORE"
  step "clickhouse: SELECT ... FROM payments FINAL WHERE payment_id = $PAYMENT_ID"
  ch "SELECT payment_id, order_id, payment_status, amount, updated_at, _peerdb_version, _peerdb_is_deleted FROM payments FINAL WHERE payment_id = $PAYMENT_ID"

  echo "--- DELETE"
  step "psql: DELETE FROM payments WHERE payment_id = $PAYMENT_ID"
  pg "DELETE FROM payments WHERE payment_id = $PAYMENT_ID RETURNING payment_id, payment_status"
  wait_for_ch "SELECT count() = 1 FROM payments FINAL WHERE payment_id = $PAYMENT_ID AND _peerdb_is_deleted = 1"

  echo "--- AFTER"
  step "clickhouse (FINAL): the latest version is the delete marker; non-key columns are not sent by Postgres on DELETE"
  ch "SELECT payment_id, order_id, payment_status, amount, updated_at, _peerdb_version, _peerdb_is_deleted FROM payments FINAL WHERE payment_id = $PAYMENT_ID"
  step "clickhouse (FINAL + filter): the row is gone for analytical queries"
  ch "SELECT count() AS rows_visible FROM payments FINAL WHERE payment_id = $PAYMENT_ID AND _peerdb_is_deleted = 0"
fi

echo
echo "=================================================================="
echo " 3. UPDATEs made by the generator -> same final state in ClickHouse"
echo "=================================================================="
# delivered/cancelled are terminal statuses, so the generator won't change these rows again.
ORDERS=$(pg_val "SELECT string_agg(order_id::text, ',') FROM (SELECT order_id FROM orders WHERE order_status IN ('delivered', 'cancelled') AND updated_at > order_date AND updated_at < now() - interval '30 seconds' ORDER BY updated_at DESC LIMIT 5) t")
if [ -z "$ORDERS" ]; then
  echo "No generator-updated orders in a terminal status yet, skipping."
else
  step "psql: last orders the generator moved to a terminal status"
  pg "SELECT order_id, order_status, order_date, updated_at FROM orders WHERE order_id IN ($ORDERS) ORDER BY order_id"
  step "clickhouse (FINAL): same orders"
  ch "SELECT order_id, order_status, order_date, updated_at, _peerdb_is_deleted FROM orders FINAL WHERE order_id IN ($ORDERS) ORDER BY order_id"
  PG_ROWS=$(pg_val "SELECT order_id || '|' || order_status FROM orders WHERE order_id IN ($ORDERS) ORDER BY order_id")
  CH_ROWS=$(ch_val "SELECT concat(toString(order_id), '|', order_status) FROM orders FINAL WHERE order_id IN ($ORDERS) AND _peerdb_is_deleted = 0 ORDER BY order_id")
  if [ "$PG_ROWS" = "$CH_ROWS" ]; then
    echo "-> MATCH: order_status is identical in Postgres and ClickHouse FINAL"
  else
    echo "-> MISMATCH between Postgres and ClickHouse FINAL" >&2
  fi
fi

echo
echo "=================================================================="
echo " 4. Row counts: Postgres vs ClickHouse (raw vs FINAL)"
echo "=================================================================="
echo "The generator keeps writing, so live tables can differ by the rows still in flight."
printf '\n%-12s %10s %14s %16s\n' "table" "postgres" "clickhouse_raw" "clickhouse_final"
for t in categories products customers orders order_items payments; do
  printf '%-12s %10s %14s %16s\n' "$t" \
    "$(pg_val "SELECT count(*) FROM $t")" \
    "$(ch_val "SELECT count() FROM $t")" \
    "$(ch_val "SELECT count() FROM $t FINAL WHERE _peerdb_is_deleted = 0")"
done
