"""QA test QUAL-004: .env.example contains all required keys with no real credentials."""
import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "app" / "config.py"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"


def _extract_settings_fields(config_path: Path) -> set[str]:
    """Extract all field names declared in the Settings class."""
    source = config_path.read_text()
    tree = ast.parse(source)

    fields: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and stmt.target:
                    name = stmt.target.id if isinstance(stmt.target, ast.Name) else None
                    if name and not name.startswith("_") and name != "model_config":
                        fields.add(name)
    return fields


def _extract_env_vars(env_path: Path) -> dict[str, str]:
    """Parse .env.example into a dict of key=value (ignoring comments/blanks)."""
    result: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        result[key] = value
    return result


# ── Real-credential heuristics ───────────────────────────────────────
# Patterns that strongly suggest a real secret (not a placeholder).
REAL_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),           # OpenAI-style API key
    re.compile(r"ghp_[a-zA-Z0-9]{30,}"),           # GitHub PAT
    re.compile(r"AKIA[0-9A-Z]{16}"),               # AWS access key
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),       # Base64 blob >40 chars
]

# Patterns that indicate a clearly-fake placeholder.
PLACEHOLDER_INDICATORS = [
    "changeme", "change-me", "your-", "xxx", "placeholder",
    "example", "replace", "todo", "fixme", "default",
    "localhost", "127.0.0.1", "mailhog", "test",
]


def _is_clearly_placeholder(value: str) -> bool:
    """Return True if the value looks like an intentional placeholder."""
    low = value.lower()
    return any(ind in low for ind in PLACEHOLDER_INDICATORS)


def _looks_like_real_secret(value: str) -> list[str]:
    """Return list of pattern descriptions that match (empty = safe)."""
    hits = []
    for pat in REAL_SECRET_PATTERNS:
        if pat.search(value):
            hits.append(pat.pattern)
    return hits


def test_all_settings_fields_in_env_example():
    """Every Settings field must have a corresponding .env.example entry."""
    settings_fields = _extract_settings_fields(CONFIG_PATH)
    env_vars = _extract_env_vars(ENV_EXAMPLE_PATH)
    missing = settings_fields - set(env_vars.keys())
    assert not missing, f"Settings fields missing from .env.example: {missing}"


def test_no_extra_env_vars():
    """Every .env.example key should correspond to a Settings field (informational, not hard fail)."""
    settings_fields = _extract_settings_fields(CONFIG_PATH)
    env_vars = _extract_env_vars(ENV_EXAMPLE_PATH)
    extra = set(env_vars.keys()) - settings_fields
    # Not a hard failure — extra vars are informational
    if extra:
        import warnings
        warnings.warn(f"Extra keys in .env.example not in Settings: {extra}")


def test_no_real_credentials():
    """No .env.example value should contain what looks like a real API key or secret."""
    env_vars = _extract_env_vars(ENV_EXAMPLE_PATH)
    failures = []
    for key, value in env_vars.items():
        hits = _looks_like_real_secret(value)
        if hits and not _is_clearly_placeholder(value):
            failures.append(f"  {key}={value}  matched secret patterns: {hits}")
    assert not failures, (
        "Found values that look like real credentials:\n" + "\n".join(failures)
    )


def test_sensitive_values_are_placeholders():
    """Values for known-sensitive keys must use clearly-fake placeholders."""
    # Keys that should NEVER contain real production credentials in .env.example
    SENSITIVE_KEYS = {"SMTP_PASS", "LINK_SECRET", "DATABASE_URL"}
    env_vars = _extract_env_vars(ENV_EXAMPLE_PATH)
    failures = []

    for key in SENSITIVE_KEYS:
        value = env_vars.get(key, "")
        if not value:
            # Empty string is acceptable (e.g. SMTP_USER, SMTP_PASS with no auth)
            continue
        if not _is_clearly_placeholder(value):
            failures.append(
                f"  {key}={value}  — value is not a clearly-fake placeholder"
            )

    assert not failures, (
        "Sensitive keys have values that are not clearly placeholders:\n"
        + "\n".join(failures)
    )
