"""Offline testy parsowania modeli na kanonicznych JSON-ach z API Sejmu."""

from __future__ import annotations

from datetime import date, datetime

from sejm_process_mcp.models import (
    ProcessSummary,
    print_from_api,
    process_from_api,
)

TERM = 10


def test_summary_maps_api_aliases(fixture_json):
    raw = fixture_json("processes_list.json")[0]
    summary = process_from_api(raw, TERM)

    assert isinstance(summary, ProcessSummary)
    assert summary.number == raw["number"]
    assert summary.term == raw["term"] == TERM
    assert summary.title == raw["title"]
    assert summary.title_final == raw["titleFinal"]  # titleFinal -> title_final
    assert summary.document_type == raw["documentType"]
    assert summary.document_type_enum == raw["documentTypeEnum"]
    assert summary.process_start_date == date.fromisoformat(raw["processStartDate"])
    assert summary.eli == raw["ELI"]  # ELI -> eli
    assert summary.display_address == raw["displayAddress"]
    assert summary.source_url == f"https://api.sejm.gov.pl/sejm/term10/processes/{raw['number']}"
    assert summary.retrieved_at


def test_summary_links_keep_rel(fixture_json):
    raw = fixture_json("processes_list.json")[0]
    summary = process_from_api(raw, TERM)
    assert {link.rel for link in summary.links} >= {"isap", "eli", "eli-api"}
    assert all(link.href.startswith("http") for link in summary.links)


def test_summary_tolerates_missing_optional_fields():
    """`documentTypeEnum`, `closureDate`, `titleFinal` i `ELI` bywaja nieobecne (real: 195/500 rekordow)."""
    summary = process_from_api(
        {"number": "3", "term": 10, "title": "Kandydat na stanowisko", "processStartDate": "2023-11-13"},
        TERM,
    )
    assert summary.document_type_enum is None
    assert summary.title_final is None
    assert summary.eli is None
    assert summary.closure_date is None
    assert summary.passed is None


def test_summary_ignores_unknown_api_fields():
    summary = process_from_api(
        {"number": "1", "term": 10, "title": "T", "cosNowegoWAPI": {"a": 1}},
        TERM,
    )
    assert "cosNowegoWAPI" not in summary.model_dump()


def test_detail_extends_summary_with_stages(fixture_json):
    raw = fixture_json("process_32_detail.json")
    detail = process_from_api(raw, TERM, detail=True)

    assert detail.stages and len(detail.stages) > len(raw["stages"])
    assert detail.legislative_committee == raw["legislativeCommittee"]
    assert detail.principle_of_subsidiarity == raw["principleOfSubsidiarity"]
    assert detail.prints_considered_jointly == (raw.get("printsConsideredJointly") or [])
    # proces 32 jest zakonczony
    assert detail.passed is True
    assert detail.document_type_enum == "BILL"


def test_detail_serialises_to_json(fixture_json):
    detail = process_from_api(fixture_json("process_32_detail.json"), TERM, detail=True)
    dumped = detail.model_dump(mode="json")
    assert dumped["stages"][0]["stage_name"] == "Projekt wpłynął do Sejmu"
    assert isinstance(dumped["process_start_date"], str)


def test_print_parses_and_expands_attachments(fixture_json):
    raw = fixture_json("print_503.json")
    doc = print_from_api(raw, TERM)

    assert doc.number == "503"
    assert doc.term == TERM
    assert doc.title.startswith("Sprawozdanie Komisji")
    assert doc.document_date == date.fromisoformat(raw["documentDate"])
    assert doc.delivery_date == date.fromisoformat(raw["deliveryDate"])
    assert isinstance(doc.change_date, datetime)
    assert doc.process_print == raw["processPrint"]
    assert [a.file_name for a in doc.attachments] == raw["attachments"]
    assert doc.attachments[0].url == "https://api.sejm.gov.pl/sejm/term10/prints/503/503.pdf"
    assert doc.source_url == "https://api.sejm.gov.pl/sejm/term10/prints/503"


def test_print_without_attachments(fixture_json):
    raw = fixture_json("print_1.json")
    doc = print_from_api(raw, TERM)
    assert doc.attachments and doc.attachments[0].file_name == "1.pdf"
