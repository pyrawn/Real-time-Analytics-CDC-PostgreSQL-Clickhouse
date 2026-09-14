SELECT
    p.product_id,
    p.product_name,
    SUM(oi.quantity) AS units_sold,
    SUM(oi.quantity * oi.unit_price)::numeric(20, 2) AS revenue
FROM orders AS o
INNER JOIN order_items AS oi ON oi.order_id = o.order_id
INNER JOIN products AS p ON p.product_id = oi.product_id
WHERE o.order_date < TIMESTAMPTZ '{{CUTOFF}}'
  AND o.updated_at < TIMESTAMPTZ '{{CUTOFF}}'
  AND o.order_status = 'delivered'
GROUP BY p.product_id, p.product_name
ORDER BY revenue DESC, p.product_id
LIMIT 10;
