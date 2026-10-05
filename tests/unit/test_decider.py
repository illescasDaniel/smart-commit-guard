import pytest

from smart_commit_guard.decider import MAX_ITEM_CHARS, DeciderUnavailable, HttpDecider


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
	assert "items[0]" in qs["item_0"]["instructions"] and "items[1]" in qs["item_1"]["instructions"]
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


# --- 0.5: nothing for a local server may leave through a proxy or a redirect

import json as _json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from smart_commit_guard.decider import build_opener


class _Server:
	"""A throwaway server on 127.0.0.1: answers /v1/systemone, or redirects /redirect/v1/systemone to it."""

	def __init__(self):
		outer = self
		self.bodies: list[bytes] = []

		class Handler(BaseHTTPRequestHandler):
			def do_POST(self):
				body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
				if self.path.startswith("/redirect"):
					self.send_response(307)
					self.send_header("Location", f"http://127.0.0.1:{outer.port}/v1/systemone")
					self.end_headers()
					return
				outer.bodies.append(body)
				reply = _json.dumps({"answers": {"item_0": {"type": "noul", "noul": 0.25}}}).encode()
				self.send_response(200)
				self.send_header("Content-Length", str(len(reply)))
				self.end_headers()
				self.wfile.write(reply)

			def log_message(self, format, *args):
				pass

		self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
		self.port = self.httpd.server_address[1]
		threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

	def close(self):
		self.httpd.shutdown()
		self.httpd.server_close()


@pytest.fixture
def server():
	s = _Server()
	yield s
	s.close()


@pytest.fixture
def dead_proxy(monkeypatch):
	for key in ("NO_PROXY", "no_proxy"):
		monkeypatch.delenv(key, raising=False)
	for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
		monkeypatch.setenv(key, "http://127.0.0.1:9")   # nothing listens here: a call routed through it fails


def test_given_a_proxy_in_the_environment_when_judging_on_loopback_then_the_call_still_succeeds_and_bypasses_it(server, dead_proxy):
	d = HttpDecider(f"http://127.0.0.1:{server.port}", "m", 5.0)
	assert d.judge([("a.py", "x = 'k'")]) == [0.25] and server.bodies


def _proxy_handlers(url):
	return [h for h in vars(build_opener(url))["handlers"] if isinstance(h, urllib.request.ProxyHandler)]


def test_given_a_loopback_url_when_building_the_opener_then_no_proxy_handler_has_entries(dead_proxy):
	handlers = _proxy_handlers("http://localhost:11435")
	assert not any(h.proxies for h in handlers)


def test_given_a_hosted_url_when_building_the_opener_then_proxy_support_is_kept(dead_proxy):
	handlers = _proxy_handlers("https://api.example.com")
	assert any(h.proxies for h in handlers)


def test_given_a_server_that_redirects_when_judging_then_the_payload_is_not_re_sent_and_the_decider_is_unavailable(server):
	d = HttpDecider(f"http://127.0.0.1:{server.port}/redirect", "m", 5.0)
	with pytest.raises(DeciderUnavailable):
		d.judge([("a.py", "x = 'k'")])
	assert server.bodies == []


def test_given_a_non_utf8_answer_when_judging_then_it_is_unavailable_not_a_crash():
	with pytest.raises(DeciderUnavailable):
		make(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"), []).judge([("a.py", "a")])
