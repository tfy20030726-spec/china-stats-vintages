import csv
import tempfile
import unittest
from pathlib import Path

import stats


SOURCE = {"release_date": "2026-11-16", "report_period": "2026-10",
          "source_url": "https://www.stats.gov.cn/sj/zxfb/202611/t20261116_1965839.html"}


def render_table(rows):
    return "<table>" + "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row)
                                + "</tr>" for row in rows) + "</table>"


def sample_page():
    main = render_table([
        ["指标", "10月", "1—10月"], ["绝对量（亿元）", "同比增长（%）"] * 2,
        ["社会消费品零售总额", "46463", "0.4", "416464", "1.0"],
        ["其中：网上商品零售额", "-", "-", "107274", "2.9"],
    ])
    revision = [["年份", "月份", "环比增速（%）"]]
    for index in range(13):
        year, m = divmod(2025 * 12 + 9 + index, 12)
        row = [f"{m+1}月", "0.12"]
        if index == 0 or m == 0:
            row.insert(0, f"{year}年")
        revision.append(row)
    tables = main + render_table(revision)
    return '<meta name="PubDate" content="2026/11/16 10:00">' + tables * 2


class PublishedDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = stats.read_csv(stats.DATA)

    def test_real_publications_preserve_headlines_and_separate_scopes(self):
        month = stats.as_of(self.rows, "2026-10", "2026-11-16", measure="yoy")
        cumulative = stats.as_of(self.rows, "2026-10", "2026-11-16", scope="year_to_date", measure="yoy")
        self.assertEqual((month["value"], cumulative["value"]), ("0.4", "1.0"))
        self.assertEqual(month["source_url"], SOURCE["source_url"])

    def test_no_calendar_month_end_or_release_day_lookahead(self):
        self.assertIsNone(stats.as_of(self.rows, "2026-06", "2026-07-14"))
        self.assertEqual(stats.as_of(self.rows, "2026-06", "2026-07-15")["value"], "0.38")
        self.assertEqual(stats.as_of(self.rows, "2026-06", "2026-11-15")["value"], "0.40")
        self.assertEqual(stats.as_of(self.rows, "2026-06", "2026-11-16")["value"], "0.25")

    def test_published_dash_and_absent_release_have_different_results(self):
        args = ("online_goods", "month", "amount")
        self.assertIsNone(stats.as_of(self.rows, "2026-10", "2026-11-15", *args))
        self.assertEqual(stats.as_of(self.rows, "2026-10", "2026-11-16", *args)["value"], "")
        self.assertEqual(stats.as_of(self.rows, "2026-10", "2026-11-16",
                                     "online_goods", "year_to_date", "amount")["value"], "107274")

    def test_each_observation_is_distinct_and_traceable(self):
        sources = stats.read_csv(stats.SOURCES)
        self.assertGreaterEqual(len(sources), 6)
        manifest = {r["release_date"]: r["source_url"] for r in sources}
        keys = {(r["release_date"], r["period"], r["metric"], r["period_type"], r["measure"])
                for r in self.rows}
        self.assertEqual(len(keys), len(self.rows))
        self.assertEqual(len(self.rows), 21 * len(sources))
        for row in self.rows:
            self.assertEqual(manifest[row["release_date"]], row["source_url"])

    def test_bad_dates_are_rejected(self):
        for invalid in ("2026-2", "2026-13", "26-03"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                stats.series(self.rows, invalid)
        with self.assertRaises(ValueError):
            stats.as_of(self.rows, "2026-06", "2026-02-30")


class ImportTest(unittest.TestCase):
    def test_duplicate_page_copies_and_rowspan_years(self):
        rows = stats.extract(sample_page(), SOURCE)
        self.assertEqual(len(rows), 21)
        months = [r["period"] for r in rows if r["measure"] == "mom_sa"]
        self.assertEqual((months[0], months[-1]), ("2025-10", "2026-10"))

    def test_disagreement_between_duplicate_tables_is_an_error(self):
        html = sample_page().replace("46463", "46464", 1)
        with self.assertRaisesRegex(ValueError, "conflicting copies"):
            stats.extract(html, SOURCE)

    def test_mismatched_release_date_or_truncated_timeline_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "mismatch"):
            stats.extract(sample_page(), {**SOURCE, "release_date": "2026-11-18"})
        html = sample_page().replace("<tr><td>2月</td><td>0.12</td></tr>", "")
        with self.assertRaisesRegex(ValueError, "13 consecutive"):
            stats.extract(html, SOURCE)

    def test_refresh_is_idempotent_and_preserves_existing_vintages_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            manifest, output = folder / "sources.csv", folder / "snapshot.csv"
            with manifest.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, SOURCE)
                writer.writeheader()
                writer.writerow(SOURCE)
            self.assertEqual(stats.refresh(manifest, output, lambda _: sample_page()), 21)
            original = output.read_bytes()
            stats.refresh(manifest, output, lambda _: sample_page())
            self.assertEqual(output.read_bytes(), original)
            with self.assertRaisesRegex(ValueError, "previously published rows"):
                stats.refresh(manifest, output, lambda _: sample_page().replace("46463", "46464"))
            self.assertEqual(output.read_bytes(), original)
            with self.assertRaisesRegex(ValueError, "unexpected numeric"):
                stats.refresh(manifest, output, lambda _: sample_page().replace("46463", "n/a"))
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
