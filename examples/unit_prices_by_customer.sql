-- Which unit prices (e.g. hourly rates) were charged to which customer.
-- Hours are often entered with the default unit "Stk." instead of "Std.",
-- so look at the price level as well as the unit.
SELECT TRIM(cu.NAME1 || ' ' || COALESCE(cu.NAME2, '')) AS customer,
       u.LABEL                              AS unit,
       ROUND(op.PRICENET, 2)                AS unit_price_net,
       COUNT(*)                             AS invoice_lines,
       ROUND(SUM(ip.AMOUNT), 2)             AS quantity,
       ROUND(SUM(ip.TOTAL), 2)              AS net_billed,
       SUBSTR(MIN(i.INVDATE), 1, 4)         AS first_year,
       SUBSTR(MAX(i.INVDATE), 1, 4)         AS last_year
  FROM MOV_INVOICES_POSITIONS ip
  JOIN MOV_INVOICES i            ON i.ID = ip.INVID
  JOIN BAS_CUSTOMERS cu          ON cu.ID = i.CUSTID
  JOIN MOV_ORDERS_POSITIONS op   ON op.ID = ip.ORDPOSID
  LEFT JOIN SUP_ARTICLES_UNITS u ON u.ID = op.UNITCODE
 GROUP BY cu.ID, u.LABEL, unit_price_net
 ORDER BY customer, net_billed DESC;
