"""Continuous INSERT/UPDATE/DELETE generator for the e-commerce schema.

Seeds reference data (categories, products, customers), then loops forever
(or for GEN_DURATION_SECONDS) firing a weighted mix of operations at roughly
GEN_RATE_PER_SEC events/sec, so PeerDB/ClickHouse (Part 2/3) have a live CDC
stream to replicate and Part 4/5 have live data to query against.
"""
import os
import random
import signal
import sys
import time

import psycopg2
import psycopg2.extras
from faker import Faker

fake = Faker()

DB_CONFIG = dict(
    host=os.environ.get("PGHOST", "postgres"),
    port=os.environ.get("PGPORT", "5432"),
    dbname=os.environ.get("POSTGRES_DB", "ecommerce"),
    user=os.environ.get("POSTGRES_USER", "postgres"),
    password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
)

RATE_PER_SEC = float(os.environ.get("GEN_RATE_PER_SEC", "20"))
DURATION_SECONDS = int(os.environ.get("GEN_DURATION_SECONDS", "0"))  # 0 = run forever
SEED_CATEGORIES = int(os.environ.get("GEN_SEED_CATEGORIES", "8"))
SEED_PRODUCTS = int(os.environ.get("GEN_SEED_PRODUCTS", "200"))
SEED_CUSTOMERS = int(os.environ.get("GEN_SEED_CUSTOMERS", "500"))

ORDER_STATUS_FLOW = {
    "pending": ["paid", "cancelled"],
    "paid": ["shipped"],
    "shipped": ["delivered"],
}
PAYMENT_STATUS_FLOW = {
    "pending": ["completed", "failed"],
    "failed": ["refunded"],
}
PAYMENT_METHODS = ["credit_card", "debit_card", "paypal", "cash"]

stop_requested = False


def _handle_signal(signum, frame):
    global stop_requested
    stop_requested = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def wait_for_db(max_attempts=30, delay=2):
    for attempt in range(1, max_attempts + 1):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            conn.close()
            print("Connected to Postgres.", flush=True)
            return
        except psycopg2.OperationalError as exc:
            print(f"[{attempt}/{max_attempts}] Postgres not ready yet ({exc}); retrying...", flush=True)
            time.sleep(delay)
    raise SystemExit("Could not connect to Postgres, giving up.")


def seed_reference_data(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM categories")
        if cur.fetchone()[0] > 0:
            print("Reference data already seeded, skipping.", flush=True)
            return

        category_names = [
            "Electronics", "Home & Kitchen", "Books", "Sports & Outdoors",
            "Toys & Games", "Beauty & Personal Care", "Grocery", "Clothing",
        ][:SEED_CATEGORIES]
        category_ids = []
        for name in category_names:
            cur.execute(
                "INSERT INTO categories (category_name) VALUES (%s) RETURNING category_id",
                (name,),
            )
            category_ids.append(cur.fetchone()[0])

        products = []
        for _ in range(SEED_PRODUCTS):
            products.append((
                random.choice(category_ids),
                fake.unique.bothify(text="SKU-########"),
                fake.catch_phrase(),
                round(random.uniform(5, 500), 2),
            ))
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO products (category_id, sku, product_name, price) VALUES %s",
            products,
        )

        customers = []
        for _ in range(SEED_CUSTOMERS):
            customers.append((
                fake.name(),
                fake.unique.email(),
                fake.city(),
                fake.country(),
            ))
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO customers (full_name, email, city, country) VALUES %s",
            customers,
        )
    conn.commit()
    print(f"Seeded {len(category_names)} categories, {SEED_PRODUCTS} products, "
          f"{SEED_CUSTOMERS} customers.", flush=True)


def fetch_ids(conn, table, id_column, where=""):
    with conn.cursor() as cur:
        cur.execute(f"SELECT {id_column} FROM {table} {where}")
        return [row[0] for row in cur.fetchall()]


def op_create_order(conn, stats):
    with conn.cursor() as cur:
        cur.execute("SELECT customer_id FROM customers ORDER BY random() LIMIT 1")
        customer_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO orders (customer_id, order_status) VALUES (%s, 'pending') "
            "RETURNING order_id",
            (customer_id,),
        )
        order_id = cur.fetchone()[0]
        stats["insert"] += 1

        cur.execute(
            "SELECT product_id, price FROM products ORDER BY random() LIMIT %s",
            (random.randint(1, 5),),
        )
        items = cur.fetchall()
        for product_id, price in items:
            quantity = random.randint(1, 4)
            cur.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
                "VALUES (%s, %s, %s, %s)",
                (order_id, product_id, quantity, price),
            )
            stats["insert"] += 1

        total = sum(price * random.randint(1, 4) for _, price in items)
        cur.execute(
            "INSERT INTO payments (order_id, payment_method, amount, payment_status) "
            "VALUES (%s, %s, %s, 'pending')",
            (order_id, random.choice(PAYMENT_METHODS), round(total, 2)),
        )
        stats["insert"] += 1
    conn.commit()


