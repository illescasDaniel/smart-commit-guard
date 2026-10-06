from importlib.metadata import PackageNotFoundError, version

try:
	__version__ = version("smart-commit-guard")
except PackageNotFoundError:   # running from a checkout that was never installed
	__version__ = "unknown"
