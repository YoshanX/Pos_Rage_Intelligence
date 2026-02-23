-- ORDER 121: January 10
INSERT INTO "order" (order_id, customer_id, staff_id, courier_id, status_id, order_date, total_price)
VALUES (121, 2, 2, 2, 4, '2026-01-10', 0);

INSERT INTO order_item (order_id, product_id, quantity, price_at_sale)
SELECT 121, p.product_id, q.qty, p.current_price
FROM product p
JOIN (
    SELECT 5 AS product_id, 1 AS qty UNION ALL
    SELECT 12, 2 UNION ALL
    SELECT 44, 1
) q ON p.product_id = q.product_id;

UPDATE "order" SET total_price = (SELECT SUM(quantity * price_at_sale) FROM order_item WHERE order_id = 121) WHERE order_id = 121;