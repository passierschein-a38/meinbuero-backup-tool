#!/usr/bin/env python3
"""mbtool - extract and open WISO / Buhl "Mein Buero" backups (.mfb).

An .mfb file is a ZIP archive.  Inside:
  DB/<n>/DB<n>.bak   Firebird gbak backup, one per Mandant (client)
  Archiv/            PDFs of issued documents
  Dokumente/         attached documents
  Reports/           print templates
  MB.ini, Version.txt

This tool unpacks the archive, restores every database with Firebird 3
(which reads the older gbak formats) and exports all tables to SQLite and
CSV so the data can be read without Mein Buero.
"""
import argparse
import csv
import datetime
import decimal
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

IN_DEFAULT = "/in/backup.mfb"
OUT_DEFAULT = "/out"
FB_CHARSET = "ISO8859_1"
COMMON_CHARS = "äöüÄÖÜßéèêáàâóòôúùûçñ§°€´’–"


def log(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------- archive

def zip_name(info):
    """Return the real file name of a ZIP entry.

    Mein Buero stores names in the Windows codepage without the UTF-8
    flag; Python decodes those as cp437, which garbles German umlauts.
    """
    if info.flag_bits & 0x800:
        return info.filename
    # orig_filename is the raw name; newer Pythons replace .filename with the
    # archive's "Unicode Path" extra field, which these backups write wrongly.
    # Names are mostly in the DOS codepage, some in the Windows one.
    try:
        raw = info.orig_filename.encode("cp437")
    except UnicodeEncodeError:
        return info.filename
    name = info.orig_filename
    for codec in ("cp850", "cp1252"):
        try:
            candidate = raw.decode(codec)
        except UnicodeDecodeError:
            continue
        if all(ch < "\x80" or ch in COMMON_CHARS for ch in candidate):
            name = candidate
            break
    return name


def safe_target(root, name):
    root = os.path.abspath(root)
    name = name.replace("\\", "/")
    target = os.path.normpath(os.path.join(root, name))
    if not (target + os.sep).startswith(root + os.sep):
        raise ValueError("unsafe path in archive: %r" % name)
    return target


def read_version(z):
    for info in z.infolist():
        if info.filename.lower() == "version.txt":
            return z.read(info).decode("cp1252", "replace").strip()
    return ""


def cmd_info(mfb):
    if not zipfile.is_zipfile(mfb):
        sys.exit("%s is not a ZIP archive - not a plain .mfb backup" % mfb)
    with zipfile.ZipFile(mfb) as z:
        infos = z.infolist()
        log("File:      %s" % mfb)
        log("Entries:   %d (%.1f MB unpacked)" % (
            len(infos), sum(i.file_size for i in infos) / 1e6))
        log("Encrypted: %s" % ("yes" if any(i.flag_bits & 1 for i in infos) else "no"))
        version = read_version(z)
        if version:
            log(version)
        log("")
        folders = {}
        for i in infos:
            name = zip_name(i)
            top = name.split("/")[0] if "/" in name else "(root)"
            n, size = folders.get(top, (0, 0))
            folders[top] = (n + 1, size + i.file_size)
        for top in sorted(folders):
            log("  %-14s %5d files %10.1f MB" % (top, folders[top][0], folders[top][1] / 1e6))
        log("")
        for i in infos:
            name = zip_name(i)
            if name.lower().endswith(".bak"):
                head = z.open(i).read(200)
                fmt = head[3] if head[:3] == b"\x00\x02\x04" else None
                label = re.search(rb"\x07.([^\x00\x01]{2,80})\x01", head, re.S)
                log("  database %s  %.1f MB  gbak format %s  %s" % (
                    name, i.file_size / 1e6, fmt,
                    label.group(1).decode("cp1252", "replace") if label else ""))
            if name.lower().endswith(".mfb"):
                log("  nested backup %s  %.1f MB" % (name, i.file_size / 1e6))


def cmd_extract(mfb, out):
    files = os.path.join(out, "files")
    os.makedirs(files, exist_ok=True)
    count = 0
    with zipfile.ZipFile(mfb) as z:
        for info in z.infolist():
            name = zip_name(info)
            target = safe_target(files, name)
            if name.endswith("/"):
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            stamp = datetime.datetime(*info.date_time).timestamp()
            os.utime(target, (stamp, stamp))
            count += 1
    log("extracted %d files to %s" % (count, files))
    return files


# --------------------------------------------------------------- firebird

def find_backups(files):
    found = []
    for root, _dirs, names in os.walk(os.path.join(files, "DB")):
        for name in sorted(names):
            if name.lower().endswith(".bak"):
                m = re.search(r"(\d+)", name)
                found.append((int(m.group(1)) if m else len(found), os.path.join(root, name)))
    return sorted(found)


def gbak_restore(bak, fdb_path):
    """Restore inside the container file system, never on a bind mount."""
    attempts = [[], ["-fix_fss_metadata", FB_CHARSET, "-fix_fss_data", FB_CHARSET],
                ["-inactive", "-novalidity"]]
    last = ""
    for extra in attempts:
        if os.path.exists(fdb_path):
            os.remove(fdb_path)
        proc = subprocess.run(["gbak", "-c", "-user", "SYSDBA"] + extra + [bak, fdb_path],
                              capture_output=True, text=True, errors="replace")
        if proc.returncode == 0 and os.path.exists(fdb_path):
            return
        last = (proc.stdout + proc.stderr).strip()
        log("  gbak %s failed, retrying: %s" % (" ".join(extra) or "(default)", last[-300:]))
    raise RuntimeError("could not restore %s: %s" % (bak, last))


def cmd_restore(out):
    files = os.path.join(out, "files")
    dbdir = os.path.join(out, "db")
    os.makedirs(dbdir, exist_ok=True)
    restored = []
    for num, bak in find_backups(files):
        tmp = os.path.join(tempfile.mkdtemp(prefix="mb"), "mandant%d.fdb" % num)
        log("restoring %s ..." % os.path.relpath(bak, files))
        gbak_restore(bak, tmp)
        target = os.path.join(dbdir, "mandant%d.fdb" % num)
        shutil.copyfile(tmp, target)
        log("  -> %s (%.1f MB)" % (target, os.path.getsize(target) / 1e6))
        restored.append((num, tmp))
    if not restored:
        log("no DB/*/DB*.bak found in the backup")
    return restored


def local_copy(out, num):
    """Firebird needs real file locking, so work on a copy inside the container."""
    src = os.path.join(out, "db", "mandant%d.fdb" % num)
    if not os.path.exists(src):
        sys.exit("%s not found - run 'all' first" % src)
    tmp = os.path.join(tempfile.mkdtemp(prefix="mb"), os.path.basename(src))
    shutil.copyfile(src, tmp)
    return tmp


def fix_text(value):
    """Data is declared ISO8859_1 but was typed on Windows (cp1252)."""
    if any("\x80" <= ch <= "\x9f" for ch in value):
        try:
            return value.encode("latin-1").decode("cp1252")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return value


def read_blob(value):
    if hasattr(value, "read"):
        value = value.read()
    return value


def to_sqlite(value):
    value = read_blob(value)
    if value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return fix_text(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat(sep=" ") if isinstance(value, datetime.datetime) else value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    return str(value)


def to_csv(value, german):
    value = read_blob(value)
    if value is None:
        return ""
    if isinstance(value, str):
        return fix_text(value)
    if isinstance(value, (decimal.Decimal, float)):
        text = format(value, "f") if isinstance(value, decimal.Decimal) else repr(value)
        return text.replace(".", ",") if german else text
    if isinstance(value, datetime.datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if raw[:5] == b"{\\rtf" or (raw and all(b >= 9 for b in raw[:200])):
            return fix_text(raw.decode("latin-1"))
        return "<binary %d bytes>" % len(raw)
    return str(value)


def sqlite_type(py_type):
    if py_type is int:
        return "INTEGER"
    if py_type in (float, decimal.Decimal):
        return "REAL"
    if py_type in (bytes, bytearray):
        return "BLOB"
    return "TEXT"


def quote(name):
    return '"%s"' % name.replace('"', '""')


def export_database(num, fdb_path, out, with_views, german):
    import fdb
    exp = os.path.join(out, "export")
    csvdir = os.path.join(exp, "mandant%d_csv" % num)
    os.makedirs(csvdir, exist_ok=True)
    sqlite_path = os.path.join(exp, "mandant%d.sqlite" % num)
    tmp_sqlite = os.path.join(tempfile.mkdtemp(prefix="mb"), "db.sqlite")

    con = fdb.connect(database=fdb_path, user="SYSDBA", charset=FB_CHARSET)
    cur = con.cursor()
    cur.execute("select trim(rdb$relation_name), "
                "case when rdb$view_blr is null then 0 else 1 end "
                "from rdb$relations where coalesce(rdb$system_flag, 0) = 0 order by 1")
    relations = [(r[0], bool(r[1])) for r in cur.fetchall()]

    lite = sqlite3.connect(tmp_sqlite)
    summary = []
    for name, is_view in relations:
        if is_view and not with_views:
            continue
        try:
            cur.execute("select * from %s" % quote(name))
            cols = [(d[0], d[1]) for d in cur.description]
            target = ("V_" + name) if is_view else name
            lite.execute("create table %s (%s)" % (quote(target), ", ".join(
                "%s %s" % (quote(c), sqlite_type(t)) for c, t in cols)))
            insert = "insert into %s values (%s)" % (quote(target), ",".join("?" * len(cols)))
            rows = 0
            writer = handle = None
            while True:
                batch = cur.fetchmany(500)
                if not batch:
                    break
                if writer is None:
                    handle = open(os.path.join(csvdir, target + ".csv"), "w",
                                  newline="", encoding="utf-8-sig")
                    writer = csv.writer(handle, delimiter=";" if german else ",")
                    writer.writerow([c for c, _ in cols])
                lite.executemany(insert, [[to_sqlite(v) for v in row] for row in batch])
                writer.writerows([[to_csv(v, german) for v in row] for row in batch])
                rows += len(batch)
            if handle:
                handle.close()
            summary.append((target, rows, len(cols)))
        except Exception as exc:  # keep going, report at the end
            con.rollback()
            lite.rollback()
            summary.append((name, "ERROR: %s" % str(exc).replace("\n", " ")[:160], 0))
    lite.commit()
    company = ""
    try:
        row = lite.execute("select NAME1, NAME2, CITY from BAS_COMPANY").fetchone()
        company = ", ".join(v for v in (row or ()) if v)
    except sqlite3.Error:
        pass
    lite.close()
    con.close()
    shutil.copyfile(tmp_sqlite, sqlite_path)

    with open(os.path.join(exp, "mandant%d_tables.txt" % num), "w", encoding="utf-8") as fh:
        fh.write("Mandant %d: %s\n\n" % (num, company or "(company name not found)"))
        fh.write("%-45s %10s %8s\n" % ("table", "rows", "columns"))
        for name, rows, ncols in sorted(summary, key=lambda s: (-s[1] if isinstance(s[1], int) else 1, s[0])):
            fh.write("%-45s %10s %8s\n" % (name, rows, ncols))
    filled = [s for s in summary if isinstance(s[1], int) and s[1]]
    errors = [s for s in summary if not isinstance(s[1], int)]
    log("  mandant %d [%s]: %d tables (%d with data, %d rows), %d errors -> %s" % (
        num, company or "?", len(summary), len(filled), sum(s[1] for s in filled), len(errors), sqlite_path))
    for name, err, _ in errors:
        log("    %s: %s" % (name, err))


def cmd_export(out, restored=None, with_views=False, german=True):
    if restored is None:
        restored = []
        dbdir = os.path.join(out, "db")
        for name in sorted(os.listdir(dbdir)) if os.path.isdir(dbdir) else []:
            m = re.match(r"mandant(\d+)\.fdb$", name)
            if m:
                restored.append((int(m.group(1)), local_copy(out, int(m.group(1)))))
    log("exporting tables to SQLite and CSV ...")
    for num, path in restored:
        export_database(num, path, out, with_views, german)


def cmd_all(mfb, out, with_views, german, depth=0):
    cmd_info(mfb)
    log("")
    files = cmd_extract(mfb, out)
    restored = cmd_restore(out)
    cmd_export(out, restored, with_views, german)
    if depth == 0:
        for root, _dirs, names in os.walk(files):
            for name in names:
                if name.lower().endswith(".mfb"):
                    nested = os.path.join(root, name)
                    sub = os.path.join(out, "nested_backups", os.path.splitext(name)[0])
                    log("\n=== nested backup: %s ===" % os.path.relpath(nested, files))
                    cmd_all(nested, sub, with_views, german, depth + 1)
    if depth == 0:
        log("\ndone. Results are in the output folder:")
        log("  files/    everything from the archive (PDFs, documents, templates)")
        log("  db/       restored Firebird databases (.fdb)")
        log("  export/   mandantN.sqlite, mandantN_csv/, mandantN_tables.txt")


def cmd_sql(out, num):
    path = local_copy(out, num)
    log("Firebird isql on a working copy of mandant%d.fdb (changes are not kept)." % num)
    log("Try:  show tables;   select first 5 * from BAS_CUSTOMERS;   quit;")
    os.execvp("isql-fb", ["isql-fb", "-user", "SYSDBA", "-ch", FB_CHARSET, path])


def cmd_query(out, num, german):
    """Run SQL from stdin against mandantN.sqlite and print the result as CSV."""
    path = os.path.join(out, "export", "mandant%d.sqlite" % num)
    if not os.path.exists(path):
        sys.exit("%s not found - run 'all' first" % path)
    sql = sys.stdin.read().strip().rstrip(";")
    if not sql:
        sys.exit("no SQL on standard input, e.g.:  ./mb query outdir examples/customers.sql")
    con = sqlite3.connect("file:%s?mode=ro&immutable=1" % path, uri=True)
    try:
        cur = con.execute(sql)
    except sqlite3.Error as exc:
        sys.exit("SQL error: %s" % exc)
    writer = csv.writer(sys.stdout, delimiter=";" if german else ",", lineterminator="\n")
    writer.writerow([d[0] for d in cur.description or []])
    for row in cur:
        writer.writerow([to_csv(v, german) for v in row])


def cmd_serve(out, port):
    found = []
    for root, _dirs, names in os.walk(out):
        for name in sorted(names):
            if name.endswith(".sqlite"):
                src = os.path.join(root, name)
                rel = os.path.relpath(root, out).replace(os.sep, "_").replace("export", "").strip("_.")
                label = re.sub(r"[^A-Za-z0-9_]+", "_", (rel + "_" if rel else "") + name[:-7]).strip("_")
                dst = os.path.join("/tmp/serve", label + ".db")
                os.makedirs("/tmp/serve", exist_ok=True)
                shutil.copyfile(src, dst)
                found.append(dst)
    if not found:
        sys.exit("no .sqlite files below %s - run 'all' first" % out)
    log("browse the data at http://localhost:%d  (Ctrl+C to stop)" % port)
    os.execvp("datasette", ["datasette", "serve", "--host", "0.0.0.0", "--port", str(port),
                            "--setting", "sql_time_limit_ms", "20000",
                            "--setting", "max_returned_rows", "5000"] + found)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="mfb", default=IN_DEFAULT, help="backup file (default %(default)s)")
    ap.add_argument("--out", default=OUT_DEFAULT, help="output folder (default %(default)s)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="show what is inside the backup")
    sub.add_parser("extract", help="unpack the archive only")
    sub.add_parser("restore", help="restore DB/*.bak to Firebird .fdb files")
    for name in ("export", "all"):
        p = sub.add_parser(name, help="export tables to SQLite/CSV" if name == "export"
                           else "extract + restore + export (also nested backups)")
        p.add_argument("--views", action="store_true", help="also export database views (V_ prefix)")
        p.add_argument("--csv-intl", action="store_true",
                       help="CSV with comma separator and decimal point (default: German Excel style)")
    p = sub.add_parser("sql", help="interactive Firebird SQL shell")
    p.add_argument("mandant", nargs="?", type=int, default=1)
    p = sub.add_parser("query", help="run SQL from stdin on the exported SQLite file, print CSV")
    p.add_argument("mandant", nargs="?", type=int, default=1)
    p.add_argument("--csv-intl", action="store_true",
                   help="comma separator and decimal point (default: German Excel style)")
    p = sub.add_parser("serve", help="web UI (Datasette) for the exported SQLite files")
    p.add_argument("--port", type=int, default=8001)
    args = ap.parse_args()

    if args.cmd in ("info", "extract", "all") and not os.path.isfile(args.mfb):
        sys.exit("backup file %s not found" % args.mfb)
    if args.cmd == "info":
        cmd_info(args.mfb)
    elif args.cmd == "extract":
        cmd_extract(args.mfb, args.out)
    elif args.cmd == "restore":
        cmd_restore(args.out)
    elif args.cmd == "export":
        cmd_export(args.out, None, args.views, not args.csv_intl)
    elif args.cmd == "all":
        cmd_all(args.mfb, args.out, args.views, not args.csv_intl)
    elif args.cmd == "sql":
        cmd_sql(args.out, args.mandant)
    elif args.cmd == "query":
        cmd_query(args.out, args.mandant, not args.csv_intl)
    elif args.cmd == "serve":
        cmd_serve(args.out, args.port)


if __name__ == "__main__":
    main()
