"""Smoke testy online - hit live api.sejm.gov.pl.

Uruchamia sie jawnie (nie wchodza w domyslny `pytest`):
    pytest -m smoke -v

Te testy moga byc flaky jezeli:
- API Sejmu zmieni ksztalt JSON -> modele w `models.py` wymagaja update
- API jest down / pod load
- brak sieci

W razie failure - PIERWSZE: odswiez fixture'y i uruchom testy offline; jesli
offline tez padaja, API zmienilo kontrakt i trzeba poprawic aliasy w `models.py`.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.smoke


@pytest.mark.asyncio
async def test_smoke_search_drafts_returns_records():
    """search_drafts(term 10) zwraca rekordy z numerem i tytulem."""
    from sejm_process_mcp.server import search_drafts

    result = await search_drafts(term="10", limit=10)

    assert result["fetched"] > 0, "API Sejmu zwrocilo pusta liste procesow"
    assert result["items"], "filtry nie byly podane, wiec lista nie moze byc pusta"
    first = result["items"][0]
    assert first["number"]
    assert first["title"]
    assert first["source_url"].endswith(f"/processes/{first['number']}")


@pytest.mark.asyncio
async def test_smoke_search_drafts_query_filters():
    """Filtr `query` dziala na zywej stronie z API."""
    from sejm_process_mcp.server import search_drafts

    result = await search_drafts(term="10", query="ustawy", limit=50)
    assert result["count"] <= result["fetched"]
    for item in result["items"]:
        haystack = f"{item['title']} {item.get('title_final') or ''}".casefold()
        assert "ustawy" in haystack


@pytest.mark.asyncio
async def test_smoke_get_process_flattens_live_stages():
    """get_process na numerze odkrytym z listy zwraca niepusta os czasu."""
    from sejm_process_mcp.server import get_process, search_drafts

    listing = await search_drafts(term="10", limit=50)
    number = listing["items"][0]["number"]

    detail = await get_process(term="10", number=number)

    assert detail["number"] == number
    assert detail["stages"], "proces bez etapow - parser stages[] broken"
    assert detail["stages"][0]["stage_name"]
    assert all("depth" in stage for stage in detail["stages"])
    # os czasu jest uporzadkowana: etapy nadrzedne maja depth 0
    assert detail["stages"][0]["depth"] == 0


@pytest.mark.asyncio
async def test_smoke_get_print_returns_attachment_urls():
    """get_print zwraca druk i URL-e zalacznikow."""
    from sejm_process_mcp.server import get_print

    doc = await get_print(term="10", number="503")

    assert doc["number"] == "503"
    assert doc["title"]
    assert doc["attachments"], "druk 503 ma zalaczniki"
    assert doc["attachments"][0]["url"].startswith("https://api.sejm.gov.pl/sejm/term10/prints/503/")


@pytest.mark.asyncio
async def test_smoke_unknown_number_is_not_found():
    """Nieznany numer w tej kadencji -> structured not_found, nie puste body."""
    from sejm_process_mcp.server import SejmProcessError, get_process

    with pytest.raises(SejmProcessError) as exc:
        await get_process(term="10", number="999999")
    assert exc.value.code == "not_found"
