"""Point-in-time queries on China's monthly retail sales publications."""
import argparse
import csv
import json
import os
import re
import sys
import tempfile
import unicodedata
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "observations.csv"
SOURCES = ROOT / "data" / "sources.csv"
FIELDS = "release_date period metric period_type measure unit value source_url".split()
LABELS = {"社会消费品零售总额": "retail_total", "其中:网上商品零售额": "online_goods"}
UNITS = {"mom_sa": "pct", "amount": "cny_100m", "yoy": "pct"}


def month(value):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise ValueError(f"expected YYYY-MM, got {value!r}")
    return value


def iso_day(value):
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError(f"expected YYYY-MM-DD, got {value!r}")
    return value


def clean(value):
    return "".join(unicodedata.normalize("NFKC", value).split())


class Publication(HTMLParser):
    """Retain only table cells and the publisher's date metadata."""
    def __init__(self):
        super().__init__()
        self.release = None
        self.tables = []
        self.table = self.row = self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and (attrs.get("name") or "").lower() == "pubdate":
            stamp = attrs["content"].split()[0].replace("/", "-")
            self.release = iso_day(stamp)
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("th", "td") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.cell is not None:
            self.row.append(clean("".join(self.cell)))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def value_of(cell, allow_missing=False):
    if allow_missing and cell in ("-", "—", "–"):
        return ""
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", cell):
        raise ValueError(f"unexpected numeric cell {cell!r}")
    return cell


def primary_rows(table, report):
    m = int(report[-2:])
    if table[0] != ["指标", f"{m}月", f"1—{m}月"]:
        raise ValueError(f"unexpected main table header {table[0]}")
    if table[1] != ["绝对量(亿元)", "同比增长(%)"] * 2:
        raise ValueError(f"unexpected amount/growth columns {table[1]}")
    rows = []
    for cells in table[2:]:
        if not cells or cells[0] not in LABELS:
            continue
        metric = LABELS[cells[0]]
        if len(cells) != 5:
            raise ValueError(f"invalid main table row {cells}")
        for scope, pair in (("month", cells[1:3]), ("year_to_date", cells[3:5])):
            for measure, raw in zip(("amount", "yoy"), pair):
                value = value_of(raw, allow_missing=(metric == "online_goods" and scope == "month"))
                rows.append((report, metric, scope, measure, value))
    if len(rows) != 8 or len({row[:4] for row in rows}) != 8:
        raise ValueError("expected two distinct headline metrics with four columns each")
    return rows


def revision_rows(table, report):
    if table[0] != ["年份", "月份", "环比增速(%)"]:
        raise ValueError(f"unexpected revision columns {table[0]}")
    rows, year = [], None
    for cells in table[1:]:
        if len(cells) == 3 and re.fullmatch(r"\d{4}年", cells[0]):
            year = int(cells[0][:-1])
            cells = cells[1:]
        if len(cells) != 2 or not year or not re.fullmatch(r"(?:[1-9]|1[0-2])月", cells[0]):
            raise ValueError(f"invalid revision table row {cells}")
        period = f"{year:04d}-{int(cells[0][:-1]):02d}"
        rows.append((period, "retail_total", "month", "mom_sa", value_of(cells[1])))
    y, m = map(int, report.split("-"))
    last_index = y * 12 + m - 1
    expected = [f"{i // 12:04d}-{i % 12 + 1:02d}" for i in range(last_index - 12, last_index + 1)]
    if [r[0] for r in rows] != expected:
        raise ValueError("revision table does not cover the expected 13 consecutive months")
    return rows


