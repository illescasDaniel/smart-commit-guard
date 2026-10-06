"""Generate the large synthetic eval set: `python evals/generate_cases.py > evals/cases_generated.json`.

Every case is built from a template (how the line is written: language, quoting, key name) and a value kind (what the value
is). Real cases use random synthetic values, never a real credential. Templates are split into `tune` and `test` halves, so
a threshold fitted on `tune` is scored on templates the model never influenced, and the report can show recall per family.
Only lines the deterministic layer sends to the model are kept (`stage == "model"`): the rest never reach it.
"""
from __future__ import annotations

import json
import random
import string
import sys
import uuid

from smart_commit_guard.policy import stage

R = random.Random(20261006)
ALNUM = string.ascii_letters + string.digits
WORDS = ["Winter", "Summer", "Dragon", "Falcon", "Monkey", "Welcome", "Admin", "Qwerty", "Server", "Secret", "Orange", "Tiger"]
SYMBOLS = "!@#$%&*?"


# --- value kinds: (family, generator)
def human_password() -> str:
	return R.choice(WORDS) + str(R.choice([R.randint(1, 99), R.randint(1990, 2026)])) + R.choice(SYMBOLS) + R.choice([R.choice(WORDS)[:4], ""])


def passphrase() -> str:
	return "-".join(R.choice(["correct", "horse", "battery", "staple", "mango", "river", "copper", "lantern", "violet"]) + str(R.randint(0, 99))
					for _ in range(2)) + R.choice(SYMBOLS)


def hex_secret(n: int = 32) -> str:
	return "".join(R.choice("0123456789abcdef") for _ in range(n))


def alnum_secret(n: int = 24) -> str:
	return "".join(R.choice(ALNUM) for _ in range(n))


def b64_secret(n: int = 40) -> str:
	return "".join(R.choice(ALNUM + "/+") for _ in range(n))


def prefixed_secret() -> str:
	return R.choice(["bk_", "svc_", "int_", "app-", "tok_", "sk_internal_"]) + alnum_secret(R.randint(20, 32))


def jwt_like() -> str:
	return "eyJ" + alnum_secret(17) + "." + "eyJ" + alnum_secret(30) + "." + alnum_secret(27)


REAL_VALUES = {"human_password": human_password, "passphrase": passphrase, "hex": hex_secret, "alnum": alnum_secret,
			   "base64": b64_secret, "prefixed": prefixed_secret, "jwt": jwt_like}

SECRET_KEYS = ["password", "db_password", "DB_PASS", "api_key", "API_SECRET", "client_secret", "auth_token", "secret_key",
			   "SMTP_PASSWORD", "access_token", "private_token", "admin_pass", "redis_password", "webhook_secret", "service_key"]

# real templates: (id, path, line format, quote style); `{k}` key, `{v}` value
REAL_TEMPLATES = [
	("py-assign", "src/settings.py", '{k} = "{v}"'), ("py-single", "src/conf.py", "{k} = '{v}'"),
	("py-dict", "src/client.py", 'headers = {{"{k}": "{v}"}}'), ("py-kwarg", "src/db.py", 'connect(host="db", {k}="{v}")'),
	("js-const", "src/config.js", "const {k} = '{v}';"), ("ts-export", "src/env.ts", 'export const {k} = "{v}";'),
	("json", "config/app.json", '  "{k}": "{v}",'), ("yaml", "config/prod.yaml", "  {k}: {v}"), ("yaml-quoted", "deploy/values.yaml", '  {k}: "{v}"'),
	("toml", "config/app.toml", '{k} = "{v}"'), ("ini", "config/app.ini", "{k} = {v}"), ("env", "deploy/prod.env.txt", "{k}={v}"),
	("java", "src/main/Config.java", 'private static final String {k} = "{v}";'), ("go", "internal/cfg.go", 'var {k} = "{v}"'),
	("rust", "src/config.rs", 'const {k}: &str = "{v}";'), ("php", "app/config.php", "${k} = '{v}';"), ("ruby", "config/initializers/x.rb", "config.{k} = '{v}'"),
	("shell-export", "scripts/deploy.sh", 'export {k}="{v}"'), ("docker-env", "Dockerfile.prod", "ENV {k} {v}"),
	("compose", "docker-compose.prod.yml", "      - {k}={v}"), ("terraform", "infra/main.tf", '  {k} = "{v}"'),
	("curl-header", "scripts/call.sh", 'curl -H "Authorization: Bearer {v}" https://api.internal.example/v1'),
	("cli-flag", "Makefile", "\tmytool --{k}={v} deploy"), ("csharp", "src/Config.cs", 'public const string {k} = "{v}";'),
	("swift", "App/Secrets.swift", 'let {k} = "{v}"'), ("comment", "src/app.py", '# temporary: {k} is {v}, remove before release'),
	("log-line", "docs/runbook.txt", "the {k} for staging is {v}"), ("sql", "db/seed.sql", "ALTER USER app WITH PASSWORD '{v}';"),
]

