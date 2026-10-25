"""Small, version-pinned Pinecone vectors adapter; source text stays local.

No automatic creation, deletion, reindexing, or keyword fallback during a query.
The caller supplies a CURRENT server-side plan, never client namespaces.
"""

import hashlib
import json
import math
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .benchmark import Jina, allowed
from .ingestion import read_json, write_json

API_VERSION = "2025-10"
DIMENSION = 1024
DEFAULT_INDEX = "gstrag-jina-v1"
NAMESPACES = {"icai_book": "icai_books", "firm_book": "firm_books", "notification": "notifications"}


def namespaces_for(plan):
    if plan not in {"plus", "pro"}:
        raise ValueError("Unknown server-side plan")
    return ["icai_books", "notifications"] if plan == "plus" else ["icai_books", "firm_books", "notifications"]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def app_jina(root):
    """Seed app-owned cache, leaving frozen experiment caches untouched."""
    directory = Path(root) / "data/app/cache"
    destination = directory / "jina_cache.json"
    if not destination.exists():
        old = Path(root) / "data/processed/notification_experiment_v01/jina_cache.json"
        write_json(destination, read_json(old) if old.exists() else {})
    return Jina(directory)


class Snapshot:
    def __init__(self, bundle):
        self.corpus_id = digest({"bundle": bundle, "model": Jina.model, "dimension": DIMENSION,
                                 "passage_task": "retrieval.passage", "schema": "gst-vectors-v1"})
        self.records = bundle["records"]
        self.by_id = {}
        chunks = set()
        for record in self.records:
            if record["chunk_id"] in chunks or record["source_type"] not in NAMESPACES:
                raise ValueError("Duplicate chunk or unsupported source type")
            chunks.add(record["chunk_id"])
            expected_plan = "pro" if record["source_type"] == "firm_book" else "plus"
            if record["plan_required"] != expected_plan:
                raise ValueError("Source plan mismatch")
            self.by_id[self.vector_id(record)] = record

    def vector_id(self, record):
        return digest([self.corpus_id, record["chunk_id"]])

    def metadata(self, record):
        # Numeric arrays are not supported metadata; pages are string arrays.
        return {"corpus_id": self.corpus_id, "embedding_model": Jina.model,
                "chunk_id": record["chunk_id"], "document_id": record["document_id"],
                "source_type": record["source_type"], "plan_required": record["plan_required"],
                "pages": [str(p) for p in record["pages"]], "content_sha256": digest(record["embedding_text"])}


