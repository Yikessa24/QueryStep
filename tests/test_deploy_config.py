"""Deployment contract tests for Dockerfile, Compose, Nginx SSE, and start.sh.

Runs purely locally without requiring a Docker daemon: simulates Dockerfile.api
COPY directives against .dockerignore in a temporary staging directory, compiles
staged sources, validates compose.yaml and nginx.conf, and checks start.sh syntax.
"""

import compileall
from fnmatch import fnmatch
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _dockerignore_rules(path: Path) -> list[str]:
    rules = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            rules.append(line)
    return rules


def _is_ignored(rel_posix: str, rules: list[str]) -> bool:
    parts = rel_posix.split("/")
    for rule in rules:
        if rule.startswith("**/"):
            suffix = rule[3:]
            if any(fnmatch(part, suffix) for part in parts) or fnmatch(rel_posix, suffix):
                return True
        elif fnmatch(rel_posix, rule) or fnmatch(parts[0], rule):
            return True
    return False


def _stage_dockerfile_api(dockerfile: Path, dockerignore: Path, dest: Path) -> list[str]:
    rules = _dockerignore_rules(dockerignore)
    copied = []
    for raw in dockerfile.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("COPY "):
            continue
        tokens = line.split()[1:]
        sources, target = tokens[:-1], tokens[-1]
        for src in sources:
            src_path = ROOT / src
            if not src_path.exists():
                raise AssertionError(f"Dockerfile COPY source does not exist: {src}")
            if src_path.is_file():
                rel = src_path.relative_to(ROOT).as_posix()
                if _is_ignored(rel, rules):
                    raise AssertionError(f"Dockerfile COPY file is excluded by .dockerignore: {rel}")
                out_dir = dest / target if target.endswith("/") else dest / target
                if target.endswith("/") or target in {".", "./"}:
                    out_file = (dest / target / src_path.name).resolve()
                else:
                    out_file = (dest / target).resolve()
                out_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, out_file)
                copied.append(out_file.relative_to(dest.resolve()).as_posix())
            else:
                target_root = dest / target
                for item in src_path.rglob("*"):
                    if not item.is_file():
                        continue
                    rel = item.relative_to(ROOT).as_posix()
                    if _is_ignored(rel, rules):
                        continue
                    out_file = target_root / item.relative_to(src_path)
                    out_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, out_file)
                    copied.append(out_file.relative_to(dest).as_posix())
    return copied


