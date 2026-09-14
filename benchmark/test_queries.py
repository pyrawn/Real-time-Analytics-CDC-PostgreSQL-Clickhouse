import unittest
from pathlib import Path

from benchmark.run_benchmark import query_pairs


QUERY_DIR = Path(__file__).parent / "queries"
EXPECTED_QUERIES = {
    "01_revenue_by_category",
    "02_top_products",
    "03_aov_by_country",
    "04_payment_success",
}


class QueryContractTests(unittest.TestCase):
    def test_has_the_four_required_query_pairs(self):
        self.assertEqual({name for name, _, _ in query_pairs(QUERY_DIR)}, EXPECTED_QUERIES)

    def test_every_query_uses_the_shared_cutoff(self):
        for _, postgres_path, clickhouse_path in query_pairs(QUERY_DIR):
            self.assertIn("{{CUTOFF}}", postgres_path.read_text())
            self.assertIn("{{CUTOFF}}", clickhouse_path.read_text())

    def test_clickhouse_queries_deduplicate_and_filter_soft_deletes(self):
        for _, _, clickhouse_path in query_pairs(QUERY_DIR):
            query = clickhouse_path.read_text()
            self.assertIn("FINAL", query)
            self.assertIn("_peerdb_is_deleted = 0", query)

    def test_queries_use_terminal_lifecycle_rows_for_live_comparisons(self):
        for name, postgres_path, clickhouse_path in query_pairs(QUERY_DIR):
            for query_path in (postgres_path, clickhouse_path):
                query = query_path.read_text()
                self.assertIn("o.order_status = 'delivered'", query)
                if name == "04_payment_success":
                    self.assertIn("p.payment_status IN ('completed', 'refunded')", query)


if __name__ == "__main__":
    unittest.main()