# ok values under sensitive-looking keys, and secret-looking values under harmless keys
OK_SENSITIVE_KEY = [
	("ttl", lambda: str(R.choice([300, 3600, 86400, 604800])), ["token_ttl", "REFRESH_TOKEN_TTL", "password_max_age", "secret_rotation_days"]),
	("type-name", lambda: R.choice(["Bearer", "Basic", "oauth2", "jwt", "hmac-sha256", "bcrypt", "argon2id"]),
	 ["token_type", "auth_scheme", "password_hash_algorithm", "secret_kind"]),
	("label", lambda: R.choice(["Reset your password", "Enter your API key", "Mother's maiden name", "Forgot password?", "Secret santa list"]),
	 ["password_label", "api_key_hint", "secret_question", "token_help_text"]),
	("reference", lambda: R.choice(["app-db-credentials", "prod/db/password", "vault:secret/data/app", "arn:aws:secretsmanager:eu-west-1:123456789012:secret:app",
									"projects/p/secrets/api-key/versions/latest"]),
	 ["existingSecret", "password_secret_name", "secret_ref", "api_key_path", "secretName"]),
	("public-key-id", lambda: R.choice(["pk_test_", "pk_live_"]) + alnum_secret(24), ["publishable_key", "STRIPE_PUBLIC_KEY", "public_api_key"]),
	("hash-of-file", lambda: hex_secret(64), ["expected_sha256", "checksum", "file_digest", "content_hash"]),
	("git-sha", lambda: hex_secret(40), ["pinned_commit", "GIT_REV", "build_sha", "source_revision"]),
	("uuid", lambda: str(uuid.UUID(int=R.getrandbits(128), version=4)), ["request_id", "tenant_uuid", "session_key_id", "correlation_token"]),
	("flag", lambda: R.choice(["true", "false", "required", "disabled"]), ["password_required", "token_enabled", "secret_mode"]),
]
OK_PLAIN_KEY = [
	("opaque-id", lambda: alnum_secret(R.choice([16, 22, 28])), ["build_id", "trace_id", "node_id", "element_id", "etag", "nonce_public"]),
	("hash", lambda: hex_secret(R.choice([32, 40, 64])), ["integrity", "digest", "image_digest", "last_commit", "sha"]),
	("uuid", lambda: str(uuid.UUID(int=R.getrandbits(128), version=4)), ["device_id", "order_ref", "record_id", "guid"]),
	("css-color", lambda: "#" + hex_secret(6), ["background", "accent", "border_color"]),
	("base64-chunk", lambda: b64_secret(R.choice([44, 60, 88])), ["icon_data", "thumbnail", "font_chunk", "svg_blob"]),
	("path", lambda: "/".join(R.choice(["usr", "var", "lib", "opt", "srv", "cache", "app"]) for _ in range(3)) + "/" + alnum_secret(8), ["data_dir", "socket_path", "tmp_file"]),
	("url", lambda: "https://cdn.example.com/assets/" + alnum_secret(12) + ".js", ["script_url", "asset", "src"]),
	("sentence", lambda: R.choice(["Click here to continue", "Welcome back to the dashboard", "Unable to load profile", "Order shipped on Monday"]), ["message", "title", "label", "text"]),
]
OK_TEMPLATES = [(t[0], t[1], t[2]) for t in REAL_TEMPLATES if t[0] not in {"curl-header", "comment", "log-line", "sql", "cli-flag", "docker-env"}]


def build() -> list[dict]:
	cases: list[dict] = []
	# split templates by id parity of a shuffled list, so each half has a mix of languages
	ids = [t[0] for t in REAL_TEMPLATES]
	order = ids[:]
	R.shuffle(order)
	split = {tid: ("tune" if i % 2 == 0 else "test") for i, tid in enumerate(order)}

	for tid, path, fmt in REAL_TEMPLATES:
		for family, gen in REAL_VALUES.items():
			for _ in range(2):
				k = R.choice(SECRET_KEYS)
				text = fmt.format(k=k, v=gen())
				cases.append({"path": path, "text": text, "label": "real", "family": family, "template": tid, "split": split[tid]})
	for tid, path, fmt in OK_TEMPLATES:
		for family, gen, keys in OK_SENSITIVE_KEY:
			text = fmt.format(k=R.choice(keys), v=gen())
			cases.append({"path": path, "text": text, "label": "ok", "family": "ok-" + family, "template": tid, "split": split[tid]})
		for family, gen, keys in OK_PLAIN_KEY:
			text = fmt.format(k=R.choice(keys), v=gen())
			cases.append({"path": path, "text": text, "label": "ok", "family": "ok-" + family, "template": tid, "split": split[tid]})
	# only what the model sees, once per distinct line
	out, seen = [], set()
	for c in cases:
		st = stage(c["path"], c["text"])
		if st == "model" and c["text"] not in seen:
			seen.add(c["text"])
			out.append({**c, "stage": st})
	return out


if __name__ == "__main__":
	cases = build()
	print(f"{len(cases)} cases ({sum(c['label'] == 'real' for c in cases)} real)", file=sys.stderr)
	json.dump(cases, sys.stdout, indent="\t", ensure_ascii=False)
