"""Train the bundled EpiKT on DBE-KT22 using pyKT's loader and trainer."""

import argparse
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from data_pipeline.preprocess import DATASET, GROUPED_TRAIN, sha256, write_json
from kt.pykt_source import PYKT_ROOT, ROOT, bundled_pykt, pykt_source_digest

DEFAULT_DATA = ROOT / "data/processed/dbe_kt22_sql_core"
MODEL_SOURCE = PYKT_ROOT / "pykt/models/epikt.py"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verified_data(path: Path, fields: tuple[str, ...]) -> tuple[dict, dict]:
    manifest = read_json(path / "manifest.json")
    if manifest["dataset"] != DATASET:
        raise ValueError("Expected a DBE-KT22 preprocessing manifest.")
    for filename in ("data_config.json", "keyid2idx.json", *fields):
        if sha256(path / filename) != manifest["files"][filename]:
            raise ValueError(f"Preprocessed artifact changed: {filename}")
    config = read_json(path / "data_config.json")
    config[DATASET]["dpath"] = str(path.resolve())
    return config, manifest


def source_question_kcs(raw: Path) -> dict[str, list[int]]:
    lines = raw.read_text(encoding="utf-8").splitlines()
    if len(lines) % 6:
        raise ValueError("Expected six pyKT lines per learner.")
    mapping = {}
    for index in range(0, len(lines), 6):
        questions = lines[index + 1].split(",")
        concepts = lines[index + 2].split(",")
        for question, raw_kcs in zip(questions, concepts, strict=True):
            ordered = [int(kc) for kc in raw_kcs.split("_")]
            if mapping.setdefault(question, ordered) != ordered:
                raise ValueError(f"Question {question} has inconsistent KCs.")
    return mapping


def train(data_path: Path, run: Path, fold: int, seed: int, epochs: int,
          batch_size: int, emb_type: str, smoke: bool = False) -> None:
    import torch

    if epochs < 1 or batch_size < 1:
        raise ValueError("epochs and batch-size must be positive.")
    if emb_type == "qid_alibi" and not torch.cuda.is_available():
        raise RuntimeError("Bundled qid_alibi requires NVIDIA CUDA. Use --smoke for a CPU check.")

    pykt = bundled_pykt()
    config, manifest = verified_data(data_path, (GROUPED_TRAIN, "data.txt"))
    data_config = config[DATASET]
    if fold not in data_config["folds"]:
        raise ValueError(f"Unknown validation fold: {fold}")
    data_config["train_valid_file"] = data_config["grouped_train_valid_file"]
    model_config = {
        "d_model": 16 if smoke else 64, "d_ff": 32 if smoke else 128,
        "num_attn_heads": 4, "n_blocks": 1, "n_scales": 2,
        "dropout": 0.1, "final_fc_dim": 32 if smoke else 128,
    }
    run.mkdir(parents=True, mode=0o700, exist_ok=False)
    torch.set_num_threads(min(torch.get_num_threads(), 4))
    pykt.set_seed(seed)
    # pyKT eagerly loads tensors and saves a pickle beside each input CSV.
    # A private staging directory keeps caches from earlier runs out of the loader.
    with TemporaryDirectory(prefix="querystep-train-") as temporary:
        staged_csv = Path(temporary) / GROUPED_TRAIN
        shutil.copyfile(data_path / GROUPED_TRAIN, staged_csv)
        if sha256(staged_csv) != manifest["files"][GROUPED_TRAIN]:
            raise ValueError("Training CSV changed during staging.")
        staged_config = {DATASET: {**data_config, "dpath": temporary}}
        train_loader, valid_loader, *_ = pykt.init_dataset4train(
            DATASET, "epikt", staged_config, fold, batch_size
        )
    if smoke:
        # Exercise real pyKT optimizer and validation on small slices.
        from itertools import islice
        train_loader = list(islice(train_loader, 2))
        valid_loader = list(islice(valid_loader, 4))

    model = pykt.init_model("epikt", model_config, data_config, emb_type)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    record = {
        "train_config": {"batch_size": batch_size, "num_epochs": epochs,
                         "seq_len": data_config["maxlen"], "optimizer": "adam"},
        "model_config": model_config,
        "data_config": data_config,
        "params": {"model_name": "epikt", "dataset_name": DATASET, "emb_type": emb_type,
                   "fold": fold, "seed": seed, "smoke": smoke},
        "data_manifest_sha256": sha256(data_path / "manifest.json"),
        "model_source_sha256": sha256(MODEL_SOURCE),
        "pykt_source_sha256": pykt_source_digest(),
    }
    config_path = run / "config.json"
    write_json(config_path, record)
    shutil.copyfile(data_path / "keyid2idx.json", run / "keyid2idx.json")
    question_kcs = run / "question_kcs.json"
    write_json(question_kcs, source_question_kcs(data_path / "data.txt"))
    result = pykt.train_model(
        model, train_loader, valid_loader, epochs, optimizer, str(run), save_model=True
    )
    checkpoint = run / f"{emb_type}_model.ckpt"
    if not checkpoint.is_file():
        raise RuntimeError("pyKT did not save a valid checkpoint.")
    write_json(run / "training_metrics.json", {
        "validation_concept_auc": float(result[4]), "validation_concept_acc": float(result[5]),
        "best_epoch": int(result[6]), "smoke": smoke,
        "config_sha256": sha256(config_path),
        "checkpoint_sha256": sha256(checkpoint),
        "mapping_sha256": manifest["files"]["keyid2idx.json"],
        "question_kcs_sha256": sha256(question_kcs),
    })
    print(f"Saved {checkpoint}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--fold", type=int, default=0)
    parser.add_argument("--seed", type=int, default=3407)
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--emb-type", choices=["qid", "qid_alibi"])
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    train(args.data, args.run, args.fold, args.seed, 1 if args.smoke else args.epochs,
          args.batch_size if args.batch_size is not None else (16 if args.smoke else 32),
          args.emb_type or ("qid" if args.smoke else "qid_alibi"), args.smoke)


if __name__ == "__main__":
    main()
