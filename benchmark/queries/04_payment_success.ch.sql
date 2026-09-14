SELECT
    p.payment_method,
    count() AS total_payments,
    countIf(p.payment_status = 'completed') AS completed_payments,
    countIf(p.payment_status = 'failed') AS failed_payments,
    countIf(p.payment_status = 'refunded') AS refunded_payments,
    CAST(round(100.0 * countIf(p.payment_status = 'completed') / nullIf(count(), 0), 2), 'Decimal(10, 2)') AS success_rate
FROM ecommerce.payments AS p FINAL
INNER JOIN ecommerce.orders AS o FINAL ON o.order_id = p.order_id
WHERE o.order_status = 'delivered'
  AND p.payment_status IN ('completed', 'refunded')
  AND o.order_date < toDateTime64('{{CUTOFF}}', 6, 'UTC')
  AND o.updated_at < toDateTime64('{{CUTOFF}}', 6, 'UTC')
  AND p.updated_at < toDateTime64('{{CUTOFF}}', 6, 'UTC')
  AND p._peerdb_is_deleted = 0
  AND o._peerdb_is_deleted = 0
GROUP BY p.payment_method
ORDER BY success_rate DESC, p.payment_method;
