"""Run paired PostgreSQL and ClickHouse benchmark queries."""

import argparse
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from statistics import median
import subprocess
import time


BENCHMARK_DIR = Path(__file__).resolve().parent
QUERY_DIR = BENCHMARK_DIR / "queries"
RESULTS_DIR = BENCHMARK_DIR / "results"


def render_query(query: str, cutoff: str) -> str:
    return query.replace("{{CUTOFF}}", cutoff)


def canonical_result(result: str) -> str:
    def canonical_field(field: str) -> str:
        try:
            value = Decimal(field)
        except InvalidOperation:
            return field
        return "0" if value == 0 else format(value.normalize(), "f")

    rows = (
        "\t".join(canonical_field(field) for field in line.strip().split("\t"))
        for line in result.splitlines()
        if line.strip()
    )
    return "\n".join(sorted(rows))


def results_match(postgres_result: str, clickhouse_result: str) -> bool:
    def rows(result: str) -> list[list[str]]:
        return sorted(line.strip().split("\t") for line in result.splitlines() if line.strip())

    postgres_rows = rows(postgres_result)
    clickhouse_rows = rows(clickhouse_result)
    if len(postgres_rows) != len(clickhouse_rows):
        return False

    for postgres_row, clickhouse_row in zip(postgres_rows, clickhouse_rows):
        if len(postgres_row) != len(clickhouse_row):
            return False
        for postgres_field, clickhouse_field in zip(postgres_row, clickhouse_row):
            try:
                difference = abs(Decimal(postgres_field) - Decimal(clickhouse_field))
            except InvalidOperation:
                if postgres_field != clickhouse_field:
                    return False
            else:
                if difference > Decimal("0.01"):
                    return False
    return True


def query_pairs(query_dir: Path) -> list[tuple[str, Path, Path]]:
    pairs = []
    for postgres_path in sorted(query_dir.glob("*.pg.sql")):
        name = postgres_path.name.removesuffix(".pg.sql")
        clickhouse_path = query_dir / f"{name}.ch.sql"
        if not clickhouse_path.exists():
            raise ValueError(f"{name}: missing ClickHouse query")
        pairs.append((name, postgres_path, clickhouse_path))

    for clickhouse_path in query_dir.glob("*.ch.sql"):
        name = clickhouse_path.name.removesuffix(".ch.sql")
        if not (query_dir / f"{name}.pg.sql").exists():
            raise ValueError(f"{name}: missing PostgreSQL query")

    return pairs


def cutoff_utc(now: datetime | None = None, minutes: int = 5) -> str:
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S+00")


def cutoff_candidates(
    now: datetime | None = None, minimum_minutes: int = 5, maximum_minutes: int = 15
) -> list[str]:
    if maximum_minutes < minimum_minutes:
        raise ValueError("maximum cutoff must not be less than minimum cutoff")
    return [cutoff_utc(now, minutes) for minutes in range(minimum_minutes, maximum_minutes + 1)]


def select_settled_queries(
    pairs: list[tuple[str, Path, Path]], now: datetime | None = None
) -> tuple[str, list[tuple[str, dict[str, str], str]]]:
    for cutoff in cutoff_candidates(now):
        selected = []
        for name, postgres_path, clickhouse_path in pairs:
            queries = {
                "postgres": render_query(postgres_path.read_text(), cutoff),
                "clickhouse": render_query(clickhouse_path.read_text(), cutoff),
            }
            postgres_result, _ = execute("postgres", queries["postgres"])
            clickhouse_result, _ = execute("clickhouse", queries["clickhouse"])
            if not postgres_result.strip() or not clickhouse_result.strip():
                break
            if not results_match(postgres_result, clickhouse_result):
                break
            selected.append((name, queries, postgres_result))
        else:
            return cutoff, selected

    raise RuntimeError("no settled non-empty CDC cutoff found; allow the mirror to catch up and retry")


def database_command(engine: str) -> list[str]:
    if engine == "postgres":
        command = 'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -A -t -F "\t"'
    elif engine == "clickhouse":
        command = 'clickhouse-client -u "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" -d "$CLICKHOUSE_DB" --format TSVRaw'
    else:
        raise ValueError(f"unknown engine: {engine}")
    return ["docker", "compose", "exec", "-T", engine, "sh", "-lc", command]


def timing_summary(samples: list[float]) -> dict[str, float]:
    return {
        "min_ms": min(samples),
        "median_ms": median(samples),
        "max_ms": max(samples),
    }


