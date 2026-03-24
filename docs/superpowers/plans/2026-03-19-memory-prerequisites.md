# LATTICE++ Evolution Prerequisites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare the LATTICE++ memory system for Evolution by swapping to Chroma + Gemini Embedding 2, implementing LongMemEval-S and BEAM evals, building the smart grader, and running baseline scores.

**Architecture:** Replace the turbopuffer vector index with a local Chroma instance. Replace the OpenRouter embedding call with Google's Gemini Embedding 2 batch API. Keep PlanetScale (Postgres) as the canonical store and Neo4j as the graph store — only the vector index layer changes. Build eval pipelines following the existing LoCoMo pattern.

**Tech Stack:** Python 3.12+, uv, chromadb, google-generativeai (Gemini SDK), existing LATTICE++ stack

**Target repo:** `/Users/sayan/Projects/aadi-labs/memory`
**Spec:** `/Users/sayan/Projects/aadi-labs/evolution/docs/superpowers/specs/2026-03-19-memory-evolution-design.md`

---

## Build Order

```
Task 1: Add dependencies (chromadb, google-generativeai) ───┐
Task 2: Create ChromaIndex (replace turbopuffer) ───────────┤
Task 3: Create GeminiEmbeddingProvider (batch API) ─────────┤
Task 4: Wire Chroma + Gemini into VectorStore + config ─────┘
                         │
Task 5: Implement LongMemEval-S eval ──────────────────┐
Task 6: Implement BEAM eval ───────────────────────────┤ (parallel, independent)
                         │                              │
Task 7: Build smart grader script ─────────────────────┘
Task 8: Write evolution.yaml ──────────────────────────
Task 9: Run baseline ─────────────────────────────── STOP
```

Tasks 5-6 are independent of Tasks 2-4 and can run in parallel.

---

### Task 1: Add Dependencies

**Files:**
- Modify: `/Users/sayan/Projects/aadi-labs/memory/pyproject.toml`

- [ ] **Step 1: Add chromadb and google-generativeai to dependencies**

In `pyproject.toml`, add to the `dependencies` list:
```
"chromadb>=0.5",
"google-generativeai>=0.8",
```

- [ ] **Step 2: Install**

Run: `cd /Users/sayan/Projects/aadi-labs/memory && uv sync`

---

### Task 2: Create ChromaIndex

Replace `TurbopufferIndex` with `ChromaIndex` that exposes the same interface used by `VectorStore`.

**Files:**
- Create: `/Users/sayan/Projects/aadi-labs/memory/memory_system/stores/chroma_index.py`
- Test: `/Users/sayan/Projects/aadi-labs/memory/memory_system/tests/test_chroma_index.py`

The `VectorStore` (vector_store.py) calls these methods on the index:
- `upsert_rows(rows)` — rows are dicts with id, scope, type, trust, doc_time, doc_text, vector, conversation_id
- `delete_ids(ids)` — list of UUIDs
- `delete_by_filter(filters)` — filter expression
- `query(rank_by, filters, top_k, include_attributes)` — low-level query
- `vector_search(query_vector, filters, top_k)` — ANN search
- `bm25_search(query_text, filters, top_k)` — full-text search
- `hybrid_multi_search(query_text, query_vector, filters, top_k_vector, top_k_text)` — combined
- `multi_query(queries)` — batch queries
- `hint_cache_warm()` — no-op for Chroma

- [ ] **Step 1: Write failing test for ChromaIndex**

