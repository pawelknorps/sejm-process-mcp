"""Element 9 of the MateMatic MCP canon: this connector declares its own coverage.

Knowledge about what a corpus does NOT hold is useless while it lives only as prose
in the server instructions - the model has to remember it and choose to relay it, and
an agent has no way to ask. Here it is callable.

Every gap below is grounded in this connector's own source and tool surface. The list
is deliberately never empty: no legal corpus is complete, so an empty gap list would
mean "nobody checked", not "there are no gaps".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _CoverageBase(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class CoverageFamily(_CoverageBase):
    """One data family this connector exposes."""

    name: str = Field(description="Data family, e.g. 'Federal legislation'.")
    tool: str = Field(description="Tool or tools that reach this family.")
    source: str = Field(description="Official source the data comes from.")
    captured_at: str | None = Field(
        default=None,
        description="Date this family was last captured (ISO). None when queried live.",
    )
    live: bool = Field(default=True, description="True when queried live instead of from a snapshot.")


class CoverageGap(_CoverageBase):
    """A known, named hole in this connector's coverage - plus the way around it."""

    id: str = Field(description="Stable gap identifier.")
    family: str = Field(description="Which family the gap belongs to.")
    missing: str = Field(description="What is NOT available through this connector.")
    fallback: str = Field(description="Where to go instead.")


class Coverage(_CoverageBase):
    """What this connector covers, how it is sourced, and what it does not cover."""

    status: Literal["ok", "degraded", "failed"] = "ok"
    as_of_note: str = Field(description="States what the dates mean, and what they do not promise.")
    families: list[CoverageFamily] = Field(default_factory=list)
    known_gaps: list[CoverageGap] = Field(
        default_factory=list,
        description="Never empty. An empty list would mean 'not checked', not 'no gaps'.",
    )


SOURCE = "api.sejm.gov.pl (official Sejm REST API, no auth)"

AS_OF_NOTE = (
    "Data is queried live against the Sejm API, so there is no local snapshot date. The "
    "default term is the current one (10); earlier terms answer only when asked for "
    "explicitly, and a date on a stage states when the Sejm recorded it - not that the "
    "draft is still pending today."
)

_FAMILIES: list[dict] = [
    {
        "name": "Legislative processes (projects / drafts)",
        "tool": "search_drafts / get_process",
    },
    {"name": "Parliamentary prints (druki)", "tool": "get_print"},
]

_GAPS: list[dict] = [
    {
        "id": "SEJM-PROC-001",
        "family": "Legislative processes (projects / drafts)",
        "missing": "Only the Sejm (lower chamber) side of the process is covered. Senate amendments appear as a single stage position, never as the Senate's own process.",
        "fallback": "For the Senate stage use senat.gov.pl, and confirm the enacted text via the isap connector or eli.gov.pl.",
    },
    {
        "id": "SEJM-PROC-002",
        "family": "Legislative processes (projects / drafts)",
        "missing": "The enacted legal text is not here - only the process record, its stages and links to prints. `passed: true` names the outcome, not the text in force.",
        "fallback": "Use the isap connector (or eli.gov.pl) for the text as enacted and in force.",
    },
    {
        "id": "SEJM-PROC-003",
        "family": "Legislative processes (projects / drafts)",
        "missing": "The Sejm API exposes no server-side search: `search_drafts` filters one fetched page (default 50 records of a term holding hundreds), so a query can miss matches that sit on a later page.",
        "fallback": "Page through with `offset`, or widen `date_from`/`date_to`; the full text search belongs to isap/ELI.",
    },
    {
        "id": "SEJM-PROC-004",
        "family": "Legislative processes (projects / drafts)",
        "missing": "There is no lookup by ELI (`MP/2023/1261`). Records carry the ELI, but the tools resolve by process `number` within a term.",
        "fallback": "Find the process with `search_drafts(query=...)`, then read `number` from the record and call `get_process`.",
    },
    {
        "id": "SEJM-PROC-005",
        "family": "Parliamentary prints (druki)",
        "missing": "Attachments (PDF/DOCX) are returned as links only - the connector never downloads or extracts their text.",
        "fallback": "Fetch the attachment URL and read the file outside the connector.",
    },
    {
        "id": "SEJM-PROC-006",
        "family": "Parliamentary prints (druki)",
        "missing": "Only the current term answers by default, and earlier terms (term9, term8, ...) must be named explicitly; very old processes may be absent from the API.",
        "fallback": "Pass `term=\"9\"` (or older) explicitly; check isap for the enacted outcome.",
    },
]


def build_coverage() -> Coverage:
    """Assemble the declared coverage for this connector."""
    return Coverage(
        status="ok",
        as_of_note=AS_OF_NOTE,
        families=[CoverageFamily(source=SOURCE, live=True, **f) for f in _FAMILIES],
        known_gaps=[CoverageGap(**g) for g in _GAPS],
    )
