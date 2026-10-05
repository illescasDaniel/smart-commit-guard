"""Scan policy: thresholds, batching and fail-open/closed rules live here, not in the model."""
from __future__ import annotations

import fnmatch
import re
import time
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from typing import Literal

from .decider import MAX_BATCH, Decider, DeciderUnavailable
from .redact import fingerprints, mask_line
from .rules import scan_line
from .skip import (
	is_env_file,
	is_example_path,
	is_rules_only,
	is_skipped,
	sensitive_file_reason,
)
from .types import AddedLine, Finding, LineHit, ScanResult

MAX_CALLS = 30   # one candidate per request (see decider.MAX_BATCH), so this is also the candidates judged per scan
WINDOW_CHARS = 300   # what the model sees of a long line: about this many characters centred on the candidate

FILE_PREVIEW = "<contents hidden>"
# Honoured only when the repo file sets `allow_inline = true`. The other tools' spellings are accepted too, so adopting this
# tool does not mean rewriting every existing marker.
PRAGMAS = ("smart-commit-guard: allow", "gitleaks:allow", "pragma: allowlist secret")
_KEY_BEFORE = re.compile(r"[A-Za-z0-9_.-]{1,80}[\"']?\s*[:=]\s*[\"']?$")


def _allowed(path: str, masked: str, allowlist: AbstractSet[str], allow_paths: Mapping[str, str]) -> bool:
	"""An entry in either fingerprint form; an `[[allow]]` entry with a `path` glob only counts for matching paths."""
	for fp in fingerprints(path, masked):
		if fp in allowlist and (fp not in allow_paths or fnmatch.fnmatchcase(path, allow_paths[fp])):
			return True
	return False


def _label(hit: LineHit) -> str:
	return f"{hit.rule} pattern" if hit.kind == "rule" else "secret-looking value"