```python
# memory_system/tests/test_chroma_index.py
import pytest
import uuid
from memory_system.stores.chroma_index import ChromaIndex, ChromaConfig


@pytest.fixture
def chroma_index(tmp_path):
    config = ChromaConfig(
        persist_directory=str(tmp_path / "chroma_data"),
        collection_name="test",
    )
    index = ChromaIndex(config)
    yield index


def test_upsert_and_vector_search(chroma_index):
    rows = [
        {
            "id": str(uuid.uuid4()),
            "scope": "user-1",
            "type": "observation",
            "trust": 0.9,
            "doc_time": "2026-01-01T00:00:00Z",
            "doc_text": "Alice loves hiking in the mountains",
            "vector": [0.1] * 768,  # Gemini Embedding 2 dimension
        },
        {
            "id": str(uuid.uuid4()),
            "scope": "user-1",
            "type": "observation",
            "trust": 0.8,
            "doc_time": "2026-01-02T00:00:00Z",
            "doc_text": "Bob prefers reading books",
            "vector": [0.9] * 768,
        },
    ]
    chroma_index.upsert_rows(rows)
    results = chroma_index.vector_search(
        query_vector=[0.1] * 768, top_k=1
    )
    assert len(results) == 1
    assert "hiking" in results[0]["doc_text"]


def test_delete_ids(chroma_index):
    row_id = str(uuid.uuid4())
    chroma_index.upsert_rows([{
        "id": row_id, "scope": "s", "type": "t",
        "trust": 1.0, "doc_time": "2026-01-01T00:00:00Z",
        "doc_text": "test", "vector": [0.5] * 768,
    }])
    chroma_index.delete_ids([row_id])
    results = chroma_index.vector_search(query_vector=[0.5] * 768, top_k=10)
    assert len(results) == 0


def test_filter_by_scope(chroma_index):
    chroma_index.upsert_rows([
        {"id": str(uuid.uuid4()), "scope": "user-1", "type": "t",
         "trust": 1.0, "doc_time": "2026-01-01T00:00:00Z",
         "doc_text": "a", "vector": [0.1] * 768},
        {"id": str(uuid.uuid4()), "scope": "user-2", "type": "t",
         "trust": 1.0, "doc_time": "2026-01-01T00:00:00Z",
         "doc_text": "b", "vector": [0.1] * 768},
    ])
    results = chroma_index.vector_search(
        query_vector=[0.1] * 768, filters={"scope": "user-1"}, top_k=10
    )
    assert len(results) == 1
    assert results[0]["scope"] == "user-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/sayan/Projects/aadi-labs/memory && uv run pytest memory_system/tests/test_chroma_index.py -v`

- [ ] **Step 3: Implement ChromaIndex**

```python
# memory_system/stores/chroma_index.py
"""Chroma-based local vector index, replacing turbopuffer."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import chromadb

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChromaConfig:
    persist_directory: str = "./chroma_data"
    collection_name: str = "lattice"
    distance_metric: str = "cosine"


class ChromaIndex:
    """Local Chroma vector index with the same interface VectorStore expects."""

    def __init__(self, config: ChromaConfig) -> None:
        self.config = config
        self._client = chromadb.PersistentClient(path=config.persist_directory)
        self._collection = self._client.get_or_create_collection(
            name=config.collection_name,
            metadata={"hnsw:space": config.distance_metric},
        )

    async def hint_cache_warm(self) -> None:
        """No-op for local Chroma."""
        pass

    def upsert_rows(self, rows: list[dict]) -> None:
        """Upsert documents into Chroma."""
        if not rows:
            return
        ids = [r["id"] for r in rows]
        embeddings = [r["vector"] for r in rows]
        documents = [r.get("doc_text", "") for r in rows]
        metadatas = [
            {
                "scope": r.get("scope", ""),
                "type": r.get("type", ""),
                "trust": float(r.get("trust", 1.0)),
                "doc_time": r.get("doc_time", ""),
                "conversation_id": r.get("conversation_id", ""),
            }
            for r in rows
        ]
        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    async def upsert_rows_async(self, rows: list[dict], **kwargs) -> None:
        """Async wrapper — Chroma is sync but VectorStore calls with await."""
        self.upsert_rows(rows)

    def delete_ids(self, ids: list[str]) -> None:
        if ids:
            self._collection.delete(ids=ids)

    async def delete_ids_async(self, ids: list[str]) -> None:
        self.delete_ids(ids)

    def delete_by_filter(self, filters: dict, **kwargs) -> None:
        where = self._build_where(filters)
        if where:
            self._collection.delete(where=where)

    def vector_search(
        self,
        query_vector: list[float],
        filters: dict | None = None,
        top_k: int = 50,
    ) -> list[dict]:
        """ANN search returning dicts with id, doc_text, scope, etc."""
        kwargs = {
            "query_embeddings": [query_vector],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if filters:
            kwargs["where"] = self._build_where(filters)
        results = self._collection.query(**kwargs)
        return self._unpack_results(results)

    async def vector_search_async(self, query_vector, filters=None, top_k=50):
        return self.vector_search(query_vector, filters, top_k)

    def bm25_search(
        self,
        query_text: str,
        filters: dict | None = None,
        top_k: int = 50,
    ) -> list[dict]:
        """Full-text search via Chroma's document search."""
        kwargs = {
            "query_texts": [query_text],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if filters:
            kwargs["where"] = self._build_where(filters)
        results = self._collection.query(**kwargs)
        return self._unpack_results(results)

    def hybrid_multi_search(
        self,
        query_text: str,
        query_vector: list[float],
        filters: dict | None = None,
        top_k_vector: int = 50,
        top_k_text: int = 50,
    ) -> tuple[list[dict], list[dict]]:
        """Run vector and text search, return both result sets."""
        vector_results = self.vector_search(query_vector, filters, top_k_vector)
        text_results = self.bm25_search(query_text, filters, top_k_text)
        return vector_results, text_results

    def multi_query(self, queries: list[dict], **kwargs) -> list[list[dict]]:
        """Batch multiple queries."""
        results = []
        for q in queries:
            if "query_vector" in q:
                r = self.vector_search(
                    q["query_vector"],
                    q.get("filters"),
                    q.get("top_k", 50),
                )
            else:
                r = self.bm25_search(
                    q.get("query_text", ""),
                    q.get("filters"),
                    q.get("top_k", 50),
                )
            results.append(r)
        return results

    def _build_where(self, filters: dict) -> dict | None:
        """Convert simple key=value filters to Chroma where clause."""
        if not filters:
            return None
        # Single filter: {"scope": "user-1"} → {"scope": {"$eq": "user-1"}}
        if len(filters) == 1:
            key, value = next(iter(filters.items()))
            return {key: {"$eq": value}}
        # Multiple: AND them
        conditions = [{k: {"$eq": v}} for k, v in filters.items()]
        return {"$and": conditions}

    def _unpack_results(self, raw: dict) -> list[dict]:
        """Convert Chroma query results to list of dicts."""
        if not raw or not raw.get("ids") or not raw["ids"][0]:
            return []
        results = []
        ids = raw["ids"][0]
        docs = raw.get("documents", [[]])[0]
        metas = raw.get("metadatas", [[]])[0]
        dists = raw.get("distances", [[]])[0]
        for i, doc_id in enumerate(ids):
            entry = {
                "id": doc_id,
                "doc_text": docs[i] if i < len(docs) else "",
                "dist": dists[i] if i < len(dists) else 0.0,
            }
            if i < len(metas) and metas[i]:
                entry.update(metas[i])
            results.append(entry)
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/memory && uv run pytest memory_system/tests/test_chroma_index.py -v`

