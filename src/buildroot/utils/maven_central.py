"""HTTP client for Maven Central POM and JAR fetching."""

from __future__ import annotations

import hashlib
import io
import logging
import os
import shutil
import time
import zipfile
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

MAVEN_CENTRAL_BASE = os.environ.get(
    "MAVEN_MIRROR_URL",
    "https://repo1.maven.org/maven2",
)
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "buildroot" / "poms"
DEFAULT_JAR_CACHE_DIR = Path.home() / ".cache" / "buildroot" / "jars"
MAX_RETRIES = 5
BACKOFF_BASE = 2.0
_MAX_JAR_BYTES = 50 * 1024 * 1024  # 50 MB


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


def _jar_url(group_id: str, artifact_id: str, version: str) -> str:
    group_path = group_id.replace(".", "/")
    return f"{MAVEN_CENTRAL_BASE}/{group_path}/{artifact_id}/{version}/{artifact_id}-{version}.jar"


def _jar_cache_path(
    cache_dir: Path, group_id: str, artifact_id: str, version: str
) -> Path:
    """Return the cache path for a JAR, preserving Maven repository layout."""
    group_path = group_id.replace(".", "/")
    return (
        cache_dir
        / group_path
        / artifact_id
        / version
        / f"{artifact_id}-{version}.jar"
    )


def get_jar_path(
    group_id: str,
    artifact_id: str,
    version: str,
    *,
    cache_dir: Path | None = None,
    verify_checksum: bool = True,
) -> Path:
    """Return path to a cached JAR, downloading from Maven Central if needed.

    The JAR is stored under ``cache_dir`` using standard Maven layout:
    ``{group_path}/{artifact_id}/{version}/{artifact_id}-{version}.jar``

    On download the SHA-1 checksum published alongside the JAR is verified
    when *verify_checksum* is True and the checksum file is available.

    Returns the local filesystem path to the cached JAR.
    Raises requests.HTTPError on non-retryable download failure.
    Raises ValueError if the JAR exceeds the size limit or checksum fails.
    """
    cache = cache_dir or DEFAULT_JAR_CACHE_DIR
    cached_path = _jar_cache_path(cache, group_id, artifact_id, version)

    if cached_path.exists():
        logger.debug(
            "JAR cache hit for %s:%s:%s at %s",
            group_id, artifact_id, version, cached_path,
        )
        return cached_path

    url = _jar_url(group_id, artifact_id, version)
    logger.info("Downloading JAR from %s", url)

    cached_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cached_path.with_suffix(".jar.tmp")

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with requests.get(url, timeout=120, stream=True) as resp:
                if resp.status_code == 429:
                    wait = BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "429 rate-limited, retry %d/%d for %s (%.1fs backoff)",
                        attempt + 1, MAX_RETRIES, url, wait,
                    )
                    time.sleep(wait)
                    last_exc = requests.HTTPError(response=resp)
                    continue
                resp.raise_for_status()

                sha1 = hashlib.sha1()  # noqa: S324
                downloaded = 0
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        downloaded += len(chunk)
                        if downloaded > _MAX_JAR_BYTES:
                            tmp_path.unlink(missing_ok=True)
                            raise ValueError(
                                f"JAR exceeds size limit of {_MAX_JAR_BYTES} bytes: {url}"
                            )
                        f.write(chunk)
                        sha1.update(chunk)

            # Download succeeded — break out of retry loop
            break

        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            wait = BACKOFF_BASE * (2 ** attempt)
            logger.warning(
                "Retry %d/%d for %s (%.1fs backoff): %s",
                attempt + 1, MAX_RETRIES, url, wait, exc,
            )
            time.sleep(wait)
            continue
        except requests.HTTPError:
            tmp_path.unlink(missing_ok=True)
            raise
    else:
        # All retries exhausted
        tmp_path.unlink(missing_ok=True)
        raise last_exc  # type: ignore[misc]

    # Optional SHA-1 verification
    if verify_checksum:
        sha1_url = url + ".sha1"
        try:
            sha1_text = _fetch_with_retry(sha1_url)
            expected = sha1_text.strip().split()[0]
            actual = sha1.hexdigest()
            if actual != expected:
                tmp_path.unlink(missing_ok=True)
                raise ValueError(
                    f"SHA-1 mismatch for {url}: expected {expected}, got {actual}"
                )
            logger.info("SHA-1 verified for %s", cached_path)
        except requests.RequestException:
            logger.warning("Could not verify SHA-1 checksum for %s", url)

    # Atomic rename into cache
    tmp_path.rename(cached_path)
    logger.info("Cached JAR at %s (%d bytes)", cached_path, downloaded)
    return cached_path


def fetch_jar_manifest_jdk(
    group_id: str, artifact_id: str, version: str
) -> str:
    """Download the published JAR and read Build-Jdk-Spec from MANIFEST.MF.

    Returns the JDK version string, or empty string if not found.
    """
    try:
        jar_path = get_jar_path(
            group_id, artifact_id, version, verify_checksum=False,
        )
    except (requests.RequestException, ValueError):
        jar_url = _jar_url(group_id, artifact_id, version)
        logger.warning("Could not fetch JAR from %s", jar_url)
        return ""

    try:
        with zipfile.ZipFile(jar_path) as zf:
            manifest_path = "META-INF/MANIFEST.MF"
            if manifest_path not in zf.namelist():
                return ""
            manifest = zf.read(manifest_path).decode("utf-8", errors="replace")
            for line in manifest.splitlines():
                if line.startswith("Build-Jdk-Spec:"):
                    return line.split(":", 1)[1].strip()
                if line.startswith("Build-Jdk:"):
                    raw = line.split(":", 1)[1].strip()
                    parts = raw.split(".")
                    if parts[0] == "1" and len(parts) >= 2:
                        return parts[1]
                    return parts[0]
    except (zipfile.BadZipFile, KeyError):
        logger.warning(
            "Could not read manifest from JAR at %s",
            _jar_url(group_id, artifact_id, version),
        )
    return ""


def download_jar(
    group_id: str,
    artifact_id: str,
    version: str,
    dest_path: Path,
    *,
    verify_checksum: bool = True,
) -> Path:
    """Download a JAR from Maven Central and optionally verify its SHA-1 checksum.

    Returns the path to the downloaded JAR.
    Raises requests.HTTPError on download failure.
    Raises ValueError if checksum verification fails.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    cached = get_jar_path(
        group_id, artifact_id, version, verify_checksum=verify_checksum,
    )

    # Copy from cache to the caller's requested destination
    shutil.copy2(cached, dest_path)
    logger.info("Copied cached JAR to %s", dest_path)
    return dest_path


def _fetch_with_retry(url: str) -> str:
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 429:
                wait = BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "429 rate-limited, retry %d/%d for %s (%.1fs backoff)",
                    attempt + 1, MAX_RETRIES, url, wait,
                )
                time.sleep(wait)
                last_exc = requests.HTTPError(response=resp)
                continue
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
