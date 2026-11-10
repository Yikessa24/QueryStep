"""Check a catalog and release package without loading PyTorch or opening a GPU."""

import argparse
import json
from pathlib import Path

from api.catalog import Catalog
from kt.release import require_release_report
from kt.scoring import load_calibration, question_mapping_issue, verify_run_files


def preflight(run: Path, catalog: Catalog, *, allow_smoke: bool = False) -> dict:
    files = verify_run_files(run, allow_smoke=allow_smoke)
    calibration = load_calibration(run, files.config, files.training)
    supported = set(calibration["source_questions_with_training_support"])
    issues = []
    for item in sorted(catalog.items.values(), key=lambda value: value.id):
        issue = question_mapping_issue(
            item.source_question_id, item.source_kcs, files.mapping["questions"],
            files.question_kcs, supported,
        )
        if issue:
            issues.append({"item_id": item.id, "reason": issue})

    smoke = files.config["params"]["smoke"]
    release_ok = False
    if not smoke:
        try:
            require_release_report(run, files.config)
            release_ok = True
        except (OSError, KeyError, TypeError, ValueError):
            pass
    return {
        "catalog_revision": catalog.revision, "items": len(catalog.items),
        "mapped_and_supported": len(catalog.items) - len(issues), "issues": issues,
        "smoke": smoke, "release_report_passed": release_ok,
        "production_package_compatible": release_ok and not issues,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--allow-smoke", action="store_true")
    args = parser.parse_args()
    try:
        report = preflight(args.run, Catalog.load(args.catalog), allow_smoke=args.allow_smoke)
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f"Catalog preflight failed: {error}\n")
    print(json.dumps(report, indent=2))
    if not report["production_package_compatible"] and not (report["smoke"] and not report["issues"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
