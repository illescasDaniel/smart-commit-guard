"""Shared value types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class AddedLine:
	path: str
	number: int
	text: str


@dataclass(frozen=True)
class LineHit:
	"""What the deterministic layer found on one added line."""
	kind: Literal["rule", "candidate"]   # "rule": a known secret shape; "candidate": looks suspicious, needs the model
	rule: str | None                      # rule name for kind == "rule"
	high_confidence: bool                 # True: block without asking the model (outside example paths)
	value: str                            # the secret-looking value, used for masking and the model question
	start: int = 0                        # span of `value` in the line
	end: int = 0


@dataclass(frozen=True)
class Finding:
	path: str
	number: int
	level: Literal["block", "warn"]
	reason: str
	preview: str                          # masked, never the raw secret
	p: float | None = None


@dataclass
class ScanResult:
	findings: list[Finding] = field(default_factory=list)
	model_unavailable: bool = False
	model_skipped: str | None = None      # why the model was deliberately not used, e.g. "hosted_scope"
	budget_exhausted: bool = False        # the model time budget ran out; the rest were not judged

	@property
	def exit_code(self) -> int:
		return 1 if any(f.level == "block" for f in self.findings) else 0
