"""Wspolna konfiguracja testow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_audit_log(tmp_path, monkeypatch):
    """Testy nie dopisuja do produkcyjnego audit logu."""
    monkeypatch.setenv("SEJM_PROCESS_MCP_AUDIT_DIR", str(tmp_path / "audit"))


@pytest.fixture
def fixture_json():
    """Wczytuje kanoniczny JSON z `tests/fixtures`."""

    def _load(name: str):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return _load