class PineconeStore:
    def __init__(self, snapshot, name=DEFAULT_INDEX, key=None, session=None):
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,43}[a-z0-9])?", name):
            raise ValueError("Invalid Pinecone index name")
        self.key = key or os.environ.get("PINECONE_API_KEY")
        if not self.key:
            raise ValueError("Set PINECONE_API_KEY locally; no Pinecone request made")
        self.snapshot, self.name = snapshot, name
        self.session = session or requests.Session()
        self.host = None
        self.requests = self.read_units = self.upserted = 0

    def request(self, method, path, body=None, params=None, data=False, missing_ok=False):
        base = self.host if data else "https://api.pinecone.io"
        if not base:
            raise ValueError("Connect to an existing ready index first")
        self.requests += 1
        try:
            response = self.session.request(method, base + path, params=params, json=body, timeout=(5, 30),
                allow_redirects=False, headers={"Api-Key": self.key, "X-Pinecone-Api-Version": API_VERSION,
                                                "Content-Type": "application/json"})
        except requests.RequestException:
            raise RuntimeError("Pinecone transport unavailable; details omitted") from None
        if missing_ok and response.status_code == 404:
            return None
        if not response.ok or 300 <= response.status_code < 400:
            raise RuntimeError(f"Pinecone HTTP {response.status_code}; response body omitted")
        try:
            payload = response.json()
            usage = payload.get("usage", {})
            self.read_units += usage.get("read_units", usage.get("readUnits", 0))
            return payload
        except (ValueError, TypeError, AttributeError):
            raise RuntimeError("Invalid Pinecone response; body omitted") from None

    def describe(self, missing_ok=False):
        return self.request("GET", "/indexes/" + self.name, missing_ok=missing_ok)

    def create(self):
        # Explicit CLI-only operation. Never changes billing plans or deletes.
        return self.request("POST", "/indexes", {"name": self.name, "vector_type": "dense",
            "dimension": DIMENSION, "metric": "cosine", "deletion_protection": "enabled",
            "spec": {"serverless": {"cloud": "aws", "region": "us-east-1"}},
            "tags": {"application": "gst-rag", "vector_schema": "gst-vectors-v1"}})

    def connect(self):
        info = self.describe()
        if (info.get("dimension") != DIMENSION or info.get("metric") != "cosine"
                or info.get("vector_type") != "dense" or info.get("embed")
                or info.get("tags", {}).get("application") != "gst-rag"):
            raise ValueError("Index is not an owned, compatible Jina vectors index; left unchanged")
        if not info.get("status", {}).get("ready"):
            raise ValueError("Pinecone index is not ready")
        host = info.get("host", "")
        parsed = urlsplit("https://" + host)
        if (not re.fullmatch(r"[a-z0-9.-]+", host) or not host.endswith(".pinecone.io")
                or ".svc." not in host or parsed.hostname != host):
            raise ValueError("Untrusted index host; no data-plane request made")
        self.host = "https://" + host
        return info

    @staticmethod
    def vector(values):
        vector = [float(v) for v in values]
        if len(vector) != DIMENSION or not all(math.isfinite(v) for v in vector) or not any(vector):
            raise ValueError("Embedding dimension/nonfinite/zero-vector mismatch")
        return vector

    def upsert(self, embeddings):
        if len(embeddings) != len(self.snapshot.records):
            raise ValueError("Passage/vector count mismatch")
        batches = {ns: [] for ns in NAMESPACES.values()}
        # Validate ALL input before the first write.
        for record, embedding in zip(self.snapshot.records, embeddings):
            batches[NAMESPACES[record["source_type"]]].append({"id": self.snapshot.vector_id(record),
                "values": self.vector(embedding), "metadata": self.snapshot.metadata(record)})
        for ns, vectors in batches.items():
            for start in range(0, len(vectors), 50):
                batch = vectors[start:start + 50]
                result = self.request("POST", "/vectors/upsert", {"namespace": ns, "vectors": batch}, data=True)
                if result.get("upsertedCount") != len(batch):
                    raise ValueError("Pinecone did not acknowledge the full upsert batch")
                self.upserted += len(batch)

    def search(self, query_vector, plan, top_k=10):
        """Return sorted union of top_k PER allowed namespace, hydrated locally.

        Taking global top_k afterward is sufficient for comparison; the service
        takes book top-10 and adds mandatory notification context separately.
        """
        namespaces = namespaces_for(plan)
        if type(top_k) is not int or not 1 <= top_k <= 100:
            raise ValueError("top_k outside demo bounds")
        vector = self.vector(query_vector)
        found, seen = [], set()
        for namespace in namespaces:
            result = self.request("POST", "/query", {"namespace": namespace, "vector": vector, "topK": top_k,
                "includeValues": False, "includeMetadata": True,
                "filter": {"corpus_id": {"$eq": self.snapshot.corpus_id}, "embedding_model": {"$eq": Jina.model}}}, data=True)
            if result.get("namespace", namespace) != namespace:
                raise ValueError("Unexpected response namespace")
            for match in result.get("matches", []):
                record = self.snapshot.by_id.get(match.get("id"))
                if (record is None or not allowed(record, plan) or NAMESPACES[record["source_type"]] != namespace
                        or match.get("metadata") != self.snapshot.metadata(record) or match["id"] in seen):
                    raise ValueError("Unknown, stale, duplicate, or unauthorized Pinecone match; query failed closed")
                score = float(match["score"])
                if not math.isfinite(score):
                    raise ValueError("Nonfinite Pinecone score")
                seen.add(match["id"])
                found.append((record, score))
        return sorted(found, key=lambda pair: (-pair[1], pair[0]["chunk_id"]))

    def verify_records(self, embeddings=None):
        """Fetch every expected vector, not just eventually-consistent counts."""
        expected = {ns: [] for ns in NAMESPACES.values()}
        for vector_id, record in self.snapshot.by_id.items():
            expected[NAMESPACES[record["source_type"]]].append(vector_id)
        local = dict(zip(self.snapshot.by_id, embeddings)) if embeddings is not None else None
        counts = {}
        for namespace, ids in expected.items():
            counts[namespace] = 0
            for start in range(0, len(ids), 50):
                batch = ids[start:start + 50]
                result = self.request("GET", "/vectors/fetch", params=[("namespace", namespace)] + [("ids", i) for i in batch], data=True)
                vectors = result.get("vectors", {})
                if set(vectors) != set(batch):
                    raise ValueError("Expected snapshot vectors not yet visible or missing")
                for vector_id in batch:
                    row, record = vectors[vector_id], self.snapshot.by_id[vector_id]
                    if row.get("metadata") != self.snapshot.metadata(record):
                        raise ValueError("Fetched vector metadata differs from local source")
                    if local is not None:
                        actual, wanted = self.vector(row["values"]), self.vector(local[vector_id])
                        if max(abs(a - b) for a, b in zip(actual, wanted)) > 1e-6:
                            raise ValueError("Fetched embedding differs from local vector")
                counts[namespace] += len(batch)
        return counts
