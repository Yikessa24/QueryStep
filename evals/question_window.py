"""Shared pyKT question-window prediction path for validation and test."""

from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

from data_pipeline.preprocess import DATASET, GROUPED_TRAIN, sha256
from kt.pykt_source import bundled_pykt, epikt_analysis
from kt.scoring import EpiKTScorer
from kt.train import read_json, verified_data


def predict(run: Path, data: Path, split: str, batch_size: int, allow_smoke: bool):
    import torch

    if split not in {"validation", "test"} or batch_size < 1:
        raise ValueError("Expected validation or test and a positive batch size.")
    torch.set_num_threads(min(torch.get_num_threads(), 4))
    record = read_json(run / "config.json")
    if sha256(data / "manifest.json") != record["data_manifest_sha256"]:
        raise ValueError("Prediction requires the same prepared dataset as training.")
    filename = GROUPED_TRAIN if split == "validation" else "test_question_window_sequences.csv"
    config, manifest = verified_data(data, (filename, "train_valid.csv"))
    scorer = EpiKTScorer(run, allow_smoke=allow_smoke)
    bundled_pykt()
    from pykt.datasets.data_loader import KTDataset

    fold = record["params"]["fold"] if split == "validation" else -1
    with TemporaryDirectory(prefix="querystep-eval-") as temporary:
        staged_csv = Path(temporary) / filename
        copyfile(data / filename, staged_csv)
        if sha256(staged_csv) != manifest["files"][filename]:
            raise ValueError("Evaluation CSV changed during staging.")
        dataset = KTDataset(str(staged_csv), config[DATASET]["input_type"], {fold}, qtest=True)
    loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size)
    if not len(loader):
        raise ValueError("No question-window rows for this split.")
    results = epikt_analysis().evaluate_question_window_late_mean(
        scorer.model, _QuestionBatches(loader), scorer.device
    )
    return record, results


class _QuestionBatches:
    def __init__(self, loader):
        self.loader = loader

    def __len__(self):
        return len(self.loader)

    def __iter__(self):
        for data, metadata in self.loader:
            yield data, {key: value.cpu() for key, value in metadata.items()}
