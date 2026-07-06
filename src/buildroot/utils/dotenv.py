"""Minimal .env file loader. Does not override existing env vars."""

import os
from pathlib import Path


def load_dotenv(env_file: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Skips blank lines and comments (#). Strips matching outer quotes
    from values (both single and double). Does not override vars that
    are already set in the environment.
    """
    if env_file is None:
        env_file = Path(__file__).resolve().parents[3] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        os.environ.setdefault(key, val)
