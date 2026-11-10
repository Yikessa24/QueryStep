"""Run the bundled pyKT splitter on normalized DBE-KT22 attempts."""

import argparse
from hashlib import file_digest
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from data_pipeline.dbe_kt22 import load_attempts, write_pykt_raw
from kt.pykt_source import PYKT_ROOT, ROOT, preprocessing_module

DATASET = "dbe_kt22"
ARCHIVE = ROOT / "data/DBE-KT22/2_DBE_KT22_datafiles_100102_csv.zip"
GROUPED_TRAIN = "train_valid_question_window_sequences.csv"


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(archive: Path, output: Path, scope: str, maxlen: int) -> dict:
    import pandas as pd

    if not 8 <= maxlen <= 200:
        raise ValueError("The DBE-KT22 pyKT window must be between 8 and 200.")
    if output.exists():
        raise FileExistsError(f"Choose a new output directory: {output}")
    if scope == "sql-core":
        settings = json.loads((ROOT / "configs/dbe_sql_core.json").read_text(encoding="utf-8"))
        kc_scope = set(settings["kc_ids"])
        exclude_images = settings["exclude_external_images"]
    else:
        kc_scope = None
        exclude_images = False

    attempts, counts = load_attempts(
        archive, kc_scope=kc_scope, exclude_external_images=exclude_images
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    splitter = preprocessing_module("split_datasets")
    with TemporaryDirectory(prefix=".dbe_kt22-", dir=output.parent) as temporary:
        stage = Path(temporary) / "dataset"
        stage.mkdir(mode=0o700)
        raw = stage / "data.txt"
        config_path = stage / "data_config.json"
        counts["after_min_length"] = write_pykt_raw(raw, attempts)
        if counts["after_min_length"]["learners"] < 7:
            raise ValueError("At least seven eligible learners are required for the pyKT split.")

        config_path.touch()
        splitter.main(str(stage), str(raw), DATASET, str(config_path), maxlen=maxlen)
        source = pd.read_csv(stage / "train_valid.csv", dtype=str)
        keys = set(source.columns)
        exists, grouped = splitter.generate_question_sequences(source, keys, maxlen=maxlen)
        if not exists or grouped.empty:
            raise RuntimeError("pyKT did not produce question-window training data.")
        grouped.to_csv(stage / GROUPED_TRAIN, index=False)

        config = json.loads(config_path.read_text(encoding="utf-8"))
        config[DATASET].update({
            "dataset_name": DATASET,
            "dpath": str(output.resolve()),
            "grouped_train_valid_file": GROUPED_TRAIN,
        })
        write_json(config_path, config)
        split_counts = source.groupby("fold")["uid"].nunique().to_dict()
        test_learners = pd.read_csv(stage / "test.csv", usecols=["uid"])["uid"].nunique()
        manifest = {
            "dataset": DATASET,
            "scope": scope,
            "scope_kc_ids": sorted(kc_scope) if kc_scope else None,
            "exclude_external_images": exclude_images,
            "source_archive_sha256": sha256(archive),
            "pykt_splitter_sha256": sha256(PYKT_ROOT / "pykt/preprocess/split_datasets.py"),
            "maxlen": maxlen,
            "counts": counts,
            "split": {"train_validation_learners_by_fold": split_counts, "test_learners": test_learners},
            "files": {path.name: sha256(path) for path in sorted(stage.iterdir())},
        }
        write_json(stage / "manifest.json", manifest)
        os.rename(stage, output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--scope", choices=["sql-core", "all"], default="sql-core")
    parser.add_argument("--maxlen", type=int, default=200)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    default = ROOT / "data/processed" / f"dbe_kt22_{args.scope.replace('-', '_')}"
    output = args.output or default
    manifest = prepare(args.archive, output, args.scope, args.maxlen)
    print(json.dumps({"output": str(output.resolve()), "counts": manifest["counts"],
                      "split": manifest["split"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