---

### Task 3: Create Gemini Embedding 2 Provider

**Files:**
- Create: `/Users/sayan/Projects/aadi-labs/memory/memory_system/models/gemini_embeddings.py`
- Test: `/Users/sayan/Projects/aadi-labs/memory/memory_system/tests/test_gemini_embeddings.py`

The existing `OpenRouterProvider.encode()` takes a string or list of strings and returns embeddings. The new provider must match this interface but use Gemini's batch API.

- [ ] **Step 1: Write failing test**

```python
# memory_system/tests/test_gemini_embeddings.py
import pytest
from unittest.mock import patch, MagicMock
from memory_system.models.gemini_embeddings import GeminiEmbeddingProvider


def test_encode_single_string():
    with patch("memory_system.models.gemini_embeddings.genai") as mock_genai:
        mock_result = MagicMock()
        mock_result.embeddings = [MagicMock(values=[0.1] * 768)]
        mock_genai.embed_content.return_value = mock_result

        provider = GeminiEmbeddingProvider(
            model="gemini-embedding-2-preview",
            dimensions=768,
        )
        result = provider.encode("hello world")
        assert len(result) == 768


def test_encode_batch():
    with patch("memory_system.models.gemini_embeddings.genai") as mock_genai:
        mock_result = MagicMock()
        mock_result.embeddings = [
            MagicMock(values=[0.1] * 768),
            MagicMock(values=[0.2] * 768),
        ]
        mock_genai.embed_content.return_value = mock_result

        provider = GeminiEmbeddingProvider(
            model="gemini-embedding-2-preview",
            dimensions=768,
        )
        result = provider.encode_batch(["hello", "world"])
        assert len(result) == 2
        assert len(result[0]) == 768


def test_default_dimensions():
    provider = GeminiEmbeddingProvider()
    assert provider.dimensions == 768
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/sayan/Projects/aadi-labs/memory && uv run pytest memory_system/tests/test_gemini_embeddings.py -v`

