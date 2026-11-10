"""Load a versioned checkpoint and score candidates without their outcomes."""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from statistics import fmean

from data_pipeline.preprocess import sha256
from kt.pykt_source import bundled_pykt, pykt_source_digest
from kt.train import DATASET, MODEL_SOURCE, read_json


@dataclass(frozen=True)
class GradedAttempt:
    question_id: int
    correct: int


@dataclass(frozen=True)
class RunArtifacts:
    config: dict
    training: dict
    mapping: dict
    question_kcs: dict
    checkpoint: Path


def load_calibration(run: Path, config: dict, training: dict) -> dict:
    calibration = read_json(run / "calibration.json")
    params = config["params"]
    if (calibration["method"] != "validation_logistic"
            or calibration["fold"] != params["fold"]
            or calibration["smoke"] != params["smoke"]
            or calibration["checkpoint_sha256"] != training["checkpoint_sha256"]
            or calibration["mapping_sha256"] != training["mapping_sha256"]
            or calibration["catalog_kcs_sha256"] != training["question_kcs_sha256"]
            or not isfinite(calibration["coefficient"]) or calibration["coefficient"] <= 0
            or not isfinite(calibration["intercept"])):
        raise ValueError("Calibration does not match this checkpoint, fold, and mapping.")
    return calibration


def verify_run_files(run: Path, *, allow_smoke: bool = False) -> RunArtifacts:
    config_path = run / "config.json"
    config = read_json(config_path)
    params = config["params"]
    if (params["model_name"] != "epikt" or params["dataset_name"] != DATASET
            or params["emb_type"] not in {"qid", "qid_alibi"}):
        raise ValueError("Expected a QueryStep DBE-KT22 EpiKT training run.")
    if params["smoke"] and not allow_smoke:
        raise ValueError("A smoke checkpoint is restricted to local verification.")
    if sha256(MODEL_SOURCE) != config["model_source_sha256"]:
        raise ValueError("EpiKT source differs from the training run.")
    bundled_source = config.get("pykt_source_sha256")
    if bundled_source and bundled_source != pykt_source_digest():
        raise ValueError("Bundled pyKT source differs from the training run.")
    metrics = read_json(run / "training_metrics.json")
    config_hash = metrics.get("config_sha256")
    if not (config_hash is None and params["smoke"]) and config_hash != sha256(config_path):
        raise ValueError("Model configuration differs from the training run.")
    mapping_path = run / "keyid2idx.json"
    question_kcs_path = run / "question_kcs.json"
    checkpoint = run / f"{params['emb_type']}_model.ckpt"
    if (sha256(mapping_path) != metrics["mapping_sha256"]
            or sha256(question_kcs_path) != metrics["question_kcs_sha256"]
            or sha256(checkpoint) != metrics["checkpoint_sha256"]):
        raise ValueError("Checkpoint or ID mapping differs from the training run.")
    mapping = read_json(mapping_path)
    question_kcs = read_json(question_kcs_path)
    for name, size in (("questions", "num_q"), ("concepts", "num_c")):
        indexes = list(mapping[name].values())
        if (any(type(index) is not int for index in indexes)
                or sorted(indexes) != list(range(config["data_config"][size]))):
            raise ValueError(f"Invalid model indexes in {name} mapping.")
    if question_kcs.keys() != mapping["questions"].keys() or any(
            not kcs or kcs != sorted(set(kcs))
            or any(type(kc) is not int or str(kc) not in mapping["concepts"] for kc in kcs)
            for kcs in question_kcs.values()):
        raise ValueError("Question KC lists do not match the model vocabulary.")
    return RunArtifacts(config, metrics, mapping, question_kcs, checkpoint)


def question_mapping_issue(question_id: int | None, kcs: tuple[int, ...], vocabulary: dict,
                           question_kcs: dict, supported: set[int]) -> str | None:
    if question_id is None:
        return "missing_source_id"
    source = str(question_id)
    if source not in vocabulary:
        return "unknown_source_id"
    if question_kcs.get(source) != list(kcs):
        return "kc_mapping_mismatch"
    if question_id not in supported:
        return "not_seen_in_training"
    return None


class EpiKTScorer:
    def __init__(self, run: Path, *, allow_smoke: bool = False):
        import torch

        files = verify_run_files(run, allow_smoke=allow_smoke)
        config = files.config
        emb_type = config["params"]["emb_type"]
        if emb_type == "qid_alibi" and not torch.cuda.is_available():
            raise RuntimeError("The original pyKT qid_alibi implementation requires CUDA.")
        pykt = bundled_pykt()
        self.model = pykt.init_model("epikt", config["model_config"], config["data_config"], emb_type)
        self.device = next(self.model.parameters()).device
        self.model.load_state_dict(
            torch.load(files.checkpoint, map_location=self.device, weights_only=True), strict=True
        )
        self.model.eval()
        self.mapping = files.mapping
        self.question_kcs = files.question_kcs
        self.maxlen = config["data_config"]["maxlen"]

    def score(self, history: list[GradedAttempt], candidates: list[int]) -> dict[int, float]:
        import torch

        def encode(question: int) -> tuple[int, tuple[int, ...]]:
            question_index = self.mapping["questions"][str(question)]
            kc_indexes = tuple(
                self.mapping["concepts"][str(kc)] for kc in self.question_kcs[str(question)]
            )
            if not kc_indexes or len(kc_indexes) != len(set(kc_indexes)):
                raise ValueError(f"Question {question} needs a unique ordered list of KCs.")
            return question_index, kc_indexes

        prefix = []
        size = 0
        for event in reversed(history):
            if event.correct not in (0, 1):
                raise ValueError("The scored history must contain binary outcomes.")
            question, concepts = encode(event.question_id)
            if size + len(concepts) >= self.maxlen:
                break
            prefix.append([(kc, event.correct, question) for kc in concepts])
            size += len(concepts)
        if not prefix or not candidates:
            raise ValueError("Scoring requires completed history and at least one candidate.")

        common = [position for event in reversed(prefix) for position in event]
        rows = []
        spans = {}
        for candidate in dict.fromkeys(candidates):
            question, concepts = encode(candidate)
            start = len(rows)
            rows.extend(common + [(kc, 0, question)] for kc in concepts)
            spans[candidate] = slice(start, len(rows))

        data = torch.tensor(rows, dtype=torch.long, device=self.device)
        with torch.inference_mode():
            predictions, _ = self.model(data[:, :, 0], data[:, :, 1], data[:, :, 2])
            probabilities = predictions[:, -1].cpu()
        if not ((probabilities >= 0) & (probabilities <= 1)).all().item():
            raise ValueError("EpiKT returned invalid target probabilities.")
        return {candidate: fmean(probabilities[span].tolist()) for candidate, span in spans.items()}
