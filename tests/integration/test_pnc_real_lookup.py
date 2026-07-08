"""Integration tests for real PNC API lookups (VPN required)."""

from __future__ import annotations

import pytest

from buildroot.utils.pnc_api import PncClient


@pytest.mark.vpn_required
class TestRealPncLookup:
    def test_real_pnc_lookup_commons_lang3(self, tmp_path):
        client = PncClient(cache_dir=tmp_path / "cache")
        info = client.query_by_gav(
            "org.apache.commons", "commons-lang3", "3.12.0.redhat-00001"
        )
        if info is not None:
            assert info.build_id
            assert info.builder_image
            assert "quay.io" in info.builder_image

    def test_real_pnc_lookup_jackson_annotations(self, tmp_path):
        client = PncClient(cache_dir=tmp_path / "cache")
        info = client.query_by_gav(
            "com.fasterxml.jackson.core",
            "jackson-annotations",
            "2.9.9.redhat-00001",
        )
        if info is not None:
            assert info.build_id
            assert info.scm_external_url

    def test_real_pnc_lookup_not_found(self, tmp_path):
        client = PncClient(cache_dir=tmp_path / "cache")
        info = client.query_by_gav(
            "com.nonexistent",
            "nonexistent-artifact",
            "99.99.99",
        )
        assert info is None
