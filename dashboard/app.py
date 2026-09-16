"""Live CDC metrics sourced from the ClickHouse ecommerce mirror."""

import os
import time

import clickhouse_connect
import pandas as pd
import streamlit as st


REFRESH_SECONDS = 5


def get_client():
    """Create a client using the Compose service hostname and root .env values."""
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123")),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        database=os.getenv("CLICKHOUSE_DB", "ecommerce"),
    )


def query_frame(client, query: str) -> pd.DataFrame:
    result = client.query(query)
    return pd.DataFrame(result.result_rows, columns=result.column_names)


ORDER_COUNT_QUERY = """
SELECT count() AS order_count
FROM ecommerce.orders FINAL
WHERE _peerdb_is_deleted = 0
"""

REVENUE_QUERY = """
SELECT
    toDate(o.order_date) AS order_day,
    round(sum(oi.quantity * oi.unit_price), 2) AS revenue
FROM ecommerce.order_items AS oi FINAL
INNER JOIN ecommerce.orders AS o FINAL ON o.order_id = oi.order_id
WHERE oi._peerdb_is_deleted = 0
  AND o._peerdb_is_deleted = 0
GROUP BY order_day
ORDER BY order_day
"""

STATUS_QUERY = """
SELECT
    order_status,
    count() AS orders
FROM ecommerce.orders FINAL
WHERE _peerdb_is_deleted = 0
GROUP BY order_status
ORDER BY orders DESC, order_status
"""


st.set_page_config(page_title="E-commerce CDC dashboard", page_icon="📈", layout="wide")

st.title("E-commerce CDC dashboard")
st.caption(
    f"ClickHouse metrics refresh every {REFRESH_SECONDS} seconds. "
    "Queries use FINAL and exclude CDC soft deletes."
)

try:
    client = get_client()
    order_count = query_frame(client, ORDER_COUNT_QUERY).iloc[0]["order_count"]
    revenue = query_frame(client, REVENUE_QUERY)
    statuses = query_frame(client, STATUS_QUERY)
except Exception as error:
    st.error("Waiting for ClickHouse data. The dashboard will retry automatically.")
    st.exception(error)
    time.sleep(REFRESH_SECONDS)
    st.rerun()

st.metric("Live orders", f"{int(order_count):,}")

left, right = st.columns(2)
with left:
    st.subheader("Revenue over time")
    if revenue.empty:
        st.info("No order items have reached ClickHouse yet.")
    else:
        st.line_chart(revenue.set_index("order_day"), y="revenue")

with right:
    st.subheader("Order-status breakdown")
    if statuses.empty:
        st.info("No orders have reached ClickHouse yet.")
    else:
        st.bar_chart(statuses.set_index("order_status"), y="orders")

st.caption("Last rendered: " + pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M:%S UTC"))

time.sleep(REFRESH_SECONDS)
st.rerun()
