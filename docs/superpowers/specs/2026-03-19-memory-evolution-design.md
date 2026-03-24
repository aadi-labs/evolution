# LATTICE++ Evolution: State-of-the-Art Memory System

**Date:** 2026-03-19
**Status:** Design approved, pending implementation plan

## Overview

Use the Evolution platform to optimize LATTICE++ into a state-of-the-art memory system that beats Honcho (92.6% LongMemEval-S), SuperMemory (85.2%), and all other competitors across three benchmarks: LongMemEval-S, LoCoMo, and BEAM.

**Target repo:** `/Users/sayan/Projects/aadi-labs/memory`
**Evolution repo:** `/Users/sayan/Projects/aadi-labs/evolution`

## Targets to Beat

### LongMemEval-S (primary — 500 questions, 6 categories)

| System | SSU | SSA | SSP | KU | TR | MS | Overall |
|---|---|---|---|---|---|---|---|
| Honcho + Gemini-3-Pro | — | — | — | — | — | — | **92.6%** |
| Honcho + Claude Haiku 4.5 | — | — | — | — | — | — | **90.4%** |
| SuperMemory + Gemini-3-Pro | — | — | — | — | — | — | **85.2%** |
| SuperMemory + GPT-5 | — | — | — | — | — | — | **84.6%** |
| SuperMemory + GPT-4o | 97.14 | 96.43 | 70.00 | 88.46 | 76.69 | 71.43 | **81.6%** |
| Zep | 92.9 | 80.4 | 56.7 | 83.3 | 62.4 | 57.9 | **71.2%** |
| Full Context | 81.4 | 94.6 | 20.0 | 78.2 | 45.1 | 44.3 | **60.2%** |

Categories: SSU (Single-Session User), SSA (Single-Session Assistant), SSP (Single-Session Preference), KU (Knowledge Update), TR (Temporal Reasoning), MS (Multi-Session)

### LoCoMo (1,540 questions, 4 scored categories)

| System | Single-Hop | Multi-Hop | Open Domain | Temporal | Overall |
|---|---|---|---|---|---|
| Honcho | — | — | — | — | **89.9%** |
| Memobase | 70.92 | 46.88 | 77.17 | 85.05 | **75.78%** |
| Zep (updated) | 74.11 | 66.04 | 67.71 | 79.79 | **75.14%** |
| LATTICE++ (reported) | 70.92 | 40.62 | 75.51 | 76.64 | **72.73%** |
| LATTICE++ (current) | 58.87 | 38.54 | 60.40 | 69.47 | **~61%** |

### BEAM (100K to 10M tokens)

| Scale | Honcho | Paper Baseline |
|---|---|---|
| 100K | **0.630** | 0.358 |
| 500K | **0.649** | 0.359 |
| 1M | **0.631** | 0.336 |
| 10M | **0.406** | 0.266 |

## Prerequisites (Build Before Evolution Runs)

### 1. Swap turbopuffer → Chroma + Gemini Embedding 2

Replace the cloud vector search with local Chroma and Google's #1 ranked embedding model.

| Component | Current | New |
|---|---|---|
| Vector DB | turbopuffer (cloud) | Chroma (local, free) |
| Embeddings | sentence-transformers / all-MiniLM-L6-v2 (~384d) | Gemini Embedding 2 (768d, MRL truncated from 3,072) |
| Model ID | `all-MiniLM-L6-v2` | `gemini-embedding-2-preview` |
| Embedding API | Local inference | Gemini batch embedding API |
| MTEB rank | ~50s | **#1 (68.32)** |

Use Gemini's batch embedding API for throughput during eval runs (1,540+ embeddings at a time).

Chroma config:
- Persistent storage at `./chroma_data/`
- Collection per user/session as needed
- Distance metric: cosine similarity
- Dimension: 768

### 2. Implement LongMemEval-S Eval

