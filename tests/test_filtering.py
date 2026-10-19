"""Offline unit testy filtrowania klienta w `search_drafts`.

API Sejmu nie ma wyszukiwania server-side - caly filtr zyje w `filter_drafts`,
wiec to jedyne miejsce, gdzie moze sie cicho zepsuc.
"""

from __future__ import annotations

from datetime import date

from sejm_process_mcp.models import filter_drafts, process_from_api

TERM = 10


def _items(fixture_json):
    return [process_from_api(raw, TERM) for raw in fixture_json("processes_list.json")]


def test_query_matches_title_case_insensitively(fixture_json):
    items = _items(fixture_json)
    hit = filter_drafts(items, query="EMERYTURACH")
    assert [i.number for i in hit] == ["32"]


def test_query_matches_title_final(fixture_json):
    """`titleFinal` bywa inny niz `title` - fraza trafia w oba pola."""
    items = _items(fixture_json)
    assert items[0].title_final, "fixture musi miec titleFinal, inaczej test jest pusty"
    phrase = items[0].title_final.split()[-1]
    hit = filter_drafts(items, query=phrase)
    assert "1" in [i.number for i in hit]


def test_query_without_match_returns_empty(fixture_json):
    assert filter_drafts(_items(fixture_json), query="nie ma takiej ustawy") == []


def test_date_range_filters_on_process_start_date(fixture_json):
    items = _items(fixture_json)
    # Proces 32 wplynal 2023-04-11, pozostale 2023-11-13.
    early = filter_drafts(items, date_to=date(2023, 6, 1))
    assert [i.number for i in early] == ["32"]

    late = filter_drafts(items, date_from=date(2023, 6, 1))
    assert sorted(i.number for i in late) == ["1", "2", "3"]

    assert filter_drafts(items, date_from=date(2024, 1, 1)) == []


def test_date_range_drops_records_without_a_date():
    """Brak `process_start_date` + podany zakres = rekord wypada (nie falszywy traf)."""
    item = process_from_api(
        {"number": "9", "term": TERM, "title": "Bez daty", "processStartDate": None},
        TERM,
    )
    assert item.process_start_date is None
    assert filter_drafts([item], date_from=date(2020, 1, 1)) == []


def test_document_type_matches_polish_name_and_enum(fixture_json):
    items = _items(fixture_json)
    assert sorted(i.number for i in filter_drafts(items, document_type="ustawy")) == ["32"]
    assert sorted(i.number for i in filter_drafts(items, document_type="BILL")) == ["32"]
    assert sorted(i.number for i in filter_drafts(items, document_type="draft_resolution")) == ["1", "2"]


def test_filters_compose(fixture_json):
    items = _items(fixture_json)
    hit = filter_drafts(
        items,
        query="obywatelski",
        date_from=date(2023, 1, 1),
        date_to=date(2023, 12, 31),
        document_type="BILL",
    )
    assert [i.number for i in hit] == ["32"]


def test_no_filters_returns_everything(fixture_json):
    items = _items(fixture_json)
    assert filter_drafts(items) == items