- [ ] **Step 3: Implement GeminiEmbeddingProvider**

```python
# memory_system/models/gemini_embeddings.py
"""Gemini Embedding 2 provider using the Google AI batch embedding API."""

from __future__ import annotations

import logging
import os

import google.generativeai as genai

logger = logging.getLogger(__name__)

# Configure API key
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY", ""))


class GeminiEmbeddingProvider:
    """Generates embeddings via Gemini Embedding 2 batch API.

    Uses MRL (Matryoshka Representation Learning) to truncate
    from 3072 to 768 dimensions for production efficiency.
    """

    def __init__(
        self,
        model: str = "gemini-embedding-2-preview",
        dimensions: int = 768,
        batch_size: int = 100,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size

    def encode(self, text: str | list[str]) -> list[float] | list[list[float]]:
        """Encode text(s) into embedding(s). Matches OpenRouterProvider.encode() interface."""
        if isinstance(text, str):
            result = genai.embed_content(
                model=self.model,
                content=text,
                output_dimensionality=self.dimensions,
            )
            return result.embeddings[0].values
        return self.encode_batch(text)

    async def encode_async(self, text: str | list[str]) -> list[float] | list[list[float]]:
        """Async wrapper for encode."""
        return self.encode(text)

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch encode using Gemini's batch API."""
        all_embeddings = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            result = genai.embed_content(
                model=self.model,
                content=batch,
                output_dimensionality=self.dimensions,
            )
            for emb in result.embeddings:
                all_embeddings.append(emb.values)
        return all_embeddings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/memory && uv run pytest memory_system/tests/test_gemini_embeddings.py -v`

---

### Task 4: Wire Chroma + Gemini into VectorStore and Config

**Files:**
- Modify: `/Users/sayan/Projects/aadi-labs/memory/memory_system/config.py` — add Chroma config fields, update embedding model default
- Modify: `/Users/sayan/Projects/aadi-labs/memory/memory_system/stores/vector_store.py` — swap TurbopufferIndex → ChromaIndex
- Modify: `/Users/sayan/Projects/aadi-labs/memory/memory_system/factory.py` — instantiate GeminiEmbeddingProvider

This is the integration task — changes touch multiple files. Read each file fully before modifying.

- [ ] **Step 1: Read current config.py, vector_store.py, factory.py**

Read all three files to understand current structure before making changes.

- [ ] **Step 2: Update config.py**

