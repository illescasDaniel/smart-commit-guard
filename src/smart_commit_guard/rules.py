"""Deterministic layer: known secret shapes (a rule table) and candidate extraction."""
from __future__ import annotations

import base64
import binascii
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from .types import LineHit

_NO_REF = r"(?![\$\{<%])"   # a value that starts like ${VAR}, <placeholder> or %VAR% is a reference, not a secret


@dataclass(frozen=True)
class Rule:
	"""A known secret shape. The match (or `group`) is the secret; `prefixes` stay visible when it is masked."""
	name: str
	pattern: re.Pattern[str]
	group: int = 0
	prefixes: tuple[str, ...] = ()


def _rule(name: str, pattern: str, group: int = 0, prefixes: tuple[str, ...] = ()) -> Rule:
	return Rule(name, re.compile(pattern), group, prefixes)


_ALNUM = r"[A-Za-z0-9]"
_URLSAFE = r"[A-Za-z0-9_-]"
# Order matters: when two rules match the same text the first one names it (Anthropic before the generic `sk-` rule).
RULES: tuple[Rule, ...] = (
	_rule("private key", r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"),
	_rule("AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", prefixes=("AKIA", "ASIA")),
	_rule("GitHub token", rf"\bgh[pousr]_{_ALNUM}{{20,}}", prefixes=("ghp_", "gho_", "ghu_", "ghs_", "ghr_")),
	_rule("GitHub fine-grained token", r"\bgithub_pat_[A-Za-z0-9_]{60,}", prefixes=("github_pat_",)),
	_rule("Anthropic API key", rf"\bsk-ant-{_URLSAFE}{{20,}}", prefixes=("sk-ant-",)),
	# a real key mixes letters and digits; this keeps package names such as `sk-learn-contrib-projects` out
	_rule("API token", rf"\bsk-(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z]){_URLSAFE}{{16,}}", prefixes=("sk-",)),
	_rule("Stripe key", rf"\b[sr]k_(?:live|test)_{_ALNUM}{{10,}}", prefixes=("sk_live_", "sk_test_", "rk_live_", "rk_test_")),
	_rule("Stripe webhook secret", rf"\bwhsec_{_ALNUM}{{20,}}", prefixes=("whsec_",)),
	_rule("Slack token", r"\b(?:xox[abeprs]-[A-Za-z0-9-]{10,}|xapp-[A-Za-z0-9-]{10,})",
		  prefixes=("xoxb-", "xoxa-", "xoxe-", "xoxp-", "xoxr-", "xoxs-", "xapp-")),
	_rule("Google API key", r"\bAIza[0-9A-Za-z_-]{30,}", prefixes=("AIza",)),
	_rule("Google OAuth client secret", rf"\bGOCSPX-{_URLSAFE}{{20,}}", prefixes=("GOCSPX-",)),
	_rule("GitLab token", rf"\bgl(?:pat|ptt|dt|rt)-{_URLSAFE}{{15,}}", prefixes=("glpat-", "glptt-", "gldt-", "glrt-")),
	_rule("SendGrid API key", rf"\bSG\.{_URLSAFE}{{22}}\.{_URLSAFE}{{43}}", prefixes=("SG.",)),
	_rule("PyPI token", rf"\bpypi-AgEI{_URLSAFE}{{50,}}", prefixes=("pypi-",)),
	_rule("npm token", rf"\bnpm_{_ALNUM}{{36}}\b", prefixes=("npm_",)),
	_rule("Shopify token", r"\bshp(?:at|ss|ca|pa)_[a-f0-9]{32}\b", prefixes=("shpat_", "shpss_", "shpca_", "shppa_")),
	_rule("DigitalOcean token", r"\bdop_v1_[a-f0-9]{64}", prefixes=("dop_v1_",)),
	_rule("Doppler token", rf"\bdp\.pt\.{_ALNUM}{{40,}}", prefixes=("dp.pt.",)),
	_rule("Hugging Face token", rf"\bhf_{_ALNUM}{{30,}}", prefixes=("hf_",)),
	_rule("Telegram bot token", rf"\b\d{{8,10}}:AA{_URLSAFE}{{33}}\b"),
	_rule("Azure storage key", r"AccountKey=([A-Za-z0-9+/=]{80,})", group=1),
	_rule("webhook URL", r"https://(?:hooks\.slack\.com/services/[A-Za-z0-9/]{20,}"
						 r"|(?:discord|discordapp)\.com/api/webhooks/\d+/[A-Za-z0-9_-]{20,})"),
	_rule("connection string with password", r"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:" + _NO_REF + r"([^\s@/'\"]+)@([^\s/:'\"]*)", group=1),
)
CONNECTION_STRING = "connection string with password"
KNOWN_PREFIXES: tuple[str, ...] = tuple(sorted({p for r in RULES for p in r.prefixes}, key=lambda p: (-len(p), p)))

_PLACEHOLDER_PASSWORDS = {"pass", "password", "passwd", "secret", "changeme", "example", "xxx", "xxxx", "postgres", "admin"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "host", "hostname", "example.com", "db", "database"}

_NAME = r"[A-Za-z0-9_.-]*(?:pass(?:word|wd|phrase)?|secret|token|api[_-]?key|apikey|credential|private[_-]?key)[A-Za-z0-9_.-]*"
# (pattern, group holding the value). Candidates: they look suspicious but need the model (or a human) to decide.
_CANDIDATES: tuple[tuple[re.Pattern[str], int], ...] = (
	(re.compile(rf"(?i)\b{_NAME}[\"']?\s*[:=]\s*[\"']" + _NO_REF + r"([^\"']{4,})[\"']"), 1),
	(re.compile(r"^\s*(?:export\s+)?[A-Z0-9_]*(?:PASS|SECRET|TOKEN|KEY|CREDENTIAL|AUTH)[A-Z0-9_]*\s*=\s*"
				+ _NO_REF + r"([A-Za-z0-9+/_\-!@#%^&*]{6,})\s*$"), 1),
	(re.compile(r"(?i)\bBearer\s+" + _NO_REF + r"([A-Za-z0-9._~+/=-]{20,})"), 1),
	(re.compile(r"(?i)\b(?:pwd|password)=" + _NO_REF + r"([^;\"'\s]{4,})"), 1),
	(re.compile(r"\b(?:mysql|mysqldump|psql|mongo|redis-cli)\b[^\n]*?\s-p" + _NO_REF + r"([^\s'\"]{4,})"), 1),
	# `.npmrc` / `.yarnrc.yml` registry credentials, quoted or not
	(re.compile(r"(?<![A-Za-z0-9])(?:_authToken|_auth|_password|npmAuthToken)[\"']?\s*[:=]\s*[\"']?" + _NO_REF + r"([^\s\"'()]{8,})(?![^\s\"'()]|\()"), 1),
)
_PROSE = re.compile(r"(?i)\bpass(?:word|phrase)\s+is\s+" + _NO_REF + r"([^\s\"']{6,})")
_UNQUOTED = re.compile(rf"(?i)^[\s-]*{_NAME}\s*[:=]\s*" + _NO_REF + r"([^\s\"'$<{(\[]{6,})\s*$")   # YAML/compose/.env values
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")   # common in tests, so model-judged
_LITERAL = re.compile(r"[\"']([A-Za-z0-9+/_=-]{24,})[\"']")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_HEX_DIGEST = re.compile(r"[0-9a-fA-F]{32,}")
_HASH_CONTEXT = re.compile(r"(?i)(?<![a-z])(?:sha\d*|md5|hash(?:es)?|digest|checksum|commit|rev|integrity|etag)(?![a-z])")


def entropy(s: str) -> float:
	n = len(s)
	return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


_PLACEHOLDER = re.compile(r"(?i)(?:^|[-_. ])(?:your|my|example|sample|dummy|fake|mock|test|demo|changeme|replace(?:me)?|placeholder|"
						  r"redacted|todo|none|null)(?:$|[-_. 0-9]|here)|^x{4,}$|^\*+$|\.\.\.|^[-_.x*]+$")
# a bare word like `password` or `token` marks a placeholder only when the rest is plain words (`wrong-password`, `password123`,
# `prod/db-password`): `Password123!` is a real, weak password
_WEAK_WORD = re.compile(r"(?i)(?<![a-z])(?:secret|password|passwd|token|key)(?![a-z])")
_PLAIN_REST = re.compile(r"[a-z_./ -]*[0-9]{0,4}")


_RUNS = ("0123456789" * 3, "abcdefghijklmnopqrstuvwxyz" * 2, "0123456789abcdefghijklmnopqrstuvwxyz")   # digits and letters wrap
_REPEATED = re.compile(r"(.)\1{5,}")


def _is_sequential(v: str) -> bool:
	"""`abcdefghijklmnop`, `1234567890`, `0123456789abcdef`, `aaaaaaaa`: typed by a person, not generated."""
	low = v.lower()
	return len(low) >= 6 and (bool(_REPEATED.fullmatch(low)) or any(low in run or low[::-1] in run for run in _RUNS))


def _is_weak_word_only(v: str) -> bool:
	return bool(_WEAK_WORD.search(v)) and _PLAIN_REST.fullmatch(_WEAK_WORD.sub("", v).lower()) is not None


def _is_placeholder(v: str) -> bool:
	"""Obvious dummy values (`your-api-key-here`, `changeme`, `xxxxxxxx`, `test-token-123`, `abcdef123456`) never need a model."""
	return bool(_PLACEHOLDER.search(v) or _is_weak_word_only(v)) or _is_sequential(v)


def has_digit_and_letter(v: str) -> bool:
	return any(c.isdigit() for c in v) and any(c.isalpha() for c in v)


_PATH_SEGMENT = re.compile(r"[A-Z]?[a-z0-9._-]+")


def _looks_like_path_or_identifier(v: str) -> bool:
	"""Filesystem paths and snake_case names are long and varied but not secrets. A value with 2+ slashes is a path only
	when it starts like one or every segment is a plain word: a base64 secret (`wJalr.../K7MDENG/bPx...`) is neither."""
	if v.startswith(("/", "./", "../", "~/")):
		return v.count("/") >= 2
	if v.count("/") >= 2 and all(_PATH_SEGMENT.fullmatch(seg) for seg in v.split("/")):
		return True
	return bool(re.fullmatch(r"_*[a-z][a-z0-9]*(?:_[a-z0-9]+)+_*", v))


def _is_placeholder_url(m: re.Match[str]) -> bool:
	return m.group(1).lower() in _PLACEHOLDER_PASSWORDS or m.group(2).lower() in _LOCAL_HOSTS


def _is_hash_or_id(v: str, line: str) -> bool:
	"""UUIDs, and long hex strings on a line about hashes (git SHAs, sha256 sums). A secret-like name still wins: that
	case is caught by the assignment patterns before the generic literal check runs."""
	return bool(_UUID.fullmatch(v)) or (bool(_HEX_DIGEST.fullmatch(v)) and bool(_HASH_CONTEXT.search(line)))


_BASE64 = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/=_-])")
ENCODED = "(base64-encoded)"
MAX_DECODE_DEPTH = 2   # doubly encoded secrets exist; deeper than that is not worth the time


