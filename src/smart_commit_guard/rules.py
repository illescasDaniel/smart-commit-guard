"""Deterministic layer: known secret shapes and candidate extraction."""
from __future__ import annotations

import math
import re
from collections import Counter

from .types import LineHit

_NO_REF = r"(?![\$\{<%])"   # a value that starts like ${VAR}, <placeholder> or %VAR% is a reference, not a secret

_RULES: list[tuple[str, re.Pattern[str], int]] = [   # (name, pattern, group holding the secret)
	("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), 0),
	("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
	("API token", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|sk_(?:live|test)_[A-Za-z0-9]{10,}|gh[pousr]_[A-Za-z0-9]{20,}"
							 r"|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|glpat-[A-Za-z0-9_-]{15,})"), 0),
	("webhook URL", re.compile(r"https://(?:hooks\.slack\.com/services/[A-Za-z0-9/]{20,}"
							   r"|(?:discord|discordapp)\.com/api/webhooks/\d+/[A-Za-z0-9_-]{20,})"), 0),
	("connection string with password", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:" + _NO_REF + r"([^\s@/'\"]+)@([^\s/:'\"]*)"), 1),
]
_PLACEHOLDER_PASSWORDS = {"pass", "password", "passwd", "secret", "changeme", "example", "xxx", "xxxx", "postgres", "admin"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "host", "hostname", "example.com", "db", "database"}

_NAME = r"[A-Za-z0-9_.-]*(?:pass(?:word|wd|phrase)?|secret|token|api[_-]?key|apikey|credential|private[_-]?key)[A-Za-z0-9_.-]*"
_QUOTED_ASSIGNMENT = re.compile(rf"(?i)\b{_NAME}[\"']?\s*[:=]\s*[\"']" + _NO_REF + r"([^\"']{4,})[\"']")
_BARE_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?[A-Z0-9_]*(?:PASS|SECRET|TOKEN|KEY|CREDENTIAL|AUTH)[A-Z0-9_]*\s*=\s*"
							  + _NO_REF + r"([A-Za-z0-9+/_\-!@#%^&*]{6,})\s*$")
_NAME_WORD = r"[A-Za-z0-9_.-]*(?:pass(?:word|wd|phrase)?|secret|token|api[_-]?key|apikey|credential|private[_-]?key)[A-Za-z0-9_.-]*"
_UNQUOTED = re.compile(rf"(?i)^[\s-]*{_NAME_WORD}\s*[:=]\s*" + _NO_REF + r"([^\s\"'$<{(\[]{6,})\s*$")   # YAML/compose/.env values
_PROSE = re.compile(r"(?i)\bpass(?:word|phrase)\s+is\s+" + _NO_REF + r"([^\s\"']{6,})")
_BEARER = re.compile(r"(?i)\bBearer\s+" + _NO_REF + r"([A-Za-z0-9._~+/=-]{20,})")
_KV_PASSWORD = re.compile(r"(?i)\b(?:pwd|password)=" + _NO_REF + r"([^;\"'\s]{4,})")
_CLI_PASSWORD = re.compile(r"\b(?:mysql|mysqldump|psql|mongo|redis-cli)\b[^\n]*?\s-p" + _NO_REF + r"([^\s'\"]{4,})")
_LITERAL = re.compile(r"[\"']([A-Za-z0-9+/_=-]{24,})[\"']")


def _entropy(s: str) -> float:
	n = len(s)
	return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


_PLACEHOLDER = re.compile(r"(?i)(?:^|[-_. ])(?:your|my|example|sample|dummy|fake|mock|test|demo|changeme|replace(?:me)?|placeholder|"
						  r"redacted|todo|none|null|secret|password|passwd|token|key)(?:$|[-_. 0-9]|here)|^x{4,}$|^\*+$|\.\.\.|^[-_.x*]+$")


def _is_placeholder(v: str) -> bool:
	"""Obvious dummy values (`your-api-key-here`, `changeme`, `xxxxxxxx`, `test-token-123`) never need a model."""
	return bool(_PLACEHOLDER.search(v))


def _has_digit_and_letter(v: str) -> bool:
	return any(c.isdigit() for c in v) and any(c.isalpha() for c in v)


def _looks_like_path_or_identifier(v: str) -> bool:
	"""Filesystem paths (`/storage/emulated/0/Download`) and snake_case names are long and varied but not secrets."""
	return v.count("/") >= 2 or bool(re.fullmatch(r"_*[a-z][a-z0-9]*(?:_[a-z0-9]+)+_*", v))


def _is_placeholder_url(m: re.Match[str]) -> bool:
	return m.group(1).lower() in _PLACEHOLDER_PASSWORDS or m.group(2).lower() in _LOCAL_HOSTS


def scan_line(text: str) -> LineHit | None:
	"""A rule hit (high confidence for private keys, AWS keys, token prefixes, URLs with a password), a candidate
	(secret-looking name assigned a literal, or a long high-entropy literal), or None."""
	for name, rx, group in _RULES:
		if m := rx.search(text):
			if name == "connection string with password" and _is_placeholder_url(m):
				return None if _is_placeholder(m.group(group)) else LineHit("candidate", None, False, m.group(group))
			return LineHit("rule", name, True, m.group(group))
	for rx in (_QUOTED_ASSIGNMENT, _BARE_ASSIGNMENT, _BEARER, _KV_PASSWORD, _CLI_PASSWORD, _PROSE):
		if (m := rx.search(text)) and not (rx is _PROSE and m.group(1).isalpha()):   # "password is required" is prose
			return None if _is_placeholder(m.group(1)) else LineHit("candidate", None, False, m.group(1))
	if (m := _UNQUOTED.search(text)) and _has_digit_and_letter(m.group(1)) and not m.group(1).startswith("http"):
		return None if _is_placeholder(m.group(1)) else LineHit("candidate", None, False, m.group(1))
	for m in _LITERAL.finditer(text):
		v = m.group(1)
		if _looks_like_path_or_identifier(v):
			continue
		if any(c.isdigit() for c in v) and any(c.isalpha() for c in v) and _entropy(v) >= 3.5:
			return LineHit("candidate", None, False, v)
	return None
