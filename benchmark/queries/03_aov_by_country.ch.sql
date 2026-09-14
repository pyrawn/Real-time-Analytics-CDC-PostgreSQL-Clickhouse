WITH order_totals AS (
    SELECT
        o.order_id,
        ifNull(c.country, 'Unknown') AS country,
        CAST(sum(oi.quantity * oi.unit_price), 'Decimal(20, 2)') AS order_total
    FROM ecommerce.orders AS o FINAL
    INNER JOIN ecommerce.customers AS c FINAL ON c.customer_id = o.customer_id
    INNER JOIN ecommerce.order_items AS oi FINAL ON oi.order_id = o.order_id
    WHERE o.order_date < toDateTime64('{{CUTOFF}}', 6, 'UTC')
      AND o.updated_at < toDateTime64('{{CUTOFF}}', 6, 'UTC')
      AND o.order_status = 'delivered'
      AND o._peerdb_is_deleted = 0
      AND c._peerdb_is_deleted = 0
      AND oi._peerdb_is_deleted = 0
    GROUP BY o.order_id, country
)
SELECT
    country,
    count() AS order_count,
    CAST(round(avg(order_total), 2), 'Decimal(20, 2)') AS average_order_value
FROM order_totals
GROUP BY country
ORDER BY average_order_value DESC, country;
