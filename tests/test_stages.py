"""Offline testy splaszczania drzewa `stages[]` do osi czasu."""

from __future__ import annotations

from datetime import date

from sejm_process_mcp.models import flatten_stages, process_from_api

TERM = 10


def _detail(fixture_json):
    return process_from_api(fixture_json("process_32_detail.json"), TERM, detail=True)


def test_flattens_the_whole_tree_without_losing_stages(fixture_json):
    raw = fixture_json("process_32_detail.json")
    detail = _detail(fixture_json)

    raw_count = 0

    def count(nodes):
        nonlocal raw_count
        for node in nodes:
            raw_count += 1
            count(node.get("children") or [])

    count(raw["stages"])
    assert len(detail.stages) == raw_count
    assert len(detail.stages) > len(raw["stages"]), "fixture musi miec zagniezdzone etapy"


def test_order_is_depth_first_and_children_follow_their_parent(fixture_json):
    detail = _detail(fixture_json)
    names = [s.stage_name for s in detail.stages]

    # Etap nadrzedny, zaraz po nim jego zagniezdzone dzieci (Referral / CommitteeReport).
    parent_idx = names.index("Skierowano do I czytania na posiedzeniu Sejmu")
    child = detail.stages[parent_idx + 1]
    assert child.stage_name == "Skierowanie"
    assert child.stage_type == "Referral"
    assert child.depth == 1
    assert child.parent_stage == "Skierowano do I czytania na posiedzeniu Sejmu"
    assert child.committee_code == "Sejm"

    top = [s for s in detail.stages if s.depth == 0]
    assert len(top) == len(fixture_json("process_32_detail.json")["stages"])
    assert all(s.parent_stage is None for s in top)


def test_nested_committee_report_keeps_print_number(fixture_json):
    detail = _detail(fixture_json)
    reports = [s for s in detail.stages if s.stage_type == "CommitteeReport"]
    assert reports, "fixture musi miec Sprawozdanie komisji"
    assert any(s.print_number for s in reports)


def test_voting_stage_carries_counts(fixture_json):
    detail = _detail(fixture_json)
    voting_stages = [s for s in detail.stages if s.stage_type == "Voting"]
    assert voting_stages, "fixture musi miec etap glosowania"

    vote = voting_stages[0]
    assert vote.voting is not None
    assert vote.voting.yes is not None
    assert vote.voting.no is not None
    assert vote.voting.abstain is not None
    assert vote.voting.not_participating is not None
    assert vote.voting.total_voted is not None
    assert vote.voting.majority_type
    assert vote.voting.voting_number is not None
    assert vote.voting.pdf_url and vote.voting.pdf_url.endswith("/pdf")
    assert vote.voting.date is not None and "T" in vote.voting.date


def test_voting_is_attached_only_to_voting_stages(fixture_json):
    detail = _detail(fixture_json)
    for stage in detail.stages:
        if stage.stage_type == "Voting":
            assert stage.voting is not None
        else:
            assert stage.voting is None


def test_end_stage_without_date_survives(fixture_json):
    """Etap `End` nie ma daty - splaszczanie musi to przetrwac, nie wybuchnac."""
    detail = _detail(fixture_json)
    end = detail.stages[-1]
    assert end.stage_type == "End"
    assert end.date is None


def test_stage_dates_are_parsed(fixture_json):
    detail = _detail(fixture_json)
    first = detail.stages[0]
    assert first.date == date(2023, 4, 11)
    assert first.stage_type == "Start"


def test_reading_stage_keeps_decision_and_sitting(fixture_json):
    detail = _detail(fixture_json)
    third = next(s for s in detail.stages if s.stage_name == "III czytanie na posiedzeniu Sejmu")
    assert third.decision == "uchwalono"
    assert third.sitting_num == 16
    assert third.comment


def test_flatten_handles_empty_and_none():
    assert flatten_stages(None) == []
    assert flatten_stages([]) == []


def test_flatten_of_a_stage_without_children():
    stages = flatten_stages([{"stageName": "Uchwalono", "stageType": "End"}])
    assert len(stages) == 1
    assert stages[0].depth == 0
    assert stages[0].parent_stage is None
