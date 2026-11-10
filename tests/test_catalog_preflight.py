import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from api.catalog import DEFAULT_CATALOG, Catalog
from course_content.check_catalog import preflight
from course_content.import_dbe import _prompt
from data_pipeline.preprocess import sha256, write_json
from kt.train import MODEL_SOURCE


class CatalogPreflightTest(unittest.TestCase):
    def test_import_preserves_line_breaks_without_altering_sql(self):
        row = {
            "id": "1",
            "question_text": "Run this: SELECT x WHERE x &lt; 5",
            "question_rich_text": "<font>Run this:</font><br><font>SELECT x WHERE x &lt; 5</font>",
        }
        self.assertEqual(_prompt(row), "Run this:\nSELECT x WHERE x < 5")
        row["question_rich_text"] = row["question_rich_text"].replace("&lt;", "&gt;")
        with self.assertRaisesRegex(ValueError, "different rich and plain text"):
            _prompt(row)

    def test_preflight_reports_mapping_problems_without_model_or_question_text(self):
        with TemporaryDirectory() as directory:
            run = Path(directory)
            config = {
                "params": {"model_name": "epikt", "dataset_name": "dbe_kt22", "emb_type": "qid",
                           "fold": 0, "smoke": True},
                "data_config": {"num_q": 4, "num_c": 2},
                "model_source_sha256": sha256(MODEL_SOURCE),
            }
            write_json(run / "config.json", config)
            write_json(run / "keyid2idx.json", {
                "questions": {"11": 0, "12": 1, "13": 2, "14": 3},
                "concepts": {"1": 0, "2": 1},
            })
            write_json(run / "question_kcs.json", {"11": [1], "12": [1], "13": [1], "14": [2]})
            (run / "qid_model.ckpt").write_bytes(b"metadata-only test fixture")
            metrics = {
                "config_sha256": sha256(run / "config.json"),
                "mapping_sha256": sha256(run / "keyid2idx.json"),
                "question_kcs_sha256": sha256(run / "question_kcs.json"),
                "checkpoint_sha256": sha256(run / "qid_model.ckpt"),
            }
            write_json(run / "training_metrics.json", metrics)
            write_json(run / "calibration.json", {
                "method": "validation_logistic", "fold": 0, "smoke": True,
                "mapping_sha256": metrics["mapping_sha256"],
                "catalog_kcs_sha256": metrics["question_kcs_sha256"],
                "checkpoint_sha256": metrics["checkpoint_sha256"],
                "coefficient": 1.0, "intercept": 0.0,
                "source_questions_with_training_support": [11, 12, 13],
            })
            original = list(Catalog.load(DEFAULT_CATALOG).items.values())
            catalog = Catalog("metadata-check", [
                replace(original[0], source_question_id=11, source_kcs=(1,)),
                replace(original[1], source_question_id=12, source_kcs=(2,)),
                replace(original[2], source_question_id=90, source_kcs=(1,)),
                replace(original[3], source_question_id=14, source_kcs=(2,)),
                original[4],
            ])
            report = preflight(run, catalog, allow_smoke=True)
            self.assertEqual(report["mapped_and_supported"], 1)
            self.assertFalse(report["production_package_compatible"])
            self.assertEqual([entry["reason"] for entry in report["issues"]], [
                "kc_mapping_mismatch", "unknown_source_id", "not_seen_in_training", "missing_source_id",
            ])
            self.assertNotIn(original[0].prompt, str(report))
            with self.assertRaisesRegex(ValueError, "smoke checkpoint"):
                preflight(run, catalog)
            (run / "qid_model.ckpt").write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError, "Checkpoint or ID mapping"):
                preflight(run, catalog, allow_smoke=True)
