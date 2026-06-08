"""HTTP client for Maven Central POM fetching."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

MAVEN_CENTRAL_BASE = "https://repo1.maven.org/maven2"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "buildroot" / "poms"
MAX_RETRIES = 3
BACKOFF_BASE = 1.0


def _cache_key(group_id: str, artifact_id: str, version: str) -> str:
    gav = f"{group_id}:{artifact_id}:{version}"
    return hashlib.sha256(gav.encode()).hexdigest()


def _pom_url(group_id: str, artifact_id: str, version: str) -> str:
    group_path = group_id.replace(".", "/")
    return f"{MAVEN_CENTRAL_BASE}/{group_path}/{artifact_id}/{version}/{artifact_id}-{version}.pom"


def fetch_pom(
    group_id: str,
    artifact_id: str,
    version: str,
    *,
    no_cache: bool = False,
    cache_dir: Path | None = None,
) -> str:
    """Fetch a POM from Maven Central with caching and retry.

    Returns the POM XML text.
    Raises requests.HTTPError on non-retryable failures.
    """
    cache = cache_dir or DEFAULT_CACHE_DIR

    if not no_cache:
        cached = _read_cache(cache, group_id, artifact_id, version)
        if cached is not None:
            logger.debug("Cache hit for %s:%s:%s", group_id, artifact_id, version)
            return cached

    url = _pom_url(group_id, artifact_id, version)
    xml_text = _fetch_with_retry(url)

    if not no_cache:
        _write_cache(cache, group_id, artifact_id, version, xml_text)

    return xml_text


def _read_cache(cache_dir: Path, group_id: str, artifact_id: str, version: str) -> str | None:
    key = _cache_key(group_id, artifact_id, version)
    path = cache_dir / f"{key}.pom"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _write_cache(cache_dir: Path, group_id: str, artifact_id: str, version: str, content: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(group_id, artifact_id, version)
    path = cache_dir / f"{key}.pom"
    path.write_text(content, encoding="utf-8")


def _fetch_with_retry(url: str) -> str:
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return resp.text
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            wait = BACKOFF_BASE * (2 ** attempt)
            logger.warning("Retry %d/%d for %s (%.1fs backoff): %s", attempt + 1, MAX_RETRIES, url, wait, exc)
            time.sleep(wait)
        except requests.HTTPError:
            raise
    raise last_exc  # type: ignore[misc]
