-- Every invoice line with quantity, unit and unit price.
-- Invoice lines only hold quantity and total; text, unit and price come from
-- the order line they were created from (ORDPOSID).
SELECT i.INVNO                              AS invoice_no,
       SUBSTR(i.INVDATE, 1, 10)             AS invoice_date,
       TRIM(cu.NAME1 || ' ' || COALESCE(cu.NAME2, '')) AS customer,
       ip.POSID                             AS line,
       ip.AMOUNT                            AS quantity,
       u.LABEL                              AS unit,
       ROUND(op.PRICENET, 2)                AS unit_price_net,
       op.DISCPERC                          AS discount_percent,
       ROUND(ip.TOTAL, 2)                   AS line_total_net,
       REPLACE(REPLACE(op.ARTDESCR, CHAR(13), ''), CHAR(10), ' | ') AS description
  FROM MOV_INVOICES_POSITIONS ip
  JOIN MOV_INVOICES i               ON i.ID = ip.INVID
  JOIN BAS_CUSTOMERS cu             ON cu.ID = i.CUSTID
  LEFT JOIN MOV_ORDERS_POSITIONS op ON op.ID = ip.ORDPOSID
  LEFT JOIN SUP_ARTICLES_UNITS u    ON u.ID = op.UNITCODE
 ORDER BY i.INVDATE, i.INVNO, ip.POSID;