def extract(html, source):
    page = Publication()
    page.feed(html)
    page.close()
    report = month(source["report_period"])
    if page.release != iso_day(source["release_date"]) or page.release[:7] <= report:
        raise ValueError(f"release date / report month mismatch for {report}")
    versions = {}
    for table in page.tables:
        if not table or not table[0]:
            continue
        header = table[0][0]
        if header == "指标":
            values = primary_rows(table, report)
        elif header == "年份":
            values = revision_rows(table, report)
        else:
            continue
        if header in versions and versions[header] != values:
            raise ValueError(f"conflicting copies of {header} table in {report}")
        versions[header] = values
    if set(versions) != {"指标", "年份"}:
        raise ValueError(f"incomplete tables in {report}")
    result = []
    for values in versions.values():
        for period, metric, scope, measure, value in values:
            result.append(dict(zip(FIELDS, (page.release, period, metric, scope, measure,
                                            UNITS[measure], value, source["source_url"]))))
    return result


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def fetch(source):
    url = source["source_url"]
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "www.stats.gov.cn":
        raise ValueError(f"expected an official NBS HTTPS URL, got {url}")
    request = Request(url, headers={"User-Agent": "china-stats-vintages/1.0 (retail statistics research)"})
    with urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8-sig")


def refresh(sources=SOURCES, output=DATA, get_html=fetch):
    entries = read_csv(sources)
    if not entries or len({s["release_date"] for s in entries}) != len(entries):
        raise ValueError("source manifest is empty or has duplicate release dates")
    rows = []
    for source in entries:
        rows.extend(extract(get_html(source), source))
    rows.sort(key=lambda r: tuple(r[f] for f in FIELDS[:5]))
    if output.exists():
        old = {tuple(r[f] for f in FIELDS) for r in read_csv(output)}
        new = {tuple(r[f] for f in FIELDS) for r in rows}
        if old - new:
            raise ValueError("previously published rows changed or disappeared; review the source before replacing the snapshot")
    with tempfile.NamedTemporaryFile(dir=output.parent, mode="w", encoding="utf-8",
                                     newline="", delete=False) as stream:
        temp_path = Path(stream.name)
        try:
            writer = csv.DictWriter(stream, FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        except BaseException:
            stream.close()
            temp_path.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp_path, output)
    finally:
        temp_path.unlink(missing_ok=True)
    return len(rows)


def series(rows, period, metric="retail_total", scope="month", measure="mom_sa"):
    key = (month(period), metric, scope, measure)
    return sorted((row for row in rows if (row["period"], row["metric"], row["period_type"],
                                           row["measure"]) == key),
                  key=lambda row: row["release_date"])


def as_of(rows, period, on, metric="retail_total", scope="month", measure="mom_sa"):
    day = iso_day(on)
    matches = series(rows, period, metric, scope, measure)
    return next((row for row in reversed(matches) if row["release_date"] <= day), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for command in ("as-of", "revisions"):
        q = subs.add_parser(command)
        q.add_argument("--period", required=True, type=month)
        q.add_argument("--metric", choices=tuple(LABELS.values()), default="retail_total")
        q.add_argument("--scope", choices=("month", "year_to_date"), default="month")
        q.add_argument("--measure", choices=tuple(UNITS), default="mom_sa")
        if command == "as-of":
            q.add_argument("--on", required=True, type=iso_day)
    subs.add_parser("refresh", help="refetch the release manifest and rebuild the data atomically")
    args = parser.parse_args()
    if args.command == "refresh":
        print(f"{refresh()} observations")
        return
    rows = read_csv(DATA)
    options = args.metric, args.scope, args.measure
    if args.measure == "mom_sa" and options[:2] != ("retail_total", "month"):
        parser.error("mom_sa is published only for retail_total, month")
    if args.command == "as-of":
        result = as_of(rows, args.period, args.on, *options)
        if result is None:
            print(json.dumps({"status": "no_release_in_archive", "as_of": args.on}))
        else:
            print(json.dumps({**result, "value": result["value"] or None,
                              "status": "published" if result["value"] else "not_reported"}))
        return
    baseline = None
    for row in series(rows, args.period, *options):
        v = Decimal(row["value"]) if row["value"] else None
        delta = str(v - baseline) if baseline is not None and v is not None else None
        print(json.dumps({**row, "value": row["value"] or None, "change": delta}))
        baseline = v


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        sys.exit(str(error))
