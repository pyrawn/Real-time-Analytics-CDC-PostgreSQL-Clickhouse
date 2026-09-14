SELECT
    p.payment_method,
    COUNT(*) AS total_payments,
    COUNT(*) FILTER (WHERE p.payment_status = 'completed') AS completed_payments,
    COUNT(*) FILTER (WHERE p.payment_status = 'failed') AS failed_payments,
    COUNT(*) FILTER (WHERE p.payment_status = 'refunded') AS refunded_payments,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE p.payment_status = 'completed') / NULLIF(COUNT(*), 0),
        2
    )::numeric(10, 2) AS success_rate
FROM payments AS p
INNER JOIN orders AS o ON o.order_id = p.order_id
WHERE o.order_status = 'delivered'
  AND p.payment_status IN ('completed', 'refunded')
  AND o.order_date < TIMESTAMPTZ '{{CUTOFF}}'
  AND o.updated_at < TIMESTAMPTZ '{{CUTOFF}}'
  AND p.updated_at < TIMESTAMPTZ '{{CUTOFF}}'
GROUP BY p.payment_method
ORDER BY success_rate DESC, p.payment_method;
