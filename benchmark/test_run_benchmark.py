import unittest
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from benchmark.run_benchmark import (
    canonical_result,
    cutoff_candidates,
    cutoff_utc,
    database_command,
    query_pairs,
    render_query,
    results_match,
    select_settled_queries,
    summary_markdown,
    timing_summary,
)


class QueryRenderingTests(unittest.TestCase):
    def test_render_query_replaces_the_shared_cutoff(self):
        query = "SELECT * FROM orders WHERE order_date < '{{CUTOFF}}'"

        rendered = render_query(query, "2026-09-13 19:43:57+00")

        self.assertEqual(
            rendered,
            "SELECT * FROM orders WHERE order_date < '2026-09-13 19:43:57+00'",
        )

    def test_canonical_result_ignores_row_order_and_blank_lines(self):
        result = "b\t2\n\na\t1\n"

        self.assertEqual(canonical_result(result), "a\t1\nb\t2")

    def test_canonical_result_ignores_decimal_scale(self):
        postgres_result = "2026-09-01\tHome & Kitchen\t25363.80\n"
        clickhouse_result = "2026-09-01\tHome & Kitchen\t25363.8\n"

        self.assertEqual(canonical_result(postgres_result), canonical_result(clickhouse_result))

    def test_results_match_allows_one_cent_decimal_rounding_difference(self):
        postgres_result = "Iraq\t2\t4222.30\n"
        clickhouse_result = "Iraq\t2\t4222.29\n"

        self.assertTrue(results_match(postgres_result, clickhouse_result))

    def test_results_match_rejects_larger_numeric_or_text_differences(self):
        self.assertFalse(results_match("Iraq\t2\t4222.30\n", "Iraq\t2\t4222.28\n"))
        self.assertFalse(results_match("Iraq\t2\t4222.30\n", "Iran\t2\t4222.30\n"))


class QueryDiscoveryTests(unittest.TestCase):
    def test_query_pairs_returns_complete_dialect_pairs(self):
        with TemporaryDirectory() as directory:
            query_dir = Path(directory)
            (query_dir / "01_revenue.pg.sql").write_text("SELECT 1")
            (query_dir / "01_revenue.ch.sql").write_text("SELECT 1")

            self.assertEqual(
                query_pairs(query_dir),
                [("01_revenue", query_dir / "01_revenue.pg.sql", query_dir / "01_revenue.ch.sql")],
            )

    def test_query_pairs_rejects_an_unpaired_dialect_file(self):
        with TemporaryDirectory() as directory:
            query_dir = Path(directory)
            (query_dir / "01_revenue.pg.sql").write_text("SELECT 1")

            with self.assertRaisesRegex(ValueError, "missing ClickHouse query"):
                query_pairs(query_dir)


class RunnerContractTests(unittest.TestCase):
    def test_cutoff_is_five_minutes_before_the_benchmark_start(self):
        now = datetime(2026, 9, 13, 20, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(cutoff_utc(now), "2026-09-13 19:55:00+00")

    def test_cutoff_candidates_back_off_one_minute_at_a_time(self):
        now = datetime(2026, 9, 13, 20, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(
            cutoff_candidates(now, minimum_minutes=5, maximum_minutes=7),
            [
                "2026-09-13 19:55:00+00",
                "2026-09-13 19:54:00+00",
                "2026-09-13 19:53:00+00",
            ],
        )

    def test_settled_query_selection_backs_off_until_all_pairs_match(self):
        now = datetime(2026, 9, 13, 20, 0, 0, tzinfo=timezone.utc)
        with TemporaryDirectory() as directory:
            query_dir = Path(directory)
            postgres_path = query_dir / "01_revenue.pg.sql"
            clickhouse_path = query_dir / "01_revenue.ch.sql"
            postgres_path.write_text("postgres {{CUTOFF}}")
            clickhouse_path.write_text("clickhouse {{CUTOFF}}")

            def fake_execute(engine, query):
                if "19:55:00" in query:
                    return ("1\n" if engine == "postgres" else "2\n"), 0.0
                return "1\n", 0.0

            with patch("benchmark.run_benchmark.execute", side_effect=fake_execute):
                cutoff, selected = select_settled_queries(
                    [("01_revenue", postgres_path, clickhouse_path)], now
                )

        self.assertEqual(cutoff, "2026-09-13 19:54:00+00")
        self.assertEqual(selected[0][0], "01_revenue")
        self.assertEqual(selected[0][2], "1\n")

    def test_database_command_uses_the_service_local_clients(self):
        postgres = database_command("postgres")
        clickhouse = database_command("clickhouse")

        self.assertEqual(postgres[:5], ["docker", "compose", "exec", "-T", "postgres"])
        self.assertIn("psql", postgres[-1])
        self.assertIn('-F "\t"', postgres[-1])
        self.assertEqual(clickhouse[:5], ["docker", "compose", "exec", "-T", "clickhouse"])
        self.assertIn("clickhouse-client", clickhouse[-1])

    def test_database_command_rejects_unknown_engines(self):
        with self.assertRaisesRegex(ValueError, "unknown engine"):
            database_command("sqlite")

    def test_timing_summary_uses_min_median_and_max(self):
        self.assertEqual(
            timing_summary([30.0, 10.0, 20.0, 50.0, 40.0]),
            {"min_ms": 10.0, "median_ms": 30.0, "max_ms": 50.0},
        )

    def test_summary_markdown_includes_both_engines_for_each_query(self):
        summary = summary_markdown(
            "2026-09-13 19:58:00+00",
            {
                "01_revenue_by_category": {
                    "postgres": {"min_ms": 10.0, "median_ms": 20.0, "max_ms": 30.0},
                    "clickhouse": {"min_ms": 5.0, "median_ms": 8.0, "max_ms": 12.0},
                }
            },
        )

        self.assertIn("2026-09-13 19:58:00+00", summary)
        self.assertIn("01_revenue_by_category", summary)
        self.assertIn("PostgreSQL", summary)
        self.assertIn("ClickHouse", summary)
        self.assertIn("5–15 minute settled CDC window", summary)
        self.assertIn("## Observations", summary)
        self.assertIn("had the lower median", summary)

    def test_runner_exposes_a_repetitions_option(self):
        runner = Path(__file__).parent / "run_benchmark.py"

        completed = subprocess.run(
            [sys.executable, str(runner), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertIn("--repetitions", completed.stdout)


if __name__ == "__main__":
    unittest.main()
