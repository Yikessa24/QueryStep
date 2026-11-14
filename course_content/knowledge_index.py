"""Build and query a versioned index of reviewed Markdown lessons."""

import argparse
from contextlib import closing
from datetime import date
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic
from urllib.parse import urlparse

SOURCE = Path(__file__).with_name("knowledge")
INDEX_VERSION = 1
MODEL_NAME = "BAAI/bge-small-zh-v1.5"
LEXICAL_MIN = 0.4
DENSE_MIN = 0.47
SQL_TOKENS = {"count(*)": "sqlcountstar", "count(column)": "sqlcountcolumn", "count(列)": "sqlcountcolumn",
              ">=": "sqlgte", "<=": "sqllte", ">": "sqlgt", "<": "sqllt", "is null": "sqlisnull"}
OUT_OF_SCOPE = re.compile(r"\b(?:json_table|create\s+index|mysql|sql\s+server)\b|并行索引")
SEGMENTS = re.compile(r"[a-z_][a-z_0-9]*|\d+|[\u3400-\u9fff]+")
HAN = re.compile(r"[\u3400-\u9fff]+")


def lexical_terms(text):
    text = text.lower()
    for symbol, token in SQL_TOKENS.items():
        text = text.replace(symbol, f" {token} ")
    terms = []
    for part in SEGMENTS.findall(text):
        if HAN.fullmatch(part):
            # Index overlapping character pairs with the same normalization at query time.
            terms.extend(part[i:i + 2] for i in range(max(1, len(part) - 1)))
        else:
            terms.append(part)
    return terms


def load_lessons(directory=SOURCE):
    chunks = {}
    documents = set()
    for path in sorted(directory.glob("*.md")):
        _, metadata, body = path.read_text(encoding="utf-8").split("---\n", 2)
        doc = json.loads(metadata)
        identifier = doc["id"]
        if identifier in documents or not re.fullmatch(r"[a-z][a-z-]*", identifier):
            raise ValueError(f"Invalid or duplicate document ID: {identifier}")
        documents.add(identifier)
        source = urlparse(doc["source_url"])
        if (source.scheme != "https" or source.hostname not in {"www.sqlite.org", "www.postgresql.org"}
                or not doc["source_section"].strip() or doc["dialect"] not in {"sqlite", "postgresql", "sql"}
                or type(doc["version"]) is not int or doc["version"] < 1):
            raise ValueError(f"Invalid source metadata: {identifier}")
        date.fromisoformat(doc["reviewed_on"])
        parent, *parts = re.split(r"(?m)^## ", body)
        if not parts or not parent.strip().startswith("# "):
            raise ValueError(f"Missing headings: {identifier}")
        for part in parts:
            heading, _, content = part.partition("\n")
            slug, title = (bit.strip() for bit in heading.split("|", 1))
            chunk_id = f"{identifier}/{slug}"
            if chunk_id in chunks or not re.fullmatch(r"[a-z][a-z-]*", slug) or not title:
                raise ValueError(f"Invalid or duplicate section: {chunk_id}")
            notes = dict(re.findall(r"(?m)^<!-- (keywords|experiment): (.*?) -->$", content))
            if notes.get("experiment") not in (None, "join_filter", "join_count", "having_boundary"):
                raise ValueError(f"Unknown experiment: {chunk_id}")
            excerpt = re.sub(r"(?m)^<!-- .*? -->\n?", "", content).strip()
            if not excerpt or not notes.get("keywords"):
                raise ValueError(f"Missing text or keywords: {chunk_id}")
            chunks[chunk_id] = {
                "id": chunk_id, "title": title, "parent": parent.strip()[2:],
                "text": excerpt, "keywords": notes["keywords"], "experiment": notes.get("experiment"), **{
                    key: doc[key] for key in ("version", "topic", "dialect", "source_url", "source_section", "reviewed_on")
                },
            }
    if not chunks:
        raise ValueError("No reviewed lesson fragments found.")
    return chunks


class Embedder:
    def __init__(self, model_path, revision=None):
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        torch.set_num_threads(min(torch.get_num_threads(), 2))
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, revision=revision, trust_remote_code=False)
        self.model = AutoModel.from_pretrained(
            model_path, revision=revision, trust_remote_code=False, use_safetensors=True,
        ).eval()
        if Path(model_path).is_dir():
            path = Path(model_path)
            digest = sha256()
            for name in ("model.safetensors", "config.json", "tokenizer.json"):
                with (path / name).open("rb") as file:
                    digest.update(name.encode())
                    digest.update(file_digest(file, "sha256").digest())
            self.identity = digest.hexdigest()
        else:
            self.identity = self.model.config._commit_hash
        if not self.identity:
            raise ValueError("Embedding model revision could not be determined.")

    def encode(self, texts, *, query=False):
        if query:
            texts = ["为这个句子生成表示以用于检索相关文章：" + text for text in texts]
        with self.torch.inference_mode():
            features = self.tokenizer(texts, padding=True, truncation=True, max_length=256, return_tensors="pt")
            hidden = self.model(**features).last_hidden_state[:, 0]
            return self.torch.nn.functional.normalize(hidden, dim=1).cpu().numpy()


