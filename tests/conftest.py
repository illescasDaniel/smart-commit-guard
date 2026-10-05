import pytest

from smart_commit_guard.decider import DeciderUnavailable


class FakeDecider:
	"""Records every batch; answers with `rule(path, text) -> p`."""

	def __init__(self, rule=lambda path, text: 0.0):
		self.rule = rule
		self.batches: list[list[tuple[str, str]]] = []
		self.down = False

	def judge(self, items):
		if self.down:
			raise DeciderUnavailable("fake outage")
		self.batches.append(list(items))
		return [self.rule(p, t) for p, t in items]

	@property
	def seen_text(self) -> str:
		return "\n".join(t for b in self.batches for _, t in b)


@pytest.fixture
def fake():
	return FakeDecider


# Test secrets are assembled at runtime so this file never trips a scanner (including this tool).
AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
