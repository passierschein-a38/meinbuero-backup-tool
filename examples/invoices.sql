-- Every invoice with customer and amounts.
SELECT i.INVNO                              AS invoice_no,
       SUBSTR(i.INVDATE, 1, 10)             AS invoice_date,
       cu.CUSTNO                            AS customer_no,
       TRIM(cu.NAME1 || ' ' || COALESCE(cu.NAME2, '')) AS customer,
       ROUND(i.TOTALNET, 2)                 AS net,
       ROUND(i.TOTALGROSS - i.TOTALNET, 2)  AS vat,
       ROUND(i.TOTALGROSS, 2)               AS gross
  FROM MOV_INVOICES i
  JOIN BAS_CUSTOMERS cu ON cu.ID = i.CUSTID
 ORDER BY i.INVDATE, i.INVNO;
