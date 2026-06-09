"""HTTP client for Maven Central POM and JAR fetching."""

from __future__ import annotations

import hashlib
import io
import logging
import time
import zipfile
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

MAVEN_CENTRAL_BASE = "https://repo1.maven.org/maven2"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "buildroot" / "poms"
MAX_RETRIES = 3
BACKOFF_BASE = 1.0
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


def fetch_jar_manifest_jdk(
    group_id: str, artifact_id: str, version: str
) -> str:
    """Download the published JAR and read Build-Jdk-Spec from MANIFEST.MF.

    Returns the JDK version string, or empty string if not found.
    """
    group_path = group_id.replace(".", "/")
    jar_url = (
        f"{MAVEN_CENTRAL_BASE}/{group_path}/{artifact_id}"
        f"/{version}/{artifact_id}-{version}.jar"
    )
    try:
        resp = requests.get(jar_url, timeout=30, stream=True)
        resp.raise_for_status()
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > _MAX_JAR_BYTES:
            logger.warning("JAR too large (%s bytes), skipping %s", content_length, jar_url)
            resp.close()
            return ""
        chunks = []
        downloaded = 0
        for chunk in resp.iter_content(chunk_size=8192):
            downloaded += len(chunk)
            if downloaded > _MAX_JAR_BYTES:
                logger.warning("JAR exceeded %d bytes during download, skipping %s", _MAX_JAR_BYTES, jar_url)
                resp.close()
                return ""
            chunks.append(chunk)
        resp.close()
    except requests.RequestException:
        logger.warning("Could not fetch JAR from %s", jar_url)
        return ""

    try:
        jar_bytes = io.BytesIO(b"".join(chunks))
        with zipfile.ZipFile(jar_bytes) as zf:
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
        logger.warning("Could not read manifest from JAR at %s", jar_url)
    return ""


def _jar_url(group_id: str, artifact_id: str, version: str) -> str:
    group_path = group_id.replace(".", "/")
    return f"{MAVEN_CENTRAL_BASE}/{group_path}/{artifact_id}/{version}/{artifact_id}-{version}.jar"


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
    url = _jar_url(group_id, artifact_id, version)
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Downloading JAR from %s", url)
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()

    sha1 = hashlib.sha1()  # noqa: S324
    downloaded = 0
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            downloaded += len(chunk)
            if downloaded > _MAX_JAR_BYTES:
                dest_path.unlink(missing_ok=True)
                raise ValueError(
                    f"JAR exceeds size limit of {_MAX_JAR_BYTES} bytes: {url}"
                )
            f.write(chunk)
            sha1.update(chunk)
    resp.close()

    if verify_checksum:
        sha1_url = url + ".sha1"
        try:
            sha1_resp = requests.get(sha1_url, timeout=30)
            sha1_resp.raise_for_status()
            expected = sha1_resp.text.strip().split()[0]
            actual = sha1.hexdigest()
            if actual != expected:
                raise ValueError(
                    f"SHA-1 mismatch for {url}: expected {expected}, got {actual}"
                )
            logger.info("SHA-1 verified for %s", dest_path)
        except requests.RequestException:
            logger.warning("Could not verify SHA-1 checksum for %s", url)

    logger.info("Downloaded JAR to %s (%d bytes)", dest_path, downloaded)
    return dest_path


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