def _decode_text(token: str) -> str | None:
	"""The text a base64 token decodes to, or None when it is not (mostly printable) UTF-8: hashes and binary blobs are skipped."""
	try:
		raw = base64.b64decode(token + "=" * (-len(token) % 4), validate=True)
		text = raw.decode("utf-8")
	except (binascii.Error, UnicodeDecodeError, ValueError):
		return None
	if not text or sum(c.isprintable() or c in "\n\r\t" for c in text) < 0.95 * len(text):
		return None
	return text


def _decoded_rule_hits(token: str, depth: int) -> list[LineHit]:
	text = _decode_text(token)
	if text is None:
		return []
	hits = [h for h in scan_line(text, rules_only=True, _depth=depth + 1) if h.kind == "rule"]
	if not hits and depth + 1 < MAX_DECODE_DEPTH:
		hits = [h for m in _BASE64.finditer(text) for h in _decoded_rule_hits(m.group(), depth + 1)]
	return hits


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
	return a[0] < b[1] and b[0] < a[1]


def scan_line(text: str, *, rules_only: bool = False, _depth: int = 0) -> list[LineHit]:
	"""Every hit on the line, ordered by position. A rule hit is a high-confidence known secret shape (private keys, AWS
	keys, token prefixes, URLs with a password); a candidate is a secret-looking name assigned a literal, or a long
	high-entropy literal. Hits never overlap, and a placeholder value hides only itself, not the rest of the line.
	A base64 token that decodes to text containing a known secret shape is reported as that rule, "(base64-encoded)", so a
	Kubernetes `Secret` or an encoded private key does not hide it. With `rules_only`, candidates are not extracted at all."""
	hits: list[LineHit] = []
	taken: list[tuple[int, int]] = []   # spans already explained: hits and placeholders

	def free(span: tuple[int, int]) -> bool:
		return not any(_overlaps(span, t) for t in taken)

	def add(kind: Literal["rule", "candidate"], rule: str | None, high: bool, span: tuple[int, int]) -> None:
		taken.append(span)
		hits.append(LineHit(kind, rule, high, text[span[0]:span[1]], span[0], span[1]))

	for rule in RULES:
		for m in rule.pattern.finditer(text):
			span = m.span(rule.group)
			if not free(span):
				continue
			if rule.name == CONNECTION_STRING and _is_placeholder_url(m):
				if _is_placeholder(m.group(rule.group)):
					taken.append(span)
				else:
					add("candidate", None, False, span)
				continue
			add("rule", rule.name, True, span)
	if _depth < MAX_DECODE_DEPTH:
		for m in _BASE64.finditer(text):
			if free(m.span()) and (found := _decoded_rule_hits(m.group(), _depth)):
				name = found[0].rule or "secret"
				add("rule", name if name.endswith(ENCODED) else f"{name} {ENCODED}", True, m.span())
	if rules_only:
		return sorted(hits, key=lambda h: h.start)

	def candidate(span: tuple[int, int]) -> None:
		value = text[span[0]:span[1]]
		if _is_placeholder(value):
			taken.append(span)
		else:
			add("candidate", None, False, span)

	for rx, group in _CANDIDATES:
		for m in rx.finditer(text):
			if free(m.span(group)):
				candidate(m.span(group))
	for m in _PROSE.finditer(text):
		if free(m.span(1)) and not m.group(1).isalpha():   # "password is required" is prose
			candidate(m.span(1))
	for m in _UNQUOTED.finditer(text):
		if free(m.span(1)) and has_digit_and_letter(m.group(1)) and not m.group(1).startswith("http"):
			candidate(m.span(1))
	for m in _JWT.finditer(text):
		if free(m.span()):
			add("candidate", None, False, m.span())
	for m in _LITERAL.finditer(text):
		v = m.group(1)
		if not free(m.span(1)) or _looks_like_path_or_identifier(v) or _is_hash_or_id(v, text):
			continue
		if has_digit_and_letter(v) and entropy(v) >= 3.5:
			add("candidate", None, False, m.span(1))
	return sorted(hits, key=lambda h: h.start)
