SELECT
    toDate(toStartOfMonth(o.order_date)) AS order_month,
    c.category_name,
    CAST(sum(oi.quantity * oi.unit_price), 'Decimal(20, 2)') AS revenue
FROM ecommerce.orders AS o FINAL
INNER JOIN ecommerce.order_items AS oi FINAL ON oi.order_id = o.order_id
INNER JOIN ecommerce.products AS p FINAL ON p.product_id = oi.product_id
INNER JOIN ecommerce.categories AS c FINAL ON c.category_id = p.category_id
WHERE o.order_date < toDateTime64('{{CUTOFF}}', 6, 'UTC')
  AND o.updated_at < toDateTime64('{{CUTOFF}}', 6, 'UTC')
  AND o.order_status = 'delivered'
  AND o._peerdb_is_deleted = 0
  AND oi._peerdb_is_deleted = 0
  AND p._peerdb_is_deleted = 0
  AND c._peerdb_is_deleted = 0
GROUP BY order_month, c.category_name
ORDER BY order_month, revenue DESC, c.category_name;