- Download/prepare LongMemEval-S dataset (500 questions, 6 categories)
- Implement eval pipeline matching LATTICE++'s existing LoCoMo pattern:
  - Ingest conversations into LATTICE++
  - Query for each question
  - LLM judge scoring (GPT-4o-mini, binary correct/wrong)
  - Aggregate by category and overall
- Place in `evaluations/longmemeval/`

### 3. Implement BEAM Eval

- Download/prepare BEAM dataset (100K, 500K, 1M scales — skip 10M for now)
- Implement eval pipeline
- Place in `evaluations/beam/`

### 4. Build Evolution Graders

Two grader scripts in the memory repo:

**`evolution_graders/grader.py`** — single smart grader script:

The grader tracks its own invocation count via a state file (`.evolution/grader_state.json`).

**Every attempt (fast mode):**
- Runs LongMemEval-S subset: SSU + KU + TR categories (~90 questions)
- Outputs the subset accuracy as a float to stdout (ScriptGrader protocol)
- Estimated time: 2-3 minutes

**Every 5th attempt (full mode):**
- Runs all three benchmarks in parallel via ProcessPoolExecutor:
  - LongMemEval-S (full 500 questions)
  - LoCoMo (full 1,540 questions)
  - BEAM 100K
- Computes weighted composite: 0.40 * longmemeval + 0.35 * locomo + 0.25 * beam
- Outputs composite score to stdout
- Writes detailed per-metric breakdown to `.evolution/shared/latest_full_eval.json` (agents can read this)
- Tracks full eval count; after 50 full runs, only fast mode runs
- Estimated time: 10-12 minutes (parallel)

**Output protocol:** First line of stdout is always a single float (0.0-1.0). This conforms to Evolution's ScriptGrader protocol. Agents see the score and feedback via `evolution eval` response.

**Sidecar file** (`.evolution/shared/latest_full_eval.json`):
```json
{
  "mode": "full",
  "run_number": 7,
  "longmemeval_overall": 0.72,
  "longmemeval_by_category": {"SSU": 0.85, "SSA": 0.80, "SSP": 0.55, "KU": 0.78, "TR": 0.65, "MS": 0.50},
  "locomo_llm_judge": 0.68,
  "locomo_by_category": {"single_hop": 0.70, "multi_hop": 0.42, "open_domain": 0.75, "temporal": 0.72},
  "beam_100k": 0.45,
  "composite": 0.636,
  "timestamp": "2026-03-20T14:30:00Z"
}
```
Agents can read this file to understand which categories need the most work.

**Python environment:** The grader uses a shebang pointing to the memory repo's venv: `#!/path/to/memory/.venv/bin/python`. All dependencies (chromadb, google-generativeai, LATTICE++ itself) must be installed in that venv.

### 5. Write evolution.yaml

Place in memory repo root.

## Evolution Session Config

