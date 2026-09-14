WITH order_totals AS (
    SELECT
        o.order_id,
        COALESCE(c.country, 'Unknown') AS country,
        SUM(oi.quantity * oi.unit_price)::numeric(20, 2) AS order_total
    FROM orders AS o
    INNER JOIN customers AS c ON c.customer_id = o.customer_id
    INNER JOIN order_items AS oi ON oi.order_id = o.order_id
    WHERE o.order_date < TIMESTAMPTZ '{{CUTOFF}}'
      AND o.updated_at < TIMESTAMPTZ '{{CUTOFF}}'
      AND o.order_status = 'delivered'
    GROUP BY o.order_id, COALESCE(c.country, 'Unknown')
)
SELECT
    country,
    COUNT(*) AS order_count,
    ROUND(AVG(order_total), 2)::numeric(20, 2) AS average_order_value
FROM order_totals
GROUP BY country
ORDER BY average_order_value DESC, country;