Add Chroma config fields alongside existing turbopuffer ones (don't remove turbopuffer yet — keep as fallback):
```python
# Add these fields to LatticeConfig
chroma_persist_directory: str = "./chroma_data"
chroma_collection_name: str = "lattice"
vector_backend: str = "chroma"  # "chroma" or "turbopuffer"
embedding_provider: str = "gemini"  # "gemini" or "openrouter"
gemini_embedding_model: str = "gemini-embedding-2-preview"
gemini_embedding_dimensions: int = 768
```

Update `embedding_model` default from `"google/gemini-embedding-001"` to `"gemini-embedding-2-preview"`.

- [ ] **Step 3: Update vector_store.py**

Replace the turbopuffer import with a conditional import based on config:
```python
# At the top of VectorStore.__init__
if config.vector_backend == "chroma":
    from memory_system.stores.chroma_index import ChromaIndex, ChromaConfig
    chroma_cfg = ChromaConfig(
        persist_directory=config.chroma_persist_directory,
        collection_name=config.chroma_collection_name,
    )
    self.index = ChromaIndex(chroma_cfg)
else:
    from memory_system.stores.turbopuffer_index import TurbopufferIndex, TurbopufferConfig
    # ... existing turbopuffer setup
```

Update all `await self.index.upsert_rows(...)` calls — ChromaIndex is sync, so the VectorStore needs to call the sync methods or use the async wrappers.

- [ ] **Step 4: Update factory.py**

Conditionally create GeminiEmbeddingProvider or OpenRouterProvider:
```python
if config.embedding_provider == "gemini":
    from memory_system.models.gemini_embeddings import GeminiEmbeddingProvider
    embedding_provider = GeminiEmbeddingProvider(
        model=config.gemini_embedding_model,
        dimensions=config.gemini_embedding_dimensions,
    )
else:
    # existing OpenRouterProvider setup
```

The `LatticeMemory` and downstream components need the provider to have an `encode()` method — both providers expose this.

- [ ] **Step 5: Verify existing tests still pass**

Run: `cd /Users/sayan/Projects/aadi-labs/memory && uv run pytest memory_system/tests/ -v`

---

### Task 5: Implement LongMemEval-S Eval

**Files:**
- Create: `/Users/sayan/Projects/aadi-labs/memory/evaluations/longmemeval/` (directory)
- Create: `/Users/sayan/Projects/aadi-labs/memory/evaluations/longmemeval/run_eval.py`
- Create: `/Users/sayan/Projects/aadi-labs/memory/evaluations/longmemeval/dataset/` (download dataset)
- Create: `/Users/sayan/Projects/aadi-labs/memory/evaluations/longmemeval/Makefile`

Follow the LoCoMo eval pattern exactly: ingest → search → judge → aggregate.

- [ ] **Step 1: Research LongMemEval-S dataset format**

Search for the LongMemEval-S dataset:
- Check HuggingFace datasets for "longmemeval"
- Check the original paper's GitHub repo
- Understand the 6 categories: SSU, SSA, SSP, KU, TR, MS
- Understand the conversation format and question format

- [ ] **Step 2: Create directory structure**

```bash
mkdir -p /Users/sayan/Projects/aadi-labs/memory/evaluations/longmemeval/dataset
mkdir -p /Users/sayan/Projects/aadi-labs/memory/evaluations/longmemeval/results
```

- [ ] **Step 3: Write dataset download/preparation script**

```python
# evaluations/longmemeval/prepare_dataset.py
"""Download and prepare LongMemEval-S dataset."""
# Fetch from HuggingFace or original source
# Convert to format compatible with LATTICE++ eval pipeline
# Save to dataset/ directory
```

- [ ] **Step 4: Implement run_eval.py**

Follow the LoCoMo pattern:
```python
# evaluations/longmemeval/run_eval.py
"""LongMemEval-S evaluation pipeline for LATTICE++.

Usage:
    python run_eval.py --method add      # Ingest conversations
    python run_eval.py --method search   # Answer questions
    python run_eval.py --method eval     # Score answers
    python run_eval.py --method score    # Aggregate scores
    python run_eval.py --method all      # Run full pipeline
    python run_eval.py --subset SSU,KU,TR  # Run subset only (for fast eval)
"""
```

Key components:
- Ingest: Parse conversations, write to LATTICE++ via `lattice.write()`
- Search: For each question, query LATTICE++ via `lattice.query()`, generate answer via LLM
- Eval: LLM judge (GPT-4o-mini) scores each answer as correct/wrong
- Score: Aggregate by category, compute overall accuracy
- Subset mode: Only run specified categories (for fast eval)

- [ ] **Step 5: Create Makefile with Lattice env vars**

Copy the env var pattern from `evaluations/locomo/Makefile` but adapted for LongMemEval-S.

- [ ] **Step 6: Run eval to verify pipeline works**

Run: `cd /Users/sayan/Projects/aadi-labs/memory/evaluations/longmemeval && make run-lattice-add && make run-lattice-search`

---

### Task 6: Implement BEAM Eval

**Files:**
- Create: `/Users/sayan/Projects/aadi-labs/memory/evaluations/beam/` (directory)
- Create: `/Users/sayan/Projects/aadi-labs/memory/evaluations/beam/run_eval.py`
- Create: `/Users/sayan/Projects/aadi-labs/memory/evaluations/beam/dataset/`
- Create: `/Users/sayan/Projects/aadi-labs/memory/evaluations/beam/Makefile`

- [ ] **Step 1: Research BEAM dataset and format**

Search for the BEAM benchmark:
- Find the dataset source (likely HuggingFace or paper repo)
- Understand the scale tiers (100K, 500K, 1M tokens)
- Understand the scoring metric

- [ ] **Step 2: Create directory structure and download dataset**

- [ ] **Step 3: Implement run_eval.py**

Same pattern as LongMemEval-S but adapted for BEAM's format. Start with 100K scale only.

```python
# evaluations/beam/run_eval.py
"""BEAM evaluation pipeline for LATTICE++.

Usage:
    python run_eval.py --scale 100k --method all
"""
```

- [ ] **Step 4: Verify pipeline runs**

Run: `cd /Users/sayan/Projects/aadi-labs/memory/evaluations/beam && python run_eval.py --scale 100k --method all`

---

### Task 7: Build Smart Grader Script

**Files:**
- Create: `/Users/sayan/Projects/aadi-labs/memory/evolution_graders/grader.py`
- Test: `/Users/sayan/Projects/aadi-labs/memory/evolution_graders/test_grader.py`

- [ ] **Step 1: Write the grader script**

```python
#!/usr/bin/env python3
"""Evolution grader for LATTICE++ — tiered evaluation.

Every attempt: fast eval (LongMemEval-S subset: SSU + KU + TR, ~90 questions)
Every 5th attempt: full eval (all 3 benchmarks in parallel)

Outputs a single float to stdout (Evolution ScriptGrader protocol).
Writes detailed metrics to .evolution/shared/latest_full_eval.json.
"""

import json
import os
import sys
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

STATE_FILE = ".evolution/grader_state.json"
SIDECAR_FILE = ".evolution/shared/latest_full_eval.json"
FULL_EVAL_INTERVAL = 5
MAX_FULL_EVALS = 50

# Weights for composite score
WEIGHTS = {
    "longmemeval_overall": 0.40,
    "locomo_llm_judge": 0.35,
    "beam_100k": 0.25,
}


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        return json.loads(Path(STATE_FILE).read_text())
    return {"attempt_count": 0, "full_eval_count": 0}


def save_state(state: dict) -> None:
    Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(STATE_FILE).write_text(json.dumps(state, indent=2))


def run_fast_eval() -> float:
    """Run LongMemEval-S subset (SSU + KU + TR)."""
    result = subprocess.run(
        ["python3", "evaluations/longmemeval/run_eval.py",
         "--method", "all", "--subset", "SSU,KU,TR"],
        capture_output=True, text=True, timeout=600,
    )
    # Parse accuracy from output
    for line in result.stdout.strip().split("\n"):
        if "overall" in line.lower() or "accuracy" in line.lower():
            parts = line.split()
            for part in parts:
                try:
                    return float(part.strip("%,")) / 100 if "%" in part else float(part)
                except ValueError:
                    continue
    return 0.0


def run_longmemeval_full() -> dict:
    """Run full LongMemEval-S (500 questions)."""
    result = subprocess.run(
        ["python3", "evaluations/longmemeval/run_eval.py", "--method", "all"],
        capture_output=True, text=True, timeout=3600,
    )
    # Parse JSON results
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"overall": 0.0}


def run_locomo() -> dict:
    """Run full LoCoMo eval."""
    result = subprocess.run(
        ["python3", "evaluations/locomo/run_eval_pipeline.py"],
        capture_output=True, text=True, timeout=3600,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"overall": 0.0}


def run_beam() -> dict:
    """Run BEAM 100K eval."""
    result = subprocess.run(
        ["python3", "evaluations/beam/run_eval.py", "--scale", "100k", "--method", "all"],
        capture_output=True, text=True, timeout=3600,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"overall": 0.0}


def run_full_eval() -> float:
    """Run all 3 benchmarks in parallel, return composite score."""
    with ProcessPoolExecutor(max_workers=3) as pool:
        longmemeval_future = pool.submit(run_longmemeval_full)
        locomo_future = pool.submit(run_locomo)
        beam_future = pool.submit(run_beam)

        longmemeval = longmemeval_future.result()
        locomo = locomo_future.result()
        beam = beam_future.result()

    lm_score = longmemeval.get("overall", 0.0)
    lc_score = locomo.get("overall", 0.0)
    bm_score = beam.get("overall", 0.0)

    composite = (
        WEIGHTS["longmemeval_overall"] * lm_score
        + WEIGHTS["locomo_llm_judge"] * lc_score
        + WEIGHTS["beam_100k"] * bm_score
    )

    # Write sidecar
    sidecar = {
        "mode": "full",
        "longmemeval_overall": lm_score,
        "longmemeval_by_category": longmemeval.get("by_category", {}),
        "locomo_llm_judge": lc_score,
        "locomo_by_category": locomo.get("by_category", {}),
        "beam_100k": bm_score,
        "composite": composite,
    }
    Path(SIDECAR_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(SIDECAR_FILE).write_text(json.dumps(sidecar, indent=2))

    return composite


def main():
    state = load_state()
    state["attempt_count"] += 1

    is_full = (
        state["attempt_count"] % FULL_EVAL_INTERVAL == 0
        and state["full_eval_count"] < MAX_FULL_EVALS
    )

    if is_full:
        state["full_eval_count"] += 1
        score = run_full_eval()
        print(f"{score:.4f}", file=sys.stderr)
        print(f"Full eval #{state['full_eval_count']}/{MAX_FULL_EVALS}")
    else:
        score = run_fast_eval()
        print(f"Fast eval (LongMemEval-S subset)", file=sys.stderr)

    save_state(state)

    # ScriptGrader protocol: first line of stdout = float score
    print(f"{score:.4f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make grader executable**

Run: `chmod +x /Users/sayan/Projects/aadi-labs/memory/evolution_graders/grader.py`

- [ ] **Step 3: Write basic test**

```python
# evolution_graders/test_grader.py
"""Test the grader state management."""
import json
import pytest
from pathlib import Path


def test_state_file_created(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".evolution").mkdir()
    (tmp_path / ".evolution" / "shared").mkdir()

    from evolution_graders.grader import load_state, save_state
    state = load_state()
    assert state["attempt_count"] == 0
    state["attempt_count"] = 5
    save_state(state)
    reloaded = load_state()
    assert reloaded["attempt_count"] == 5


def test_full_eval_triggers_every_5th():
    from evolution_graders.grader import FULL_EVAL_INTERVAL
    assert FULL_EVAL_INTERVAL == 5
```

- [ ] **Step 4: Run test**

Run: `cd /Users/sayan/Projects/aadi-labs/memory && uv run pytest evolution_graders/test_grader.py -v`

---

### Task 8: Write evolution.yaml

**Files:**
- Create: `/Users/sayan/Projects/aadi-labs/memory/evolution.yaml`

- [ ] **Step 1: Write the config file**

Use the exact YAML from the approved spec (`docs/superpowers/specs/2026-03-19-memory-evolution-design.md`), with the user's modifications to the optimizer role prompt (config tuning, retrieval pipeline optimization, latency optimization).

- [ ] **Step 2: Validate config loads**

Run: `cd /Users/sayan/Projects/aadi-labs/memory && python3 -c "import yaml; c = yaml.safe_load(open('evolution.yaml')); print(f'Session: {c[\"session\"][\"name\"]}, Agents: {list(c[\"agents\"].keys())}')"``

---

### Task 9: Run Baseline (STOP AFTER THIS)

Run each benchmark once to establish baseline scores with the new Chroma + Gemini Embedding 2 stack.

- [ ] **Step 1: Run LongMemEval-S baseline**

```bash
cd /Users/sayan/Projects/aadi-labs/memory/evaluations/longmemeval
make run-lattice-add
make run-lattice-search
python run_eval.py --method eval
python run_eval.py --method score
```

Record scores per category and overall.

- [ ] **Step 2: Run LoCoMo baseline**

```bash
cd /Users/sayan/Projects/aadi-labs/memory/evaluations/locomo
make run-lattice-add
make run-lattice-search
python evals.py --input_file results/lattice_search_results.json --output_file results/evals.json
python generate_scores.py --input_path="results/evals.json"
```

Record scores per category and overall.

- [ ] **Step 3: Run BEAM 100K baseline**

```bash
cd /Users/sayan/Projects/aadi-labs/memory/evaluations/beam
python run_eval.py --scale 100k --method all
```

Record score.

- [ ] **Step 4: Update evolution.yaml milestones with actual baselines**

Replace the estimated baseline values in `evolution.yaml` with the actual scores from steps 1-3.

- [ ] **Step 5: Report baseline scores**

Print summary table:
```
LATTICE++ Baseline (Chroma + Gemini Embedding 2)
├── LongMemEval-S: XX.X% (target: 85%, stretch: 92.6%)
│   ├── SSU: XX.X%
│   ├── SSA: XX.X%
│   ├── SSP: XX.X%
│   ├── KU:  XX.X%
│   ├── TR:  XX.X%
│   └── MS:  XX.X%
├── LoCoMo: XX.X% (target: 76%, stretch: 89.9%)
│   ├── Single-Hop: XX.X%
│   ├── Multi-Hop:  XX.X%
│   ├── Open Domain: XX.X%
│   └── Temporal:   XX.X%
└── BEAM 100K: X.XXX (target: 0.63, stretch: 0.70)
```

**STOP HERE. Do not start `evolution run`. Wait for explicit user instruction.**
