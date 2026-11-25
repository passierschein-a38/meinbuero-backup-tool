# meinbuero-backup-tool

A simple tool to access old backups of WISO / Buhl "Mein Büro" (`.mfb` files)
without the program itself, for example when the old version is no longer
installed and the current version refuses to open the backup.

It unpacks the backup, restores the databases and exports every table to
SQLite and CSV. Everything runs in a Docker container; the backup file is
only read, never changed.

[Deutsche Beschreibung](#deutsch) · [Technical details](#technical-details)

This is an unofficial project. It is not affiliated with or endorsed by
Buhl Data Service GmbH; "WISO" and "Mein Büro" are their trademarks.

## Usage (macOS / Linux, Docker required)

    ./mb build                              # build the image once
    ./mb info  "backup.mfb"                 # show what is inside
    ./mb all   "backup.mfb" [outdir]        # unpack + restore + export
    ./mb serve outdir                       # browse at http://localhost:8001
    ./mb sql   outdir 1                     # Firebird SQL shell for Mandant 1
    ./mb query outdir file.sql [mandant]    # run a query, CSV on stdout

`all` accepts `--views` (also export the database views, prefixed `V_`) and
`--csv-intl` (comma separator, decimal point) after the output folder.
Without an output folder, `<backup>_extracted` next to the backup is used.

## Output

    outdir/
      files/              the unpacked archive: Archiv/ (PDFs of issued documents),
                          Dokumente/, Reports/ (print templates), MB.ini ...
      db/mandantN.fdb     restored Firebird 3 databases
      export/
        mandantN.sqlite   all tables in one SQLite file
        mandantN_csv/     one CSV per non-empty table (UTF-8, ";" separated)
        mandantN_tables.txt   company name and row count per table
      nested_backups/     same structure for any .mfb found inside the backup

## Main tables

| Table | Content |
|---|---|
| BAS_COMPANY | own company (name of the Mandant) |
| BAS_CUSTOMERS, BAS_CUSTOMERS_CONTACTS | customers / suppliers and contacts |
| BAS_ARTICLES, BAS_ARTICLES_PRICES | articles |
| MOV_ORDERS(+_POSITIONS) | offers and orders |
| MOV_DELIVERIES(+_POSITIONS) | delivery notes |
| MOV_INVOICES(+_POSITIONS) | invoices and credit notes |
| MOV_PAYMENTS, MOV_BANKINGPAYMENTS | payments and bank transactions |
| MOV_FINACC_ACCRECORDS, BAS_FINACC_PLAN | bookings and chart of accounts |

## Examples: customers and invoices

The `examples/` folder holds ready-made queries for the exported SQLite
files. `./mb query` runs one and prints CSV (German Excel style: `;` and
decimal comma; add `--csv-intl` for `,` and decimal point). The Mandant
number defaults to 1.

    # 1. unpack the backup once
    ./mb all "Datensicherung.mfb" out

    # 2. customer list with address, contacts, invoice count and totals
    ./mb query out examples/customers.sql > customers.csv

    # 3. all invoices with net, VAT and gross
    ./mb query out examples/invoices.sql > invoices.csv

    # 4. invoices and amounts grouped by customer and year
    ./mb query out examples/revenue_by_customer_and_year.sql > revenue.csv

    # 5. invoice lines with quantity, unit, unit price and description
    ./mb query out examples/invoice_positions.sql > positions.csv

    # 6. unit prices (hourly rates) charged per customer
    ./mb query out examples/unit_prices_by_customer.sql > rates.csv

    # the same for Mandant 2
    ./mb query out examples/invoices.sql 2 > invoices_mandant2.csv

| Query | Answers |
|---|---|
| `customers.sql` | Who were the customers, how to reach them, how much was invoiced, first and last invoice |
| `invoices.sql` | Which invoices exist |
| `revenue_by_customer_and_year.sql` | Number of invoices and net / gross amounts per customer and year |
| `invoice_positions.sql` | What was invoiced line by line |
| `unit_prices_by_customer.sql` | Which unit prices or hourly rates each customer was charged |

How the tables hang together:

- `MOV_INVOICES.CUSTID` points to `BAS_CUSTOMERS.ID`. Customer records with
  `ID <= 0` are internal placeholders; `CUSTKIND = 1` marks suppliers.
- `MOV_INVOICES_POSITIONS.INVID` points to `MOV_INVOICES.ID`. An invoice line
  holds only quantity and total; its text, unit and unit price are in the
  order line it came from (`ORDPOSID` -> `MOV_ORDERS_POSITIONS.ID`).
- `MOV_ORDERS_POSITIONS.UNITCODE` points to `SUP_ARTICLES_UNITS.ID`
  (`Stk.`, `Std.`, ...). Hours are often entered with the default unit
  `Stk.`, so check the price level too when looking for hourly rates.
- Amounts are in `TOTALNET` / `TOTALGROSS`; dates are ISO text
  (`2018-05-28 00:00:00`), so `SUBSTR(INVDATE, 1, 4)` is the year.

Without Docker the same files work with any SQLite client, e.g.
`sqlite3 -header -csv out/export/mandant1.sqlite < examples/invoices.sql`,
or paste them into the SQL box of `./mb serve out`.

## Technical details

An `.mfb` backup is not a proprietary format. It is two well-known formats
nested in each other:

1. **The `.mfb` file is a plain ZIP archive** (deflate, not encrypted) with
   a different file extension. Any unzip tool opens it. File names inside
   are stored in the DOS / Windows codepage, so umlauts need converting.

       DB/<n>/DB<n>.bak    one database backup per Mandant
       Archiv/             PDFs of the documents that were issued
       Dokumente/          attached documents
       Reports/            print templates (.rtm)
       MB.ini, Version.txt settings and the program version
       Archiv/*.mfb        sometimes an older backup, same format

2. **Each `DB<n>.bak` is a Firebird database backup** written by Firebird's
   `gbak` tool (transportable format). It is not a database file that can
   be opened directly; it has to be restored into a `.fdb` file first:

       gbak -c -user SYSDBA DB1.bak mandant1.fdb

   The backups seen so far use gbak format 8 (Mein Büro 11, 2012) and
   format 9 (WISO Mein Büro 18, 2019). Firebird 3 restores both, which is
   why the image is built on Debian's `firebird3.0-server`. Some backups
   contain text that is invalid in the declared character set; the tool
   then retries with `-fix_fss_metadata` / `-fix_fss_data ISO8859_1`.

After the restore the tool connects with Firebird's embedded engine (no
server process, no password), reads all tables with Python (`fdb`) and
writes them to SQLite and CSV. Text is declared as ISO8859_1 but was typed
on Windows, so it is converted from Windows-1252 to UTF-8.

The restore runs inside the container's own file system and the finished
`.fdb` is copied to the output folder, because Firebird needs file locking
that bind mounts on macOS and Windows do not reliably offer.

## Deutsch

Ein einfaches Werkzeug, um alte Datensicherungen von WISO / Buhl
„Mein Büro" (`.mfb`-Dateien) ohne das Programm zu öffnen, zum Beispiel wenn
die alte Version nicht mehr installiert ist und die aktuelle Version die
Sicherung nicht mehr einlesen kann.

Das Tool entpackt die Sicherung, stellt die Datenbanken wieder her und
exportiert alle Tabellen nach SQLite und CSV. Alles läuft in einem
Docker-Container; die Sicherungsdatei wird nur gelesen und nicht verändert.

Dies ist ein inoffizielles Projekt ohne Verbindung zur Buhl Data Service
GmbH; „WISO" und „Mein Büro" sind deren Marken.

### Kurzanleitung

    ./mb build                                  # Image einmalig bauen
    ./mb info  "Datensicherung.mfb"             # Inhalt der Sicherung anzeigen
    ./mb all   "Datensicherung.mfb" ausgabe     # entpacken, wiederherstellen, exportieren
    ./mb serve ausgabe                          # Daten im Browser: http://localhost:8001
    ./mb sql   ausgabe 1                        # Firebird-SQL-Konsole für Mandant 1
    ./mb query ausgabe examples/customers.sql > kunden.csv
    ./mb query ausgabe examples/invoices.sql  > rechnungen.csv

Im Ausgabeordner liegen danach:

- `files/` – der entpackte Inhalt der Sicherung, darunter `Archiv/` mit den
  PDFs der erstellten Belege und `Dokumente/`
- `db/mandantN.fdb` – die wiederhergestellten Firebird-Datenbanken
- `export/mandantN.sqlite` – alle Tabellen in einer SQLite-Datei
- `export/mandantN_csv/` – je Tabelle eine CSV-Datei (UTF-8, Trennzeichen `;`,
  Dezimalkomma, direkt in Excel zu öffnen)
- `nested_backups/` – dasselbe für ältere Sicherungen, die in der Sicherung
  enthalten waren

Die Abfragen im Ordner `examples/` liefern Kundenliste, Rechnungen, Umsätze
je Kunde und Jahr, Rechnungspositionen sowie die berechneten Stück- und
Stundenpreise je Kunde. Details dazu stehen oben unter
„Examples: customers and invoices".

### Technischer Hintergrund

- **Die `.mfb`-Datei ist ein gewöhnliches ZIP-Archiv** (unverschlüsselt) mit
  anderer Dateiendung. Sie enthält die Ordner `DB/`, `Archiv/`,
  `Dokumente/` und `Reports/` sowie `MB.ini` und `Version.txt`.
- **Die Dateien `DB/<n>/DB<n>.bak` sind Firebird-Datenbanksicherungen**,
  erstellt mit dem Firebird-Werkzeug `gbak`, eine je Mandant. Sie lassen
  sich nicht direkt öffnen, sondern müssen zuerst mit `gbak -c` in eine
  `.fdb`-Datenbank zurückgespielt werden. Das Tool verwendet dafür
  Firebird 3, das auch die älteren Sicherungsformate (gbak-Format 8 und 9)
  liest.
- Anschließend werden alle Tabellen über die eingebettete Firebird-Engine
  gelesen und nach SQLite und CSV geschrieben. Texte werden dabei von
  Windows-1252 nach UTF-8 umgewandelt.
- Getestet mit Sicherungen aus Mein Büro 11 (2012) und WISO Mein Büro 18
  (2019).

## Notes

- Nothing is written to the backup file; it is mounted read-only.
- `sql` and `serve` work on copies inside the container, so changes are not kept.
- Text is stored as ISO8859_1 / Windows-1252 and converted to UTF-8 on export.
- Tested with backups from Mein Büro 11 (2012, gbak format 8) and
  WISO Mein Büro 18 (2019, gbak format 9).