def _digest(chunks):
    return sha256(json.dumps(chunks, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build(output, embedder, *, directory=SOURCE):
    chunks = load_lessons(directory)
    output.parent.mkdir(parents=True, exist_ok=True)
    vectors = embedder.encode([f"{card['parent']} {card['title']} {card['text']}" for card in chunks.values()])
    manifest = {"format": INDEX_VERSION, "corpus_sha256": _digest(chunks), "embedding_identity": embedder.identity,
                "dimension": int(vectors.shape[1]), "chunks": len(chunks)}
    with TemporaryDirectory(dir=output.parent) as temporary:
        scratch = Path(temporary) / "index.sqlite3"
        with closing(sqlite3.connect(scratch)) as db, db:
            db.execute("CREATE TABLE manifest (data TEXT NOT NULL)")
            db.execute("INSERT INTO manifest VALUES (?)", (json.dumps(manifest),))
            db.execute("CREATE TABLE chunks (id TEXT PRIMARY KEY, data TEXT NOT NULL, vector BLOB NOT NULL)")
            db.execute("CREATE VIRTUAL TABLE lexical USING fts5(id UNINDEXED, title, body, keywords)")
            for (identifier, card), vector in zip(chunks.items(), vectors, strict=True):
                db.execute("INSERT INTO chunks VALUES (?, ?, ?)", (identifier, json.dumps(card, ensure_ascii=False),
                                                                   vector.astype("<f4").tobytes()))
                db.execute("INSERT INTO lexical VALUES (?, ?, ?, ?)", (identifier, *(
                    " ".join(lexical_terms(card[key])) for key in ("title", "text", "keywords")
                )))
        os.replace(scratch, output)
    return manifest


class KnowledgeIndex:
    def __init__(self, path, embedder=None):
        import numpy as np

        uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
        self._lexical_lock = Lock()
        db = sqlite3.connect(uri, uri=True, check_same_thread=False)
        try:
            self.manifest = json.loads(db.execute("SELECT data FROM manifest").fetchone()[0])
            if self.manifest["format"] != INDEX_VERSION:
                raise ValueError("Unknown index format.")
            records = db.execute("SELECT id, data, vector FROM chunks ORDER BY id").fetchall()
            self.cards = {key: json.loads(data) for key, data, _ in records}
            if (_digest(self.cards) != self.manifest["corpus_sha256"]
                    or len(records) != self.manifest["chunks"]):
                raise ValueError("Index content does not match its manifest.")
            self.vectors = np.stack([np.frombuffer(vector, dtype="<f4") for _, _, vector in records])
            if self.vectors.shape[1] != self.manifest["dimension"] or not np.isfinite(self.vectors).all():
                raise ValueError("Invalid embedded vectors.")
        except BaseException:
            db.close()
            raise
        self.embedder = embedder if embedder and self.manifest["embedding_identity"] == embedder.identity else None
        self._lexical_db = db

    def close(self):
        self._lexical_db.close()

    def search(self, query, topic=None, top_k=3, mode="hybrid", dialect="sqlite"):
        start = monotonic()
        actual = "keyword" if mode in {"vector", "hybrid"} and self.embedder is None else mode
        if OUT_OF_SCOPE.search(query.lower()):
            return {"cards": [], "mode": actual, "corpus": self.manifest["corpus_sha256"],
                    "elapsed_ms": round((monotonic() - start) * 1000, 3)}
        candidates = {key for key, value in self.cards.items() if value["dialect"] in {dialect, "sql"}}
        tokens = set(lexical_terms(query))
        # Exclude chunks with no corpus-specific anchor or adequate semantic match.
        # Negatives and paraphrases in the holdout set measure this tradeoff.
        lexical = {}
        if tokens and (mode != "vector" or self.embedder is None):
            expression = " OR ".join(f'"{token}"' for token in sorted(tokens))
            with self._lexical_lock:
                matches = self._lexical_db.execute("SELECT id, bm25(lexical, 0, 2, 1, 3) FROM lexical "
                                                   "WHERE lexical MATCH ? ORDER BY 2, id", (expression,))
                lexical = {key: -rank for key, rank in matches if key in candidates}
        dense = {}
        if mode in {"vector", "hybrid"}:
            if self.embedder is not None:
                scores = self.vectors @ self.embedder.encode([query], query=True)[0]
                dense = {key: float(score) for key, score in zip(self.cards, scores, strict=True) if key in candidates}
        eligible = {key for key in candidates if lexical.get(key, 0) >= LEXICAL_MIN or dense.get(key, 0) >= DENSE_MIN}
        if actual == "hybrid" and not any(rank >= LEXICAL_MIN for rank in lexical.values()):
            eligible = {key for key in candidates if dense.get(key, 0) >= DENSE_MIN + 0.06}
        rankings = []
        if actual in {"keyword", "hybrid"}:
            rankings.append(sorted(lexical, key=lambda key: (-lexical[key], key))[:12])
        if actual in {"vector", "hybrid"}:
            rankings.append(sorted(dense, key=lambda key: (-dense[key], key))[:12])
        scores = {}
        for ranking in rankings:
            for rank, key in enumerate(ranking, 1):
                if key in eligible:
                    scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        ranked = sorted(scores, key=lambda key: (-(scores[key] + 0.0006 * (self.cards[key]["topic"] == topic)), key))
        return {"cards": [self.cards[key] for key in ranked[:top_k]], "mode": actual,
                "corpus": self.manifest["corpus_sha256"], "elapsed_ms": round((monotonic() - start) * 1000, 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--revision")
    args = parser.parse_args()
    if not Path(args.model).is_dir() and not args.revision:
        parser.error("set --revision to a Hugging Face commit or use a local --model directory")
    print(json.dumps(build(args.output, Embedder(args.model, args.revision)), ensure_ascii=False))


if __name__ == "__main__":
    main()