class DeployConfigTest(unittest.TestCase):
    def test_dockerfile_api_stages_all_runtime_packages_and_compiles(self):
        dockerfile = ROOT / "deploy/Dockerfile.api"
        dockerignore = ROOT / ".dockerignore"
        text = dockerfile.read_text(encoding="utf-8")
        self.assertIn("ARG QUERYSTEP_EXTRAS=api,diagnostics,kt,knowledge", text)
        self.assertIn("mkdir -p /app/runtime", text)

        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            copied = set(_stage_dockerfile_api(dockerfile, dockerignore, stage))
            required = {
                "pyproject.toml",
                "api/main.py",
                "api/workbench.py",
                "api/diagnostics.py",
                "api/learning_memory.py",
                "sql_lab/server.py",
                "sql_lab/client.py",
                "sql_lab/contracts.py",
                "sql_lab/workbench.py",
                "sql_lab/query_worker.py",
                "tutor/agent.py",
                "tutor/workbench_coach.py",
                "tutor/diagnosis.py",
                "tutor/coach.py",
                "course_content/catalog.json",
                "course_content/sql_tasks.py",
                "course_content/knowledge_index.py",
                "course_content/evidence_retrieval.py",
                "course_content/diagnosis_cards.py",
                "course_content/transfer.py",
                "kt/scoring.py",
                "kt/release.py",
                "kt/cpu_epikt.py",
                "data_pipeline/dbe_kt22.py",
            }
            missing = sorted(required - copied)
            self.assertEqual(missing, [], f"Missing files in Dockerfile.api build context: {missing}")

            knowledge_cards = [p for p in copied if p.startswith("course_content/knowledge/") and p.endswith(".md")]
            self.assertGreaterEqual(len(knowledge_cards), 16)

            # Ensure private artifacts/research remain excluded from baked image layers.
            self.assertFalse(any(p.startswith(("artifacts/", "research/")) for p in copied))

            compiled = compileall.compile_dir(str(stage), quiet=1)
            self.assertTrue(compiled, "Staged Python sources failed bytecode compilation")

    def test_compose_wires_full_feature_env_volumes_and_healthcheck(self):
        data = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
        self.assertIn("services", data)
        api = data["services"]["api"]
        web = data["services"]["web"]
        env = api["environment"]

        expected_env_keys = {
            "QUERYSTEP_DATABASE_URL",
            "PGPASSWORD",
            "QUERYSTEP_CATALOG",
            "QUERYSTEP_EPIKT_RUN",
            "QUERYSTEP_DIAGNOSTICS_ENABLED",
            "QUERYSTEP_DIAGNOSIS_CHECKPOINTS",
            "QUERYSTEP_COACH_ENABLED",
            "QUERYSTEP_COACH_MODEL",
            "QUERYSTEP_EXPLANATION_MODEL",
            "QUERYSTEP_KNOWLEDGE_INDEX",
            "QUERYSTEP_EMBEDDING_MODEL",
            "QUERYSTEP_LLM_BASE_URL",
            "QUERYSTEP_LLM_MODEL",
            "QUERYSTEP_LLM_API_KEY",
            "QUERYSTEP_LLM_TIMEOUT_SECONDS",
            "QUERYSTEP_LLM_TRANSIENT_RETRIES",
            "QUERYSTEP_LLM_ALLOW_INSECURE_HTTP",
            "QUERYSTEP_LLM_ALLOW_MAPPED_ITEMS",
        }
        self.assertTrue(expected_env_keys.issubset(env.keys()),
                        f"Missing compose env keys: {sorted(expected_env_keys - set(env.keys()))}")
        self.assertEqual(env["QUERYSTEP_DIAGNOSIS_CHECKPOINTS"], "/app/runtime/diagnosis-checkpoints.sqlite3")

        volumes = api.get("volumes", [])
        self.assertIn("./artifacts:/app/artifacts:ro", volumes)
        self.assertIn("./research:/app/research:ro", volumes)
        self.assertIn("api_runtime:/app/runtime", volumes)
        self.assertIn("api_runtime", data.get("volumes", {}))

        self.assertIn("healthcheck", api)
        self.assertIn("/healthz", " ".join(api["healthcheck"]["test"]))
        self.assertEqual(web["depends_on"]["api"]["condition"], "service_healthy")

    def test_nginx_disables_buffering_for_diagnosis_sse(self):
        conf = (ROOT / "deploy/nginx.conf").read_text(encoding="utf-8")
        sse_match = re.search(
            r"location\s+~\s+\^/api/diagnosis/\[\^/\]\+/events\$\s*\{(?P<body>[^}]*)\}",
            conf,
            re.DOTALL,
        )
        self.assertIsNotNone(sse_match, "Dedicated SSE location block missing in deploy/nginx.conf")
        body = sse_match.group("body")
        for directive in (
            "proxy_pass http://api:8000;",
            "proxy_http_version 1.1;",
            'proxy_set_header Connection "";',
            "proxy_buffering off;",
            "proxy_cache off;",
            "chunked_transfer_encoding off;",
            'add_header X-Accel-Buffering "no" always;',
            "proxy_read_timeout",
        ):
            self.assertIn(directive, body)

        api_source = (ROOT / "api/main.py").read_text(encoding="utf-8")
        self.assertIn('"X-Accel-Buffering": "no"', api_source)

    def test_start_sh_syntax_and_auto_venv_detection(self):
        script = ROOT / "start.sh"
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = script.read_text(encoding="utf-8")
        self.assertIn("artifacts/diagnostics-venv/bin/python", text)
        self.assertIn("sql_workbench_ready", text)


if __name__ == "__main__":
    unittest.main()
