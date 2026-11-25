-- All customers and suppliers with address, contact data and invoice totals.
-- IDs <= 0 are internal placeholder records such as "(diverse Kunden)".
SELECT cu.CUSTNO                                   AS customer_no,
       CASE cu.CUSTKIND WHEN 1 THEN 'supplier' ELSE 'customer' END AS kind,
       TRIM(cu.NAME1 || ' ' || COALESCE(cu.NAME2, '')) AS name,
       TRIM(COALESCE(cu.NAME3, ''))                AS addition,
       TRIM(COALESCE(cu.STREET, ''))               AS street,
       TRIM(COALESCE(cu.ZIPCODE, ''))              AS zip,
       TRIM(COALESCE(cu.CITY, ''))                 AS city,
       cu.COUNTRY                                  AS country,
       TRIM(COALESCE(cu.PHONE1, ''))               AS phone,
       TRIM(COALESCE(cu.EMAIL, ''))                AS email,
       TRIM(COALESCE(cu.WEBSITE, ''))              AS website,
       (SELECT GROUP_CONCAT(TRIM(COALESCE(k.CONTNAME2, '') || ' ' || COALESCE(k.CONTNAME1, '')), '; ')
          FROM BAS_CUSTOMERS_CONTACTS k
         WHERE k.CUSTID = cu.ID)                   AS contact_persons,
       COUNT(i.ID)                                 AS invoices,
       ROUND(COALESCE(SUM(i.TOTALNET), 0), 2)      AS net_total,
       ROUND(COALESCE(SUM(i.TOTALGROSS), 0), 2)    AS gross_total,
       SUBSTR(MIN(i.INVDATE), 1, 10)               AS first_invoice,
       SUBSTR(MAX(i.INVDATE), 1, 10)               AS last_invoice
  FROM BAS_CUSTOMERS cu
  LEFT JOIN MOV_INVOICES i ON i.CUSTID = cu.ID
 WHERE cu.ID > 0
 GROUP BY cu.ID
 ORDER BY net_total DESC;
