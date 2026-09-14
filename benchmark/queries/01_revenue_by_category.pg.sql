SELECT
    date_trunc('month', o.order_date)::date AS order_month,
    c.category_name,
    SUM(oi.quantity * oi.unit_price)::numeric(20, 2) AS revenue
FROM orders AS o
INNER JOIN order_items AS oi ON oi.order_id = o.order_id
INNER JOIN products AS p ON p.product_id = oi.product_id
INNER JOIN categories AS c ON c.category_id = p.category_id
WHERE o.order_date < TIMESTAMPTZ '{{CUTOFF}}'
  AND o.updated_at < TIMESTAMPTZ '{{CUTOFF}}'
  AND o.order_status = 'delivered'
GROUP BY 1, 2
ORDER BY 1, 3 DESC, 2;
