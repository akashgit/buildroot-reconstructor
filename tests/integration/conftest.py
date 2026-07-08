"""Conftest for VPN-gated integration tests."""

from __future__ import annotations

import socket

import pytest


def _pnc_reachable() -> bool:
    try:
        sock = socket.create_connection(
            ("orch-stage.pnc.engineering.redhat.com", 443), timeout=3
        )
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False


def pytest_configure(config):
    config.addinivalue_line("markers", "vpn_required: requires Red Hat VPN")


def pytest_collection_modifyitems(config, items):
    if _pnc_reachable():
        return
    skip = pytest.mark.skip(reason="PNC staging not reachable (VPN required)")
    for item in items:
        if "vpn_required" in item.keywords:
            item.add_marker(skip)
