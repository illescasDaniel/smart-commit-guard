"""The deterministic half of the eval, without a model: every labelled case must be decided at the stage it records.

A rule or name change that moves a case between `no-hit`, `model`, `rule-block` and `name-block` shows up here, and a real
secret that no stage surfaces (it could never be caught, whatever the model says) fails the run."""
import json
from pathlib import Path

import pytest

from smart_commit_guard.policy import stage

EVALS = Path(__file__).resolve().parents[2] / "evals"
CASES = [(f.name, c) for f in sorted(EVALS.glob("cases_*.json")) for c in json.loads(f.read_text(encoding="utf-8"))]


def test_given_the_eval_files_when_loading_then_there_are_cases_with_a_recorded_stage():
	assert len(CASES) >= 100 and all("stage" in c for _, c in CASES)


@pytest.mark.parametrize("name, case", CASES, ids=[f"{n}:{c['path']}:{c['text'][:40]}" for n, c in CASES])
def test_given_a_labelled_case_when_staging_then_it_lands_where_the_case_says(name, case):
	assert stage(case["path"], case["text"]) == case["stage"]


@pytest.mark.parametrize("name, case", [(n, c) for n, c in CASES if c["label"] == "real"],
						 ids=lambda v: v if isinstance(v, str) else v["text"][:40])
def test_given_a_real_secret_when_staging_then_some_stage_surfaces_it(name, case):
	assert case["stage"] != "no-hit"
