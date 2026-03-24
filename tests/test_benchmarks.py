"""Tests for the three CORAL benchmark task configurations.

Validates that:
- All three task.yaml files parse as valid YAML with expected fields.
- All three grader scripts execute and produce a numeric score.
- Seed code is importable and produces expected baseline values.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

TASKS_DIR = Path(__file__).resolve().parent.parent / "tasks"

TASK_CONFIGS = [
    "erdos_overlap",
    "kernel_engineering",
    "openvaccine",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_yaml(task_name: str) -> dict:
    path = TASKS_DIR / task_name / "task.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def _import_module_from_path(name: str, path: str):
    """Import a Python module from an absolute file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# YAML parsing tests
# ---------------------------------------------------------------------------

class TestTaskYamlParsing:
    """All three task.yaml files parse as valid YAML with expected structure."""

    @pytest.mark.parametrize("task_name", TASK_CONFIGS)
    def test_yaml_parses(self, task_name: str):
        cfg = _load_yaml(task_name)
        assert isinstance(cfg, dict), f"{task_name}/task.yaml did not parse as a dict"

    @pytest.mark.parametrize("task_name", TASK_CONFIGS)
    def test_yaml_has_required_fields(self, task_name: str):
        cfg = _load_yaml(task_name)
        for field in ("name", "description", "metric", "grader", "seed", "milestones", "stop"):
            assert field in cfg, f"{task_name}/task.yaml missing required field '{field}'"

    @pytest.mark.parametrize("task_name", TASK_CONFIGS)
    def test_metric_direction(self, task_name: str):
        cfg = _load_yaml(task_name)
        assert cfg["metric"]["direction"] == "lower_is_better"

    def test_erdos_milestones(self):
        cfg = _load_yaml("erdos_overlap")
        ms = cfg["milestones"]
        assert ms["baseline"] == pytest.approx(0.38111)
        assert ms["target"] == pytest.approx(0.38089)
        assert ms["stretch"] == pytest.approx(0.3808703)

    def test_kernel_milestones(self):
        cfg = _load_yaml("kernel_engineering")
        ms = cfg["milestones"]
        assert ms["baseline"] == 1363
        assert ms["target"] == 1103

    def test_openvaccine_milestones(self):
        cfg = _load_yaml("openvaccine")
        ms = cfg["milestones"]
        assert ms["baseline"] == pytest.approx(0.34198)


# ---------------------------------------------------------------------------
# Grader execution tests
# ---------------------------------------------------------------------------

class TestGraderExecution:
    """All three grader scripts execute and produce a numeric score."""

    @pytest.mark.parametrize(
        "task_name",
        TASK_CONFIGS,
    )
    def test_grader_produces_numeric_output(self, task_name: str):
        grader_path = TASKS_DIR / task_name / "grader.py"
        result = subprocess.run(
            [sys.executable, str(grader_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        stdout = result.stdout.strip()
        score = float(stdout)
        assert isinstance(score, float)
        # All benchmark scores should be positive
        assert score > 0


# ---------------------------------------------------------------------------
# Seed importability and baseline value tests
# ---------------------------------------------------------------------------

class TestSeedBaselines:
    """Seed code is importable and produces expected baseline values."""

    def test_erdos_solver_importable_and_baseline(self):
        solver = _import_module_from_path(
            "solver",
            str(TASKS_DIR / "erdos_overlap" / "seed" / "solver.py"),
        )
        score = solver.compute_c5()
        assert isinstance(score, float)
        # Naive baseline should be in a reasonable range (well above the optimum ~0.38)
        assert 0.2 < score < 0.8, f"Erdos baseline {score} outside expected range"

    def test_kernel_benchmark_importable_and_baseline(self):
        kernel = _import_module_from_path(
            "kernel",
            str(TASKS_DIR / "kernel_engineering" / "seed" / "kernel.py"),
        )
        score = kernel.benchmark()
        assert score == 1363

    def test_openvaccine_model_importable_and_baseline(self):
        model = _import_module_from_path(
            "model",
            str(TASKS_DIR / "openvaccine" / "seed" / "model.py"),
        )
        score = model.evaluate()
        assert score == pytest.approx(0.34198)