```yaml
session:
  name: "lattice-evolution"

task:
  name: "lattice-memory-optimization"
  path: .
  description: |
    Optimize LATTICE++ memory system to beat Honcho (92.6%) and
    SuperMemory (85.2%) on LongMemEval-S, beat Honcho (89.9%)
    on LoCoMo, and match Honcho (0.63) on BEAM.

    You may modify anything: retrieval config, prompts, code in
    memory_system/, consolidation logic, graph expansion, eval
    infrastructure. Full codebase access.

  seed: "."
  grader:
    type: script
    script: ./evolution_graders/grader.py
  metric:
    name: composite
    direction: higher_is_better
  milestones:
    baseline: 0.40
    target: 0.70
    stretch: 0.85
  stop:
    max_time: 24h
    stagnation: 2h
    stagnation_action: shake_up
    shake_up_budget: 3

roles:
  researcher:
    prompt: |
      You are optimizing LATTICE++, an AI memory system.

      Targets to beat:
      - LongMemEval-S: 92.6% (Honcho) — currently ~60%
      - LoCoMo: 89.9% (Honcho) — currently ~61%
      - BEAM 100K: 0.63 (Honcho) — no baseline yet

      You have full codebase access. Key areas:
      - memory_system/ — core implementation
      - evaluations/ — eval infrastructure
      - Retrieval config (env vars in Makefile)
      - Prompts (prompts.py, query compiler)
      - Consolidation logic, graph expansion
      - Chroma vector store config
      - Gemini Embedding 2 batch API usage

      Strategy:
      1. First fix the LoCoMo regression (was 72%, now 61%)
      2. Read shared notes from other agents before each approach
      3. Test config changes with fast eval before full eval
      4. Share findings — especially dead ends — via evolution note add
      5. Focus on retrieval quality — embeddings and reranking are the foundation
    heartbeat:
      on_attempts: 3
      on_time: 15m
      strategy: first

  optimizer:
    prompt: |
      You are optimizing LATTICE++, an AI memory system.

      Targets to beat:
      - LongMemEval-S: 92.6% (Honcho) — currently ~60%
      - LoCoMo: 89.9% (Honcho) — currently ~61%
      - BEAM 100K: 0.63 (Honcho) — no baseline yet

      You have full codebase access. Focus on:
      - Config tuning
      - Retrieval pipeline optimization
      - latency optimization

      Strategy:
      1. Start with config-only changes — fastest iteration
      2. Use fast eval (LongMemEval-S subset) for quick signal
      3. Only trigger full eval when you have a promising improvement
      4. Share all findings via evolution note add
      5. Check other agents' notes before starting new approaches
    heartbeat:
      on_attempts: 5
      on_time: 15m
      strategy: first

agents:
  claude-researcher:
    role: researcher
    runtime: claude-code
    skills:
      - superpowers

  claude-optimizer:
    role: optimizer
    runtime: claude-code
    skills:
      - superpowers

  codex-researcher:
    role: researcher
    runtime: codex
    env:
      CODEX_MODEL: o3-pro

  codex-optimizer:
    role: optimizer
    runtime: codex
    env:
      CODEX_MODEL: o3-pro

superagent:
  enabled: true
  runtime: claude-code
  remote_control: true
  skills:
    - superpowers
  prompt: |
    You are the superagent for the LATTICE++ evolution session.
    Key metrics: LongMemEval-S (target 92.6%), LoCoMo (target 89.9%), BEAM (target 0.63).
    50 full eval cycles budget. Monitor progress and nudge agents when stagnating.
    Report category-level breakdowns when asked — the weakest categories are
    Temporal Reasoning and Multi-Session.
```

## Agent Strategy Expectations

All 4 agents share notes, insights, and skills. Same roles across runtimes — diversity comes from the models, not forced specialization.

**Expected collaboration pattern:**
1. Early phase: agents independently explore different areas (config, prompts, retrieval, code)
2. Mid phase: agents read each other's notes, build on successful approaches
3. Late phase: agents converge on best approaches, refine details

**Fast eval budget:** Unlimited. Agents should iterate freely on the LongMemEval-S subset (SSU + KU + TR, ~90 questions).

**Full eval budget:** 50 cycles total across all agents. ~12 full evals per agent. Agents should be strategic — use fast eval to validate before spending a full eval cycle.

## Implementation Order

This is prerequisite work in the **memory repo**, not the evolution repo:

1. **Swap to Chroma + Gemini Embedding 2** — modify memory_system/ vector store layer
2. **Implement LongMemEval-S eval** — dataset, pipeline, scoring in evaluations/longmemeval/
3. **Implement BEAM eval** — dataset, pipeline, scoring in evaluations/beam/
4. **Build evolution graders** — fast_longmemeval.py + full_benchmarks.py
5. **Write evolution.yaml** — session config in memory repo root
6. **Run baseline** — get current scores on all three benchmarks with new embedding stack
7. **Start evolution** — `cd /path/to/memory && evolution run`

## Success Criteria

| Benchmark | Current | Target | Stretch (beat Honcho) |
|---|---|---|---|
| LongMemEval-S | ~60% | 85% | 92.6% |
| LoCoMo | ~61% | 76% | 89.9% |
| BEAM 100K | no baseline | 0.63 | 0.70 |
