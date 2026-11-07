import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.catalog.ingest import prepare_catalog
from src.catalog.repository import COLUMNS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/flipkart/flipkart_com-ecommerce_sample.csv"),
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--browser-csv", type=Path)
    args = parser.parse_args()
    if args.browser_csv:
        if args.browser_csv.resolve() == args.input.resolve():
            parser.error("Browser CSV must not overwrite the source")
        args.browser_csv.parent.mkdir(parents=True, exist_ok=True)
        with (
            args.input.open(encoding="utf-8-sig", newline="") as source,
            args.browser_csv.open("w", encoding="utf-8", newline="") as output,
        ):
            reader = csv.DictReader(source)
            if not set(COLUMNS).issubset(reader.fieldnames or []):
                parser.error("Source CSV is missing required columns")
            writer = csv.DictWriter(output, fieldnames=COLUMNS, extrasaction="ignore")
            writer.writeheader()
            count = 0
            for row in reader:
                writer.writerow(row)
                count += 1
        print(json.dumps({"status": "ok", "rows": count, "columns": list(COLUMNS)}))
        return
    products, rejected, report = prepare_catalog(args.input)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, rows in (("products", products), ("rejected", rejected)):
            with (args.output_dir / f"{name}.jsonl").open(
                "w", encoding="utf-8"
            ) as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        (args.output_dir / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
