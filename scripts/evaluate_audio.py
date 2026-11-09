"""Audit human-reviewed WAV recordings and browser timing traces."""

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.audio import audit_audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/evaluation/browser-audio.json")
    )
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_audio(args.manifest, args.evidence_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "planned": result["planned"],
                "reviewed": result["reviewed"],
                "release_gates_passed": result["release_gates_passed"],
            }
        )
    )


if __name__ == "__main__":
    main()
