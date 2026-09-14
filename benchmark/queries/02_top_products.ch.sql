SELECT
    p.product_id,
    p.product_name,
    sum(oi.quantity) AS units_sold,
    CAST(sum(oi.quantity * oi.unit_price), 'Decimal(20, 2)') AS revenue
FROM ecommerce.orders AS o FINAL
INNER JOIN ecommerce.order_items AS oi FINAL ON oi.order_id = o.order_id
INNER JOIN ecommerce.products AS p FINAL ON p.product_id = oi.product_id
WHERE o.order_date < toDateTime64('{{CUTOFF}}', 6, 'UTC')
  AND o.updated_at < toDateTime64('{{CUTOFF}}', 6, 'UTC')
  AND o.order_status = 'delivered'
  AND o._peerdb_is_deleted = 0
  AND oi._peerdb_is_deleted = 0
  AND p._peerdb_is_deleted = 0
GROUP BY p.product_id, p.product_name
ORDER BY revenue DESC, p.product_id
LIMIT 10;