def op_advance_order_status(conn, stats):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT order_id, order_status FROM orders "
            "WHERE order_status = ANY(%s) ORDER BY random() LIMIT 1",
            (list(ORDER_STATUS_FLOW.keys()),),
        )
        row = cur.fetchone()
        if not row:
            return
        order_id, current_status = row
        next_status = random.choice(ORDER_STATUS_FLOW[current_status])
        cur.execute(
            "UPDATE orders SET order_status = %s, updated_at = now() WHERE order_id = %s",
            (next_status, order_id),
        )
        stats["update"] += 1
    conn.commit()


def op_advance_payment_status(conn, stats):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT payment_id, payment_status FROM payments "
            "WHERE payment_status = ANY(%s) ORDER BY random() LIMIT 1",
            (list(PAYMENT_STATUS_FLOW.keys()),),
        )
        row = cur.fetchone()
        if not row:
            return
        payment_id, current_status = row
        next_status = random.choice(PAYMENT_STATUS_FLOW[current_status])
        paid_at_clause = ", paid_at = now()" if next_status == "completed" else ""
        cur.execute(
            f"UPDATE payments SET payment_status = %s, updated_at = now(){paid_at_clause} "
            f"WHERE payment_id = %s",
            (next_status, payment_id),
        )
        stats["update"] += 1
    conn.commit()


def op_update_customer_profile(conn, stats):
    with conn.cursor() as cur:
        cur.execute("SELECT customer_id FROM customers ORDER BY random() LIMIT 1")
        row = cur.fetchone()
        if not row:
            return
        cur.execute(
            "UPDATE customers SET city = %s, updated_at = now() WHERE customer_id = %s",
            (fake.city(), row[0]),
        )
        stats["update"] += 1
    conn.commit()


def op_update_product_price(conn, stats):
    with conn.cursor() as cur:
        cur.execute("SELECT product_id, price FROM products ORDER BY random() LIMIT 1")
        row = cur.fetchone()
        if not row:
            return
        product_id, price = row
        new_price = max(1, round(float(price) * random.uniform(0.9, 1.1), 2))
        cur.execute(
            "UPDATE products SET price = %s, updated_at = now() WHERE product_id = %s",
            (new_price, product_id),
        )
        stats["update"] += 1
    conn.commit()


def op_delete_order_item(conn, stats):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT oi.order_item_id FROM order_items oi "
            "JOIN orders o ON o.order_id = oi.order_id "
            "WHERE o.order_status = 'pending' ORDER BY random() LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return
        cur.execute("DELETE FROM order_items WHERE order_item_id = %s", (row[0],))
        stats["delete"] += 1
    conn.commit()


def op_delete_stale_payment(conn, stats):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT payment_id FROM payments WHERE payment_status = 'failed' "
            "ORDER BY random() LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return
        cur.execute("DELETE FROM payments WHERE payment_id = %s", (row[0],))
        stats["delete"] += 1
    conn.commit()


# (operation, relative weight) -- weighted towards creating new orders since that's
# the primary "traffic" of an e-commerce store; updates/deletes keep the CDC UPDATE
# and DELETE paths exercised.
OPERATIONS = [
    (op_create_order, 40),
    (op_advance_order_status, 25),
    (op_advance_payment_status, 20),
    (op_update_customer_profile, 5),
    (op_update_product_price, 5),
    (op_delete_order_item, 3),
    (op_delete_stale_payment, 2),
]
WEIGHTS = [w for _, w in OPERATIONS]
FUNCS = [f for f, _ in OPERATIONS]


def main():
    wait_for_db()
    conn = psycopg2.connect(**DB_CONFIG)
    seed_reference_data(conn)

    stats = {"insert": 0, "update": 0, "delete": 0}
    start = time.time()
    last_log = start
    interval = 1.0 / RATE_PER_SEC if RATE_PER_SEC > 0 else 0

    print(f"Starting generator: ~{RATE_PER_SEC} events/sec, "
          f"duration={'infinite' if DURATION_SECONDS == 0 else DURATION_SECONDS}s", flush=True)

    while not stop_requested:
        if DURATION_SECONDS and (time.time() - start) >= DURATION_SECONDS:
            break

        op = random.choices(FUNCS, weights=WEIGHTS, k=1)[0]
        try:
            op(conn, stats)
        except Exception as exc:  # keep the loop alive across transient errors
            print(f"Operation {op.__name__} failed: {exc}", flush=True)
            conn.rollback()

        now = time.time()
        if now - last_log >= 10:
            total = sum(stats.values())
            elapsed = now - start
            print(f"[{elapsed:.0f}s] total_ops={total} "
                  f"insert={stats['insert']} update={stats['update']} delete={stats['delete']} "
                  f"({total / elapsed:.1f} ops/sec avg)", flush=True)
            last_log = now

        if interval:
            time.sleep(interval)

    total = sum(stats.values())
    print(f"Stopping. Final totals: total_ops={total} {stats}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
