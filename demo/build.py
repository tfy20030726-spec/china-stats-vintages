"""Build the offline retail-sales revision explorer from the repository's CSV."""
import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


def build():
    rows = []
    seen = set()
    with (ROOT / "data" / "observations.csv").open(encoding="utf-8-sig", newline="") as src:
        for row in csv.DictReader(src):
            if (row["metric"], row["period_type"], row["measure"]) != ("retail_total", "month", "mom_sa"):
                continue
            day, month = row["release_date"], row["period"]
            if date.fromisoformat(day).isoformat() != day or date.fromisoformat(month + "-01").isoformat()[:7] != month:
                raise ValueError(f"Unexpected release date or period: {day}, {month}")
            if row["unit"] != "pct" or not Decimal(row["value"]).is_finite():
                raise ValueError(f"Unexpected unit or value: {day}, {month}")
            url = urlsplit(row["source_url"])
            if url.scheme not in {"http", "https"} or not url.hostname:
                raise ValueError(f"Invalid source URL: {day}, {month}")
            if (day, month) in seen:
                raise ValueError(f"Duplicate observation: {day}, {month}")
            seen.add((day, month))
            rows.append({key: row[key] for key in ("period", "release_date", "value", "source_url")})
    if not rows:
        raise ValueError("No monthly, seasonally adjusted retail-sales observations found")
    rows.sort(key=lambda row: (row["release_date"], row["period"]))
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("<", r"\u003c")
    template = (ROOT / "demo" / "page.html").read_text(encoding="utf-8")
    output = ROOT / "index.html"
    output.write_text(template.replace("__OBSERVATIONS_JSON__", encoded), encoding="utf-8", newline="\n")
    print(f"Built {output.name} with {len(rows)} published observations.")


if __name__ == "__main__":
    build()