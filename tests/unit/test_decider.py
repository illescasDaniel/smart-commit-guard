import pytest

from secret_guard.decider import MAX_ITEM_CHARS, DeciderUnavailable, HttpDecider


def make(response, calls):
	def post(url, payload, timeout):
		calls.append((url, payload, timeout))
		if isinstance(response, Exception):
			raise response
		return response
	return HttpDecider("http://localhost:11435", "m", 5.0, post=post)


def answers(*ps):
	return {"answers": {f"item_{i}": {"type": "noul", "noul": p} for i, p in enumerate(ps)}}


def test_given_two_items_when_judging_then_one_systemone_request_carries_noul_questions():
	calls = []
	ps = make(answers(0.9, 0.1), calls).judge([("a.py", "X = 'k'"), ("b.py", "Y = 'v'")])
	url, payload, timeout = calls[0]
	assert ps == [0.9, 0.1] and len(calls) == 1 and timeout == 5.0
	assert url == "http://localhost:11435/v1/systemone" and payload["model"] == "m"
	qs = payload["questions"]
	assert set(qs) == {"item_0", "item_1"}
	assert all(q["type"] == "noul" and set(q) <= {"type", "instructions", "criteria"} and q["instructions"] for q in qs.values())
	assert payload["state"]["items"][0] == {"path": "a.py", "line": "X = 'k'"}


def test_given_a_very_long_line_when_judging_then_it_is_truncated_before_sending():
	calls = []
	make(answers(0.1), calls).judge([("a.py", "x" * 5000)])
	assert len(calls[0][1]["state"]["items"][0]["line"]) <= MAX_ITEM_CHARS


def test_given_a_missing_answer_when_judging_then_it_fails_instead_of_passing():
	with pytest.raises(DeciderUnavailable):
		make(answers(0.9), []).judge([("a.py", "a"), ("b.py", "b")])


def test_given_a_non_noul_answer_when_judging_then_it_fails():
	bad = {"answers": {"item_0": {"type": "choice", "choice": "x"}}}
	with pytest.raises(DeciderUnavailable):
		make(bad, []).judge([("a.py", "a")])


@pytest.mark.parametrize("error", [TimeoutError("slow"), ConnectionError("down"), OSError("x")])
def test_given_a_transport_error_when_judging_then_it_is_unavailable(error):
	with pytest.raises(DeciderUnavailable):
		make(error, []).judge([("a.py", "a")])
