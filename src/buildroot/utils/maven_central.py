"""HTTP client for Maven Central POM and JAR fetching."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
import zipfile
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

GOOGLE_MIRROR_BASE = "https://maven-central.storage-download.googleapis.com/maven2"
MAVEN_CENTRAL_DIRECT = "https://repo1.maven.org/maven2"
_mirror_env = os.environ.get("MAVEN_MIRROR_URL", "").rstrip("/")
MAVEN_CENTRAL_BASE = _mirror_env or GOOGLE_MIRROR_BASE
FALLBACK_BASE = MAVEN_CENTRAL_DIRECT if MAVEN_CENTRAL_BASE == GOOGLE_MIRROR_BASE else GOOGLE_MIRROR_BASE
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "buildroot" / "poms"
DEFAULT_JAR_CACHE_DIR = Path.home() / ".cache" / "buildroot" / "jars"
MAX_RETRIES = 5
BACKOFF_BASE = 2.0
_MAX_JAR_BYTES = 50 * 1024 * 1024  # 50 MB

_fallback_enabled = True


def _cache_key(group_id: str, artifact_id: str, version: str) -> str:
    gav = f"{group_id}:{artifact_id}:{version}"
    return hashlib.sha256(gav.encode()).hexdigest()


def _pom_url(group_id: str, artifact_id: str, version: str) -> str:
    group_path = group_id.replace(".", "/")
    return f"{MAVEN_CENTRAL_BASE}/{group_path}/{artifact_id}/{version}/{artifact_id}-{version}.pom"


def fetch_latest_version(group_id: str, artifact_id: str) -> str | None:
    """Fetch the latest release version from Maven Central metadata.

    Returns the version string, or None if unavailable.
    """
    group_path = group_id.replace(".", "/")
    url = f"{MAVEN_CENTRAL_BASE}/{group_path}/{artifact_id}/maven-metadata.xml"
    try:
        xml_text = _fetch_with_retry(url)
        import re
        release = re.search(r"<release>([^<]+)</release>", xml_text)
        if release:
            return release.group(1)
        latest = re.search(r"<latest>([^<]+)</latest>", xml_text)
        if latest:
            return latest.group(1)
    except Exception as e:
        logger.warning("Could not fetch latest version for %s:%s: %s", group_id, artifact_id, e)
    return None


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
    tmp_path = cached_path.with_suffix(f".{os.getpid()}.jar.tmp")

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with requests.get(url, timeout=120, stream=True) as resp:
                if resp.status_code == 429:
                    if _fallback_enabled and MAVEN_CENTRAL_BASE in url:
                        mirror_url = url.replace(MAVEN_CENTRAL_BASE, FALLBACK_BASE)
                        logger.info("429 on JAR download, trying fallback: %s", mirror_url)
                        url = mirror_url
                        continue
                    wait = BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "429 rate-limited, retry %d/%d for %s (%.1fs backoff)",
                        attempt + 1, MAX_RETRIES, url, wait,
                    )
                    time.sleep(wait)
                    last_exc = requests.HTTPError(response=resp)
                    continue
                resp.raise_for_status()

                sha1 = hashlib.sha1() if verify_checksum else None  # noqa: S324
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
                        if sha1 is not None:
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
        except requests.HTTPError as exc:
            tmp_path.unlink(missing_ok=True)
            if exc.response is not None and exc.response.status_code == 404:
                resolved = resolve_canonical_coordinate(group_id, artifact_id, version)
                if resolved:
                    canonical_g, canonical_a = resolved
                    return get_jar_path(
                        canonical_g, canonical_a, version,
                        cache_dir=cache_dir, verify_checksum=verify_checksum,
                    )
            raise
    else:
        # All retries exhausted
        tmp_path.unlink(missing_ok=True)
        raise last_exc  # type: ignore[misc]

    _MIN_JAR_BYTES = 1024
    if downloaded < _MIN_JAR_BYTES:
        tmp_path.unlink(missing_ok=True)
        raise ValueError(f"Downloaded file too small ({downloaded} bytes), not a valid JAR: {url}")
    try:
        with zipfile.ZipFile(tmp_path) as zf:
            _ = zf.namelist()
    except (zipfile.BadZipFile, OSError):
        tmp_path.unlink(missing_ok=True)
        raise ValueError(f"Downloaded file is not a valid JAR/ZIP ({downloaded} bytes): {url}")

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
        except requests.RequestException as e:
            logger.warning("Could not verify SHA-1 checksum for %s: %s", url, e)

    # Atomic rename into cache
    os.replace(tmp_path, cached_path)
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


MAVEN_SEARCH_BASE = "https://search.maven.org/solrsearch/select"


def resolve_canonical_coordinate(
    group_id: str, artifact_id: str, version: str,
) -> tuple[str, str] | None:
    """Search Maven Central for the canonical coordinate when the fork coordinate 404s.

    Returns (canonical_group_id, canonical_artifact_id) if found, else None.
    """
    try:
        resp = requests.get(
            MAVEN_SEARCH_BASE,
            params={"q": f'a:"{artifact_id}" AND v:"{version}"', "rows": 10, "wt": "json"},
            timeout=15,
        )
        resp.raise_for_status()
        docs = resp.json().get("response", {}).get("docs", [])
        for doc in docs:
            g, a = doc.get("g", ""), doc.get("a", "")
            if a == artifact_id and g and g != group_id:
                logger.info(
                    "Resolved canonical coordinate: %s:%s:%s → %s:%s:%s",
                    group_id, artifact_id, version, g, a, version,
                )
                return (g, a)

        if not docs:
            resp2 = requests.get(
                MAVEN_SEARCH_BASE,
                params={"q": f'a:"{artifact_id}"', "rows": 20, "wt": "json"},
                timeout=15,
            )
            resp2.raise_for_status()
            candidates = resp2.json().get("response", {}).get("docs", [])
            for doc in candidates:
                g, a = doc.get("g", ""), doc.get("a", "")
                if a == artifact_id and g and g != group_id:
                    jar_url = _jar_url(g, a, version)
                    check = requests.head(jar_url, timeout=10, allow_redirects=True)
                    if check.status_code == 200:
                        logger.info(
                            "Resolved canonical coordinate (version probe): %s:%s:%s → %s:%s:%s",
                            group_id, artifact_id, version, g, a, version,
                        )
                        return (g, a)
    except Exception as e:
        logger.debug("Canonical coordinate resolution failed: %s", e)

    return None


def _try_fallback(url: str) -> str | None:
    """Try fetching from fallback mirror if enabled."""
    if not _fallback_enabled:
        return None
    if MAVEN_CENTRAL_BASE not in url:
        return None
    mirror_url = url.replace(MAVEN_CENTRAL_BASE, FALLBACK_BASE)
    try:
        logger.info("Trying fallback mirror: %s", mirror_url)
        resp = requests.get(mirror_url, timeout=30)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        logger.warning("Fallback mirror failed: %s", e)
        return None


def _fetch_with_retry(url: str) -> str:
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 429:
                mirror_result = _try_fallback(url)
                if mirror_result is not None:
                    return mirror_result
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
