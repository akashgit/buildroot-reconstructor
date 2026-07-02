"""HTTP client for PyPI package metadata and artifact fetching."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

PYPI_BASE = "https://pypi.org/pypi"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "buildroot" / "pypi"
MAX_RETRIES = 3
BACKOFF_BASE = 1.0
_MAX_ARTIFACT_BYTES = 100 * 1024 * 1024  # 100 MB


def _cache_key(package: str, version: str) -> str:
    pv = f"{package}:{version}"
    return hashlib.sha256(pv.encode()).hexdigest()


def _read_cache(cache_dir: Path, package: str, version: str) -> str | None:
    key = _cache_key(package, version)
    path = cache_dir / f"{key}.json"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _write_cache(cache_dir: Path, package: str, version: str, content: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(package, version)
    path = cache_dir / f"{key}.json"
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
            logger.warning(
                "Retry %d/%d for %s (%.1fs backoff): %s",
                attempt + 1, MAX_RETRIES, url, wait, exc,
            )
            time.sleep(wait)
        except requests.HTTPError:
            raise
    raise last_exc  # type: ignore[misc]


def fetch_package_metadata(
    package: str,
    version: str,
    *,
    no_cache: bool = False,
    cache_dir: Path | None = None,
) -> dict:
    """Fetch package metadata from PyPI JSON API with caching and retry.

    Returns the parsed JSON metadata dict.
    Raises requests.HTTPError on non-retryable failures.
    """
    import json

    cache = cache_dir or DEFAULT_CACHE_DIR

    if not no_cache:
        cached = _read_cache(cache, package, version)
        if cached is not None:
            logger.debug("Cache hit for %s:%s", package, version)
            return json.loads(cached)

    url = f"{PYPI_BASE}/{package}/{version}/json"
    text = _fetch_with_retry(url)

    if not no_cache:
        _write_cache(cache, package, version, text)

    return json.loads(text)


def _find_sdist_url(metadata: dict) -> dict | None:
    for url_info in metadata.get("urls", []):
        if url_info.get("packagetype") == "sdist":
            return url_info
    return None


def _find_wheel_url(metadata: dict) -> dict | None:
    for url_info in metadata.get("urls", []):
        if url_info.get("packagetype") == "bdist_wheel":
            return url_info
    return None


def download_sdist(
    package: str,
    version: str,
    dest_path: Path,
    *,
    verify_checksum: bool = True,
) -> Path:
    """Download an sdist from PyPI and optionally verify its SHA-256 checksum.

    Returns the path to the downloaded file.
    Raises requests.HTTPError on download failure.
    Raises ValueError if checksum verification fails or no sdist is available.
    """
    metadata = fetch_package_metadata(package, version)
    url_info = _find_sdist_url(metadata)
    if url_info is None:
        raise ValueError(f"No sdist found for {package}=={version}")
    return _download_artifact(url_info, dest_path, verify_checksum=verify_checksum)


def download_wheel(
    package: str,
    version: str,
    dest_path: Path,
    *,
    verify_checksum: bool = True,
) -> Path:
    """Download a wheel from PyPI and optionally verify its SHA-256 checksum.

    Returns the path to the downloaded file.
    Raises requests.HTTPError on download failure.
    Raises ValueError if checksum verification fails or no wheel is available.
    """
    metadata = fetch_package_metadata(package, version)
    url_info = _find_wheel_url(metadata)
    if url_info is None:
        raise ValueError(f"No wheel found for {package}=={version}")
    return _download_artifact(url_info, dest_path, verify_checksum=verify_checksum)


def _download_artifact(
    url_info: dict,
    dest_path: Path,
    *,
    verify_checksum: bool = True,
) -> Path:
    url = url_info["url"]
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Downloading artifact from %s", url)
    with requests.get(url, timeout=120, stream=True) as resp:
        resp.raise_for_status()

        sha256 = hashlib.sha256()
        downloaded = 0
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                downloaded += len(chunk)
                if downloaded > _MAX_ARTIFACT_BYTES:
                    dest_path.unlink(missing_ok=True)
                    raise ValueError(
                        f"Artifact exceeds size limit of {_MAX_ARTIFACT_BYTES} bytes: {url}"
                    )
                f.write(chunk)
                sha256.update(chunk)

    if verify_checksum:
        expected = url_info.get("digests", {}).get("sha256", "")
        if expected:
            actual = sha256.hexdigest()
            if actual != expected:
                raise ValueError(
                    f"SHA-256 mismatch for {url}: expected {expected}, got {actual}"
                )
            logger.info("SHA-256 verified for %s", dest_path)
        else:
            logger.warning("No SHA-256 digest available for %s", url)

    logger.info("Downloaded artifact to %s (%d bytes)", dest_path, downloaded)
    return dest_path


def extract_project_urls(metadata: dict) -> dict[str, str]:
    """Extract project URLs from PyPI metadata."""
    info = metadata.get("info", {})
    urls = dict(info.get("project_urls") or {})
    home_page = info.get("home_page")
    if home_page and "Homepage" not in urls:
        urls["Homepage"] = home_page
    return urls


def extract_python_requires(metadata: dict) -> str:
    """Extract requires_python specifier from PyPI metadata."""
    return metadata.get("info", {}).get("requires_python") or ""


def extract_classifiers(metadata: dict) -> list[str]:
    """Extract classifier strings from PyPI metadata."""
    return metadata.get("info", {}).get("classifiers") or []