def summary_markdown(cutoff: str, summaries: dict[str, dict[str, dict[str, float]]]) -> str:
    lines = [
        "# Benchmark Results",
        "",
        f"Data cutoff: `{cutoff}` (selected from the 5–15 minute settled CDC window while the generator stayed active).",
        "",
        "Times are end-to-end local Docker command wall-clock measurements in milliseconds.",
        "",
        "| Query | Engine | Min | Median | Max |",
        "|---|---|---:|---:|---:|",
    ]
    for name, engines in summaries.items():
        for engine, values in engines.items():
            label = "PostgreSQL" if engine == "postgres" else "ClickHouse"
            lines.append(
                f"| {name} | {label} | {values['min_ms']:.2f} | "
                f"{values['median_ms']:.2f} | {values['max_ms']:.2f} |"
            )
    lines.extend([
        "",
        "## Observations",
        "",
    ])
    for name, engines in summaries.items():
        postgres_median = engines["postgres"]["median_ms"]
        clickhouse_median = engines["clickhouse"]["median_ms"]
        if postgres_median <= clickhouse_median:
            faster, faster_median, slower, slower_median = (
                "PostgreSQL",
                postgres_median,
                "ClickHouse",
                clickhouse_median,
            )
        else:
            faster, faster_median, slower, slower_median = (
                "ClickHouse",
                clickhouse_median,
                "PostgreSQL",
                postgres_median,
            )
        lines.append(
            f"- {name}: {faster} had the lower median ({faster_median:.2f} ms vs "
            f"{slower}'s {slower_median:.2f} ms)."
        )
    lines.extend([
        "",
        "## Caveats",
        "",
        "These are end-to-end local Docker command measurements, so client startup and result transfer are included.",
        "ClickHouse results include `FINAL` and soft-delete filtering; compare the paired plan files before attributing a difference solely to storage engine design.",
    ])
    return "\n".join(lines) + "\n"


def execute(engine: str, query: str) -> tuple[str, float]:
    started = time.perf_counter()
    completed = subprocess.run(
        database_command(engine),
        input=query,
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed_ms = (time.perf_counter() - started) * 1_000
    if completed.returncode:
        raise RuntimeError(
            f"{engine} query failed (exit {completed.returncode}):\n{completed.stderr.strip()}"
        )
    return completed.stdout, elapsed_ms


def explain(engine: str, query: str) -> str:
    prefix = "EXPLAIN (ANALYZE, BUFFERS) " if engine == "postgres" else "EXPLAIN "
    return execute(engine, prefix + query)[0]


def selected_env() -> dict[str, str]:
    env_path = BENCHMARK_DIR.parent / ".env"
    wanted = {"POSTGRES_DB", "CLICKHOUSE_DB", "GEN_RATE_PER_SEC", "GEN_DURATION_SECONDS"}
    if not env_path.exists():
        return {}

    values = {}
    for line in env_path.read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator and key in wanted:
            values[key] = value
    return values


def git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=BENCHMARK_DIR.parent,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=5, help="measured runs per engine and query")
    arguments = parser.parse_args()
    if arguments.repetitions < 1:
        parser.error("--repetitions must be at least 1")

    RESULTS_DIR.mkdir(exist_ok=True)
    timings = []
    summaries = {}

    cutoff, settled_queries = select_settled_queries(query_pairs(QUERY_DIR))
    for name, queries, postgres_result in settled_queries:

        for engine in ("postgres", "clickhouse"):
            plan = explain(engine, queries[engine])
            (RESULTS_DIR / f"{name}.{engine}.explain.txt").write_text(plan)

        samples = {"postgres": [], "clickhouse": []}
        row_count = len(canonical_result(postgres_result).splitlines())
        for iteration in range(1, arguments.repetitions + 1):
            engines = ("postgres", "clickhouse") if iteration % 2 else ("clickhouse", "postgres")
            for engine in engines:
                result, elapsed_ms = execute(engine, queries[engine])
                if not results_match(postgres_result, result):
                    raise RuntimeError(f"{name}: {engine} result changed during measurement")
                samples[engine].append(elapsed_ms)
                timings.append(
                    {
                        "query": name,
                        "engine": engine,
                        "iteration": iteration,
                        "elapsed_ms": f"{elapsed_ms:.3f}",
                        "row_count": row_count,
                        "cutoff": cutoff,
                    }
                )

        summaries[name] = {engine: timing_summary(values) for engine, values in samples.items()}

    with (RESULTS_DIR / "timings.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=timings[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(timings)

    (RESULTS_DIR / "summary.md").write_text(summary_markdown(cutoff, summaries))
    metadata = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "cutoff": cutoff,
        "repetitions": arguments.repetitions,
        "git_commit": git_commit(),
        "environment": selected_env(),
        "query_row_counts": {row["query"]: int(row["row_count"]) for row in timings},
    }
    (RESULTS_DIR / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Wrote benchmark evidence to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
