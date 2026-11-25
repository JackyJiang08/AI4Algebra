"""CLI for the keyless retrieval API benchmark."""

from argparse import ArgumentParser
from pathlib import Path
from tempfile import NamedTemporaryFile

from ai4algebra.api_benchmark import (
    BenchmarkConfigError,
    load_queries,
    load_settings,
    run_benchmark,
)
from ai4algebra.api_benchmark._queries import SERVICES


def _write_report(path: Path, report: str) -> None:
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(report)
            handle.close()
            temporary.replace(path)
        finally:
            handle.close()
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--queries", type=Path, required=True, help="Version 1 benchmark query JSON"
    )
    parser.add_argument("--output", type=Path, required=True, help="Report JSON path")
    parser.add_argument(
        "--dotenv", type=Path, default=Path(".env"), help="Settings file"
    )
    parser.add_argument(
        "--live", action="store_true", help="Send requests to enabled services"
    )
    parser.add_argument(
        "--service", choices=SERVICES, help="Restrict the run to one service"
    )
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.dotenv)
        queries, digest = load_queries(args.queries)
        if args.output.resolve() in {args.queries.resolve(), args.dotenv.resolve()}:
            raise BenchmarkConfigError(
                "the report path must differ from the input paths"
            )
        if args.output.is_dir():
            raise BenchmarkConfigError("the report path must be a file")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report = run_benchmark(
            queries, settings, digest, live=args.live, service=args.service
        )
        _write_report(args.output, report.to_json())
    except BenchmarkConfigError as error:
        parser.error(str(error))
    except (OSError, RuntimeError):
        parser.error("could not write the benchmark report")

    print(f"Wrote benchmark report to {args.output}")
    for service, summary in report.summaries.items():
        print(
            f"  {service}  attempted {summary.attempted_count}, "
            f"succeeded {summary.success_count}, skipped {summary.skipped_count}"
        )
    return int(report.has_errors)


if __name__ == "__main__":
    raise SystemExit(main())
