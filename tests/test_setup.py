"""Phase 0 guard rails: the repo never tracks data, secrets or model weights."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_gitignore_covers_private_and_large_files():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in [".env", "data/", "*.gguf", "*.safetensors", "*.pt", ".venv/", "__pycache__/", "*.duckdb"]:
        assert pattern in ignored, f"{pattern} missing from .gitignore"


def test_env_example_has_no_real_values():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in example.splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            assert value.strip() == "", f"{key} should be blank in .env.example"
