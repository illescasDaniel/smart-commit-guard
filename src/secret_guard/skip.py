"""Paths that are never scanned, and paths where findings are likely examples."""
from __future__ import annotations

from pathlib import PurePosixPath

_LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock", "pipfile.lock",
			  "cargo.lock", "gemfile.lock", "composer.lock", "go.sum", "bun.lock", "bun.lockb"}
_BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".tar", ".7z", ".woff",
					".woff2", ".ttf", ".otf", ".mp3", ".mp4", ".mov", ".avif", ".heic", ".so", ".dll", ".exe", ".pyc"}
_GENERATED_SUFFIXES = (".min.js", ".min.css", ".map")
_EXAMPLE_DIRS = {"test", "tests", "fixtures", "fixture", "docs", "doc", "examples", "example", "samples", "sample"}
_TEMPLATE_MARKERS = ("example", "sample", "template", ".dist", "defaults")
_SSH_KEYS = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "id_ecdsa_sk", "id_ed25519_sk"}
# basename -> why it must not be committed
_SENSITIVE_NAMES = {
	".netrc": "netrc credentials", "_netrc": "netrc credentials", ".pgpass": "PostgreSQL password file",
	".pypirc": "PyPI upload credentials", ".htpasswd": "htpasswd password hashes",
	".git-credentials": "stored git credentials", ".dockercfg": "Docker registry credentials",
	".s3cfg": "s3cmd credentials", ".boto": "boto credentials", "kubeconfig": "Kubernetes credentials",
	"terraform.tfstate": "Terraform state (holds secrets in plain text)",
	"terraform.tfstate.backup": "Terraform state (holds secrets in plain text)",
	"credentials.json": "service credentials", ".env.vault": "dotenv vault keys",
}
_SENSITIVE_SUFFIXES = {
	".p12": "PKCS#12 key store", ".pfx": "PKCS#12 key store", ".jks": "Java key store", ".keystore": "Java key store",
	".ppk": "PuTTY private key", ".kdbx": "KeePass password database", ".tfstate": "Terraform state (holds secrets in plain text)",
	".tfvars": "Terraform variables (often hold secrets)", ".mobileprovision": "iOS provisioning profile",
}
# (parent directory, basename)
_SENSITIVE_PATHS = {(".aws", "credentials"): "AWS credentials", (".docker", "config.json"): "Docker registry credentials",
					(".kube", "config"): "Kubernetes credentials", (".ssh", "config"): "SSH configuration",
					(".gnupg", "secring.gpg"): "GPG secret keyring"}
_SENSITIVE_PREFIXES = (("client_secret", ".json", "OAuth client secret"), ("service-account", ".json", "service account key"),
					   ("service_account", ".json", "service account key"), ("serviceaccount", ".json", "service account key"))
ENV_REASON = "environment file should not be committed (add it to .gitignore, commit a .env.example instead)"
_EXAMPLE_NAME_MARKERS = (".example", ".sample", "-example", "_example")


def _parts(path: str) -> tuple[str, ...]:
	return tuple(p.lower() for p in PurePosixPath(path).parts)


def is_skipped(path: str) -> bool:
	"""Lockfiles, generated files, binaries by extension, and `.env.example`."""
	name = PurePosixPath(path).name.lower()
	return (name in _LOCKFILES or name == ".env.example" or name.endswith(_GENERATED_SUFFIXES)
			or PurePosixPath(name).suffix in _BINARY_SUFFIXES)


def is_env_file(path: str) -> bool:
	"""`.env`, `.env.local`, `prod.env`...: files that hold real environment secrets and should not be committed."""
	name = PurePosixPath(path).name.lower()
	return ((name == ".env" or name.startswith(".env.") or name.endswith(".env"))
			and not any(m in name for m in _TEMPLATE_MARKERS))


def sensitive_file_reason(path: str) -> str | None:
	"""Why a file of this name must never be committed (keys, credentials, state, env files), or None. Templates are exempt."""
	parts = _parts(path)
	name = parts[-1] if parts else ""
	if is_env_file(path):
		return ENV_REASON
	if any(m in name for m in _TEMPLATE_MARKERS):
		return None
	if name in _SSH_KEYS:
		return "SSH private key"
	if name in _SENSITIVE_NAMES:
		return _SENSITIVE_NAMES[name]
	if len(parts) > 1 and (parts[-2], name) in _SENSITIVE_PATHS:
		return _SENSITIVE_PATHS[(parts[-2], name)]
	for prefix, suffix, why in _SENSITIVE_PREFIXES:
		if name.startswith(prefix) and name.endswith(suffix):
			return why
	if ".tfstate" in name:
		return _SENSITIVE_SUFFIXES[".tfstate"]
	return _SENSITIVE_SUFFIXES.get(PurePosixPath(name).suffix)


def is_example_path(path: str) -> bool:
	"""Tests, fixtures, docs, READMEs and examples: a rule hit there is judged by the model instead of blocking."""
	parts = _parts(path)
	name = parts[-1] if parts else ""
	return (bool(_EXAMPLE_DIRS.intersection(parts[:-1])) or name.startswith(("test_", "readme"))
			or name.endswith(("_test.py", ".md", ".rst")) or any(m in name for m in _EXAMPLE_NAME_MARKERS))
