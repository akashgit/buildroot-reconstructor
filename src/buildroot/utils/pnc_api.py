"""PNC (Project Newcastle) API client for build environment lookups."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

PNC_API_URL = os.environ.get(
    "PNC_API_URL",
    "https://orch-stage.pnc.engineering.redhat.com/pnc-rest/v2",
)
PNC_TLS_VERIFY = os.environ.get("PNC_TLS_VERIFY", "true").lower() not in ("false", "0", "no")
PNC_CACHE_DIR = Path(os.environ.get("PNC_CACHE_DIR", str(Path.home() / ".cache" / "buildroot" / "pnc")))

CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days

_IMAGE_NAME_RE = re.compile(
    r"builder-rhel-(?P<rhel>\d+)-j(?P<jdk>\d+)-(?:mvn(?P<mvn>[\d.]+)|gradle(?P<gradle>[\d.]+))"
)


@dataclass
class PncBuildInfo:
    """Parsed PNC build environment information."""

    build_id: str = ""
    builder_image: str = ""
    jdk_version: str | None = None
    maven_version: str | None = None
    gradle_version: str | None = None
    rhel_version: str | None = None
    scm_url: str | None = None
    scm_tag: str | None = None
    scm_external_url: str | None = None
    scm_revision: str | None = None
    environment_id: str | None = None
    raw_response: dict = field(default_factory=dict)


class PncClient:
    """Client for the PNC REST API v2."""

    def __init__(
        self,
        *,
        base_url: str = "",
        tls_verify: bool | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._base_url = (base_url or PNC_API_URL).rstrip("/")
        self._verify = tls_verify if tls_verify is not None else PNC_TLS_VERIFY
        self._cache_dir = cache_dir or PNC_CACHE_DIR

        retry = Retry(
            total=5,
            backoff_factor=1.0,
            backoff_jitter=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._session.mount("http://", HTTPAdapter(max_retries=retry))

        if not self._verify:
            logger.info("PNC TLS verification disabled")

    def query_by_sha256(self, sha256: str) -> PncBuildInfo | None:
        cache_key = f"sha256-{sha256}"
        cached = self._read_cache(cache_key)
        if cached is not None:
            logger.info("PNC cache hit for sha256=%s", sha256[:16])
            return self._parse_response(cached)

        url = f"{self._base_url}/artifacts"
        params = {"sha256": sha256}
        logger.info("PNC API lookup by sha256=%s", sha256[:16])

        data = self._get(url, params)
        if data is None:
            return None

        self._write_cache(cache_key, data)
        return self._parse_response(data)

    def query_by_gav(
        self, group_id: str, artifact_id: str, version: str
    ) -> PncBuildInfo | None:
        identifier = f"maven:{group_id}:{artifact_id}:{version}"
        cache_key = f"gav-{hashlib.sha256(identifier.encode()).hexdigest()}"
        cached = self._read_cache(cache_key)
        if cached is not None:
            logger.info("PNC cache hit for %s:%s:%s", group_id, artifact_id, version)
            return self._parse_response(cached)

        url = f"{self._base_url}/artifacts"
        params = {"identifier": identifier}
        logger.info("PNC API lookup by GAV %s:%s:%s", group_id, artifact_id, version)

        data = self._get(url, params)
        if data is None:
            return None

        self._write_cache(cache_key, data)
        return self._parse_response(data)

    def _get(self, url: str, params: dict) -> dict | None:
        try:
            resp = self._session.get(url, params=params, timeout=30, verify=self._verify)
            if resp.status_code >= 400:
                logger.warning("PNC API returned %d for %s", resp.status_code, url)
                return None
            return resp.json()
        except requests.ConnectionError as e:
            logger.warning("PNC connection error (VPN required?): %s", e)
            return None
        except requests.Timeout as e:
            logger.warning("PNC request timed out: %s", e)
            return None
        except requests.RequestException as e:
            logger.warning("PNC request failed: %s", e)
            return None
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("PNC response parse error: %s", e)
            return None

    def _parse_response(self, data: dict) -> PncBuildInfo | None:
        content = data.get("content", [])
        if not content:
            return None

        for item in content:
            build = item.get("build")
            if not build:
                continue

            builder_image = extract_builder_image(data)
            scm_info = extract_scm_info(data)

            jdk_version = None
            maven_version = None
            gradle_version = None
            rhel_version = None
            if builder_image:
                parsed = parse_image_name_versions(builder_image)
                jdk_version = parsed.get("jdk")
                maven_version = parsed.get("maven")
                gradle_version = parsed.get("gradle")
                rhel_version = parsed.get("rhel")

            env = build.get("environment", {})

            info = PncBuildInfo(
                build_id=str(build.get("id", "")),
                builder_image=builder_image or "",
                jdk_version=jdk_version,
                maven_version=maven_version,
                gradle_version=gradle_version,
                rhel_version=rhel_version,
                scm_url=scm_info.get("scm_url") if scm_info else None,
                scm_tag=scm_info.get("scm_tag") if scm_info else None,
                scm_external_url=scm_info.get("scm_external_url") if scm_info else None,
                scm_revision=scm_info.get("scm_revision") if scm_info else None,
                environment_id=str(env.get("id", "")) if env else None,
                raw_response=data,
            )
            return info

        return None

    def _read_cache(self, key: str) -> dict | None:
        path = self._cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            age = time.time() - path.stat().st_mtime
            if age > CACHE_TTL_SECONDS:
                logger.debug("PNC cache expired for %s (age=%.0fs)", key, age)
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_cache(self, key: str, data: dict) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._cache_dir / f"{key}.json"
            path.write_text(json.dumps(data), encoding="utf-8")
        except OSError as e:
            logger.debug("PNC cache write failed: %s", e)


def extract_builder_image(response: dict) -> str | None:
    content = response.get("content", [])
    for item in content:
        build = item.get("build")
        if not build:
            continue
        env = build.get("environment", {})
        repo_url = env.get("systemImageRepositoryUrl", "")
        attrs = env.get("attributes", {})
        digest_ref = attrs.get("IMAGE_DIGEST_REF", "")
        if repo_url and digest_ref:
            repo_url = repo_url.rstrip("/")
            return f"{repo_url}/{digest_ref}" if "@" in digest_ref else f"{repo_url}/{digest_ref}"
    return None


def extract_scm_info(response: dict) -> dict | None:
    content = response.get("content", [])
    for item in content:
        build = item.get("build")
        if not build:
            continue

        result = {}
        scm_repo = build.get("scmRepository", {})
        if scm_repo:
            result["scm_external_url"] = scm_repo.get("externalUrl")

        build_config_rev = build.get("buildConfigRevision", {})
        if build_config_rev:
            result["scm_revision"] = build_config_rev.get("scmRevision")

        result["scm_url"] = build.get("scmUrl")
        result["scm_tag"] = build.get("scmTag")

        if any(v for v in result.values()):
            return result
    return None


def parse_image_name_versions(image_ref: str) -> dict[str, str | None]:
    m = _IMAGE_NAME_RE.search(image_ref)
    if not m:
        return {"jdk": None, "maven": None, "gradle": None, "rhel": None}
    return {
        "jdk": m.group("jdk"),
        "maven": m.group("mvn"),
        "gradle": m.group("gradle"),
        "rhel": m.group("rhel"),
    }
