-- Number of invoices and invoiced amounts per customer and year.
SELECT cu.CUSTNO                            AS customer_no,
       TRIM(cu.NAME1 || ' ' || COALESCE(cu.NAME2, '')) AS customer,
       SUBSTR(i.INVDATE, 1, 4)              AS year,
       COUNT(*)                             AS invoices,
       ROUND(SUM(i.TOTALNET), 2)            AS net,
       ROUND(SUM(i.TOTALGROSS), 2)          AS gross
  FROM MOV_INVOICES i
  JOIN BAS_CUSTOMERS cu ON cu.ID = i.CUSTID
 GROUP BY cu.ID, year
 ORDER BY customer, year;
