"""Testy serwera: powierzchnia toolow (fastmcp Client) + przeplywy offline.

Zadne z tych testow nie wychodzi do sieci - `SejmProcessClient` jest podmieniany,
a `sejm_coverage` nie dotyka API wcale.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastmcp import Client

from sejm_process_mcp.client import SejmProcessClient
from sejm_process_mcp.server import (
    INSTRUCTIONS,
    SejmProcessError,
    get_print,
    get_process,
    mcp,
    search_drafts,
    sejm_coverage,
)

EXPECTED_TOOLS = {"search_drafts", "get_process", "get_print", "sejm_coverage"}


def _fn(tool):
    """fastmcp 3 owinien tool w FunctionTool - `fn` to oryginalna coroutine."""
    return getattr(tool, "fn", tool)


def _run(tool, **kwargs):
    return asyncio.run(_fn(tool)(**kwargs))


def _audit_lines(tmp_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for f in tmp_path.rglob("*.jsonl")
        for line in f.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------- powierzchnia toolow ----------


@pytest.mark.asyncio
async def test_tool_surface_is_exactly_the_four_tools():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_all_tools_are_marked_read_only():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} bez adnotacji"
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False


@pytest.mark.asyncio
async def test_every_tool_is_documented_in_the_instructions():
    """INSTRUCTIONS to system prompt klienta - tool poza nim jest dla LLM niewidoczny."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert tool.name in INSTRUCTIONS, f"{tool.name} nie wystepuje w INSTRUCTIONS"


@pytest.mark.asyncio
async def test_coverage_tool_returns_non_empty_gaps():
    result = await _fn(sejm_coverage)()
    assert result.status == "ok"
    assert result.families
    assert result.known_gaps
    assert all(g.fallback for g in result.known_gaps)


@pytest.mark.asyncio
async def test_coverage_over_the_mcp_client(tmp_path):
    async with Client(mcp) as client:
        result = await client.call_tool("sejm_coverage", {})
    payload = result.structured_content or result.data
    assert payload["known_gaps"]
    assert any(entry["tool"] == "sejm_coverage" for entry in _audit_lines(tmp_path))


# ---------- przeplywy narzedzi (offline, klient podmieniony) ----------


def test_search_drafts_filters_page_and_logs_audit(fixture_json, monkeypatch, tmp_path):
    raw = fixture_json("processes_list.json")

    async def fake_list(self, term, limit=50, offset=0):
        return raw, f"https://api.sejm.gov.pl/sejm/term{term}/processes?limit={limit}&offset={offset}"

    monkeypatch.setattr(SejmProcessClient, "list_processes", fake_list)

    result = _run(search_drafts, term="10", query="ustawy", document_type="BILL")

    assert result["term"] == 10
    assert result["fetched"] == len(raw)
    assert result["count"] == 1
    assert result["items"][0]["number"] == "32"
    assert result["items"][0]["source_url"].endswith("/processes/32")
    assert "limit=50" in result["source_url"]

    lines = _audit_lines(tmp_path)
    assert lines and lines[-1]["tool"] == "search_drafts"
    assert lines[-1]["result_summary"] == {"fetched": 4, "count": 1}
    assert lines[-1]["source_urls"]


def test_get_process_returns_flat_timeline(fixture_json, monkeypatch):
    raw = fixture_json("process_32_detail.json")

    async def fake_get(self, term, number):
        return raw, f"https://api.sejm.gov.pl/sejm/term{term}/processes/{number}"

    monkeypatch.setattr(SejmProcessClient, "get_process", fake_get)

    result = _run(get_process, term="10", number="32")

    assert result["number"] == "32"
    stage_names = [s["stage_name"] for s in result["stages"]]
    assert stage_names[0] == "Projekt wpłynął do Sejmu"
    assert stage_names[-1] == "Uchwalono"
    voting = next(s for s in result["stages"] if s["stage_type"] == "Voting")
    assert voting["parent_stage"] == "III czytanie na posiedzeniu Sejmu"
    assert voting["voting"]["yes"] is not None
    assert "not_participating" in voting["voting"]


def test_get_print_expands_attachments(fixture_json, monkeypatch, tmp_path):
    raw = fixture_json("print_503.json")

    async def fake_get(self, term, number):
        return raw, f"https://api.sejm.gov.pl/sejm/term{term}/prints/{number}"

    monkeypatch.setattr(SejmProcessClient, "get_print", fake_get)

    result = _run(get_print, term="10", number="503")

    assert result["number"] == "503"
    assert [a["file_name"] for a in result["attachments"]] == ["503.pdf", "V7_481-78.NK.docx"]
    assert result["attachments"][1]["url"].endswith("/prints/503/V7_481-78.NK.docx")
    assert any(entry["tool"] == "get_print" for entry in _audit_lines(tmp_path))


# ---------- walidacja i kody bledow ----------


def test_missing_number_is_a_structured_error():
    with pytest.raises(SejmProcessError) as exc:
        _run(get_process, term="10", number="")
    assert exc.value.code == "missing_arg"
    assert str(exc.value).startswith("[missing_arg]")


def test_invalid_term_is_a_structured_error():
    with pytest.raises(SejmProcessError) as exc:
        _run(search_drafts, term="dziesiec")
    assert exc.value.code == "invalid_arg"


def test_term_accepts_the_term_prefix():
    """`term="term10"` tez ma dzialac - tak wyglada segment sciezki API."""
    from sejm_process_mcp.server import _parse_term

    assert _parse_term("term10") == 10
    assert _parse_term(" 9 ") == 9


def test_limit_and_offset_are_range_checked():
    with pytest.raises(SejmProcessError) as exc:
        _run(search_drafts, limit=1000)
    assert exc.value.code == "invalid_arg"

    with pytest.raises(SejmProcessError) as exc:
        _run(search_drafts, offset=-1)
    assert exc.value.code == "invalid_arg"


def test_date_range_is_validated():
    with pytest.raises(SejmProcessError) as exc:
        _run(search_drafts, date_from="2024-01-01", date_to="2023-01-01")
    assert exc.value.code == "invalid_arg"

    with pytest.raises(SejmProcessError) as exc:
        _run(search_drafts, date_from="01.01.2024")
    assert exc.value.code == "invalid_arg"


def test_404_maps_to_not_found(monkeypatch):
    async def fake_get(self, term, number):
        request = httpx.Request("GET", f"https://api.sejm.gov.pl/sejm/term{term}/processes/{number}")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("404", request=request, response=response)

    monkeypatch.setattr(SejmProcessClient, "get_process", fake_get)

    with pytest.raises(SejmProcessError) as exc:
        _run(get_process, term="10", number="999999")
    assert exc.value.code == "not_found"


def test_network_failure_maps_to_upstream_error(monkeypatch):
    async def fake_get(self, term, number):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(SejmProcessClient, "get_process", fake_get)

    with pytest.raises(SejmProcessError) as exc:
        _run(get_process, term="10", number="32")
    assert exc.value.code == "upstream_error"