def window(text: str, start: int, end: int, size: int = WINDOW_CHARS) -> str:
	"""`text` if it is short, else about `size` characters centred on the candidate span, with `…` at the cut edges.
	The key in front of the value (`password: `) is kept when it is just outside the window."""
	if len(text) <= size:
		return text
	if end - start >= size:   # a value longer than the window: its beginning is what identifies it
		lo, hi = start, start + size
	else:
		lo = max(0, start - (size - (end - start)) // 2)
		hi = min(len(text), lo + size)
		lo = max(0, hi - size)   # near the end of the line the window slides left instead of shrinking
	if lo > 0 and (m := _KEY_BEFORE.search(text[:start])) and m.start() < lo:
		lo = m.start()
	return ("…" if lo > 0 else "") + text[lo:hi] + ("…" if hi < len(text) else "")


def line_hits(path: str, text: str) -> list[LineHit]:
	"""What the deterministic layer finds on one line of `path`: nothing for skipped files, rules only for lockfiles and
	generated files."""
	if is_skipped(path) or sensitive_file_reason(path):
		return []
	return scan_line(text, rules_only=is_rules_only(path))


def stage(path: str, text: str) -> Literal["no-hit", "name-block", "rule-block", "model"]:
	"""Where a line is decided: `name-block` (a sensitive file name, no model), `rule-block` (a known secret shape, no
	model), `model` (some candidate needs it) or `no-hit`. Deterministic: this is what the eval's rules-only gate checks."""
	if sensitive_file_reason(path) and not (is_env_file(path) and (not text.strip() or text.lstrip().startswith("#"))):
		return "name-block"
	hits = line_hits(path, text)
	if not hits:
		return "no-hit"
	return "rule-block" if any(h.high_confidence for h in hits) and not is_example_path(path) else "model"


def scan(lines: Sequence[AddedLine], decider: Decider | None, *, block_at: float = 0.5, warn_at: float = 0.4,
		 allowlist: AbstractSet[str] = frozenset(), allow_paths: Mapping[str, str] = {},
		 inline_allow: bool = False, paths: Sequence[str] = (), budget: float | None = None, clock: Callable[[], float] = time.monotonic) -> ScanResult:
	"""decider=None means rules only. The decider receives the candidate line as written (a window around the candidate
	when the line is long), never other lines or whole files; lines that rules already block are never sent.
	`budget` is the total seconds of model time for the scan: candidates left over are reported as not judged.

	`paths` are changed files that have no text lines (binaries such as `.p12`); they are only checked by file name."""
	result = ScanResult()
	pending: list[tuple[AddedLine, list[LineHit], str]] = []   # (line, hits the model decides, masked line)
	by_name: dict[str, tuple[int, str]] = {}   # path -> (first line, why): a sensitive file is itself the finding
	for line in lines:
		why = sensitive_file_reason(line.path)
		if why and not (is_env_file(line.path) and (not line.text.strip() or line.text.lstrip().startswith("#"))):
			by_name.setdefault(line.path, (line.number, why))
	for path in paths:
		why = sensitive_file_reason(path)
		if why and not is_env_file(path):
			by_name.setdefault(path, (1, why))
	for path, (number, why) in by_name.items():   # one block per file, no model, contents never printed
		if not _allowed(path, FILE_PREVIEW, allowlist, allow_paths):
			result.findings.append(Finding(path, number, "block", why, FILE_PREVIEW))
	for line in lines:
		if inline_allow and any(p in line.text for p in PRAGMAS):   # a visible, reviewable opt-out for this one line
			continue
		hits = line_hits(line.path, line.text)
		if not hits:
			continue
		masked = mask_line(line.text, hits)
		if _allowed(line.path, masked, allowlist, allow_paths):
			continue
		if not is_example_path(line.path) and any(h.high_confidence for h in hits):
			labels = ", ".join(dict.fromkeys(_label(h) for h in hits if h.high_confidence))
			result.findings.append(Finding(line.path, line.number, "block", f"{labels} (rule, no model needed)", masked))
		else:
			pending.append((line, hits, masked))

	judged = _judge(pending, decider, result, budget, clock) if decider is not None else {}
	for line, hits, masked in pending:
		if finding := _line_finding(line, hits, masked, judged, result.model_unavailable, block_at, warn_at):
			result.findings.append(finding)
	result.findings.sort(key=lambda f: (f.path, f.number))
	return result


def _line_finding(line: AddedLine, hits: list[LineHit], masked: str, judged: dict[tuple[str, str], float],
				  model_unavailable: bool, block_at: float, warn_at: float) -> Finding | None:
	"""One finding per line: the most severe of its hits, naming every hit of that severity."""
	outcomes: list[tuple[LineHit, Literal["block", "warn"], str, float | None]] = []
	for hit in hits:
		p = judged.get((line.path, window(line.text, hit.start, hit.end)))
		if p is None:   # not judged: a known secret shape is never waved through
			why = "model unavailable" if model_unavailable else "not judged by the model"
			outcomes.append((hit, "block" if hit.high_confidence else "warn", why, None))
		elif p >= block_at:
			outcomes.append((hit, "block", "model says likely real", p))
		elif p >= warn_at:
			outcomes.append((hit, "warn", "model is unsure", p))
	if not outcomes:
		return None
	level = "block" if any(o[1] == "block" for o in outcomes) else "warn"
	top = [o for o in outcomes if o[1] == level]
	best = max(top, key=lambda o: -1.0 if o[3] is None else o[3])
	labels = ", ".join(dict.fromkeys(_label(o[0]) for o in top))
	return Finding(line.path, line.number, level, f"{labels}: {best[2]}", masked, best[3])


def _judge(pending: list[tuple[AddedLine, list[LineHit], str]], decider: Decider, result: ScanResult, budget: float | None,
		   clock: Callable[[], float]) -> dict[tuple[str, str], float]:
	"""(path, text sent) -> P(real). Identical items are judged once. Stops at the first failure, after MAX_CALLS calls, or
	when the time budget is used up."""
	items: list[tuple[str, str]] = []
	for line, hits, _ in pending:
		for hit in hits:
			item = (line.path, window(line.text, hit.start, hit.end))
			if item not in items:
				items.append(item)
	deadline = None if budget is None else clock() + budget
	out: dict[tuple[str, str], float] = {}
	for start in range(0, min(len(items), MAX_CALLS * MAX_BATCH), MAX_BATCH):
		if deadline is not None and clock() >= deadline:
			result.budget_exhausted = True
			break
		batch = items[start:start + MAX_BATCH]
		try:
			ps = decider.judge(batch)
		except DeciderUnavailable:
			result.model_unavailable = True
			break
		out.update(zip(batch, ps))
	return out
