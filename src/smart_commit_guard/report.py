"""Output formats. Everything printed here is already masked: a finding's preview never holds a raw secret."""
from __future__ import annotations

import json
import sys

from . import __version__
from .redact import fingerprint_v2
from .types import Finding, ScanResult

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
FORMATS = ("text", "json", "sarif")


def clip(s: str, n: int = 160) -> str:
	return s if len(s) <= n else s[:n] + "..."


def _rows(result: ScanResult) -> list[dict]:
	return [{"path": f.path, "line": f.number, "level": f.level, "reason": f.reason, "preview": f.preview, "p": f.p,
			 "fingerprint": fingerprint_v2(f.path, f.preview)} for f in result.findings]


def as_json(result: ScanResult) -> str:
	return json.dumps({"exit_code": result.exit_code, "model_unavailable": result.model_unavailable,
					   "model_skipped": result.model_skipped, "budget_exhausted": result.budget_exhausted,
					   "findings": _rows(result)})


def error_json(message: str) -> str:
	return json.dumps({"exit_code": 2, "error": message})


def as_sarif(result: ScanResult) -> str:
	"""SARIF 2.1.0 for GitHub code scanning. Snippets are the masked previews."""
	results = [{
		"ruleId": "smart-commit-guard/secret", "level": "error" if f.level == "block" else "warning",
		"message": {"text": f.reason},
		"locations": [{"physicalLocation": {"artifactLocation": {"uri": f.path},
											"region": {"startLine": f.number, "snippet": {"text": f.preview}}}}],
		"partialFingerprints": {"smartCommitGuard/v2": row["fingerprint"]},
	} for f, row in zip(result.findings, _rows(result))]
	run = {"tool": {"driver": {"name": "smart-commit-guard", "version": __version__,
							   "informationUri": "https://github.com/illescasDaniel/smart-commit-guard",
							   "rules": [{"id": "smart-commit-guard/secret", "shortDescription": {"text": "Possible committed secret"}}]}},
		   "results": results}
	return json.dumps({"$schema": SARIF_SCHEMA, "version": "2.1.0", "runs": [run]})


def _annotation_escape(s: str, prop: bool = False) -> str:
	s = s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
	return s.replace(":", "%3A").replace(",", "%2C") if prop else s


def annotation(f: Finding) -> str:
	"""A GitHub Actions workflow command, shown inline on the pull request."""
	kind = "error" if f.level == "block" else "warning"
	return f"::{kind} file={_annotation_escape(f.path, True)},line={f.number}::{_annotation_escape(f.reason)}"


def print_text(result: ScanResult, github_actions: bool, hint: str) -> None:
	for f, row in zip(result.findings, _rows(result)):
		score = f" p={f.p:.2f}" if f.p is not None else ""
		print(f"{f.level.upper():5} {f.path}:{f.number}  {f.reason}{score}\n      {clip(f.preview)}\n      allowlist: {row['fingerprint']}")
		if github_actions:
			print(annotation(f))
	if result.model_skipped == "hosted_scope":
		print("note: hosted model not used for commits (SECRET_GUARD_HOSTED_SCOPE=ci); ambiguous candidates only warn, CI will judge them",
			  file=sys.stderr)
	if result.model_unavailable:
		print("note: the decision model was unavailable; only rule hits were enforced", file=sys.stderr)
	if result.budget_exhausted:
		print("note: the model time budget (SECRET_GUARD_BUDGET) ran out; the remaining candidates were not judged", file=sys.stderr)
	if result.exit_code:
		print(hint, file=sys.stderr)
