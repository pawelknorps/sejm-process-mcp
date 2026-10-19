"""Modele Pydantic v2 + czyste transformacje dla sejm-process-mcp.

Pola API sa mapowane aliasami (`ELI` -> `eli`, `titleFinal` -> `title_final`,
`processStartDate` -> `process_start_date`), a nadmiarowe klucze API sa ignorowane -
model widzi tylko stabilny, kompaktowy rekord.
"""

from __future__ import annotations

import datetime as _dt
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from . import BASE_URL


def _utcnow_iso() -> str:
    return datetime.now(_dt.UTC).isoformat(timespec="seconds")


def process_url(term: int, number: str) -> str:
    """Kanoniczny URL procesu (do cytowania / audytu)."""
    return f"{BASE_URL}/sejm/term{term}/processes/{number}"


def print_url(term: int, number: str) -> str:
    """Kanoniczny URL druku."""
    return f"{BASE_URL}/sejm/term{term}/prints/{number}"


def attachment_url(term: int, number: str, file_name: str) -> str:
    """URL zalacznika druku (PDF/DOCX)."""
    return f"{BASE_URL}/sejm/term{term}/prints/{number}/{file_name}"


class Link(BaseModel):
    """Link zewnetrzny przy rekordzie (`isap` | `eli` | `eli-api` | `pdf`)."""

    href: str
    rel: str


class Voting(BaseModel):
    """Wynik glosowania powiazany z etapem typu `Voting`.

    `abstain` i `notParticipating` to osobne pola - wstrzymujacy sie to nie
    nieobecni, wiec ich NIE sumujemy.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    date: str | None = Field(default=None, description="ISO-8601 z godzina, np '2024-07-26T18:02:25'")
    description: str | None = None
    title: str | None = None
    kind: str | None = Field(default=None, description="np 'ELECTRONIC'")
    yes: int | None = None
    no: int | None = None
    abstain: int | None = None
    not_participating: int | None = Field(default=None, alias="notParticipating")
    total_voted: int | None = Field(default=None, alias="totalVoted")
    majority_type: str | None = Field(default=None, alias="majorityType")
    majority_votes: int | None = Field(default=None, alias="majorityVotes")
    voting_number: int | None = Field(default=None, alias="votingNumber")
    sitting: int | None = None
    sitting_day: int | None = Field(default=None, alias="sittingDay")
    links: list[Link] = Field(default_factory=list)

    @property
    def pdf_url(self) -> str | None:
        """URL protokolu glosowania w PDF, jezeli API go podaje."""
        return next((link.href for link in self.links if link.rel == "pdf"), None)


class Stage(BaseModel):
    """Jeden etap procesu legislacyjnego (po splaszczeniu drzewa `stages[]`)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    date: _dt.date | None = Field(default=None, description="data etapu; brak dla etapow typu `End`")
    stage_name: str = Field(alias="stageName", description="np 'I czytanie na posiedzeniu Sejmu'")
    stage_type: str | None = Field(default=None, alias="stageType", description="np 'Voting', 'SejmReading'")
    decision: str | None = Field(default=None, description="np 'uchwalono', 'odrzucono'")
    comment: str | None = None
    committee_code: str | None = Field(default=None, alias="committeeCode", description="np 'PSR'")
    print_number: str | None = Field(default=None, alias="printNumber", description="druk zwiazany z etapem")
    sitting_num: int | None = Field(default=None, alias="sittingNum")
    position: str | None = Field(default=None, description="stanowisko Senatu, np 'nie wniósł poprawek'")
    proposal: str | None = None
    rapporteur_name: str | None = Field(default=None, alias="rapporteurName")
    minority_motions: int | None = Field(default=None, alias="minorityMotions")
    title: str | None = None
    depth: int = Field(default=0, description="0 = etap najwyzszego poziomu, 1 = etap zagniezdzony (children)")
    parent_stage: str | None = Field(default=None, description="nazwa etapu nadrzednego dla zagniezdzonych")
    voting: Voting | None = None


class ProcessSummary(BaseModel):
    """Skrocony rekord projektu z listy `/processes` (bez historii etapow)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    number: str = Field(description="numer procesu w danej kadencji (klucz dla get_process)")
    term: int = Field(description="numer kadencji Sejmu, np 10")
    title: str
    title_final: str | None = Field(default=None, alias="titleFinal", description="tytul po uchwaleniu")
    document_type: str | None = Field(default=None, alias="documentType", description="np 'projekt ustawy'")
    document_type_enum: str | None = Field(
        default=None, alias="documentTypeEnum", description="np 'BILL', 'DRAFT_RESOLUTION' (brak dla czesci rekordow)"
    )
    process_start_date: _dt.date | None = Field(default=None, alias="processStartDate")
    document_date: _dt.date | None = Field(default=None, alias="documentDate")
    closure_date: _dt.date | None = Field(default=None, alias="closureDate", description="brak gdy proces trwa")
    passed: bool | None = Field(default=None, description="czy proces zakonczyl sie przyjeciem")
    urgency_status: str | None = Field(default=None, alias="urgencyStatus", description="np 'NORMAL'")
    shorten_procedure: bool | None = Field(default=None, alias="shortenProcedure")
    eli: str | None = Field(default=None, alias="ELI", description="np 'MP/2023/1261'")
    display_address: str | None = Field(default=None, alias="displayAddress", description="np 'M.P. 2023 poz. 1261'")
    links: list[Link] = Field(default_factory=list)
    source_url: str = Field(default="", description="URL procesu w API Sejmu")
    retrieved_at: str = Field(default_factory=_utcnow_iso)


class ProcessDetail(ProcessSummary):
    """Pelny proces z liste etapow splaszczona do czytelnej osi czasu."""

    stages: list[Stage] = Field(default_factory=list)
    legislative_committee: bool | None = Field(default=None, alias="legislativeCommittee")
    principle_of_subsidiarity: bool | None = Field(default=None, alias="principleOfSubsidiarity")
    prints_considered_jointly: list[str] = Field(default_factory=list, alias="printsConsideredJointly")


class PrintAttachment(BaseModel):
    """Zalacznik druku - nazwa pliku + URL do pobrania."""

    file_name: str
    url: str


class Print(BaseModel):
    """Druk parlamentarny (`/prints/{number}`)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    number: str
    term: int
    title: str
    document_date: _dt.date | None = Field(default=None, alias="documentDate")
    delivery_date: _dt.date | None = Field(default=None, alias="deliveryDate")
    change_date: datetime | None = Field(default=None, alias="changeDate")
    process_print: list[str] = Field(default_factory=list, alias="processPrint", description="numery procesow korzystajacych z druku")
    attachments: list[PrintAttachment] = Field(default_factory=list)
    source_url: str = Field(default="")
    retrieved_at: str = Field(default_factory=_utcnow_iso)


# ---------- czyste transformacje (testowalne offline) ----------


def flatten_stages(
    raw_stages: list[dict[str, Any]] | None,
    parent_stage: str | None = None,
    depth: int = 0,
) -> list[Stage]:
    """Splaszcza drzewo `stages[]` do uporzadkowanej listy etapow.

    Kolejnosc jest depth-first: etap nadrzedny, zaraz po nim jego `children`,
    potem kolejny etap nadrzedny. Kazdy zagniezdzony etap niesie `depth` > 0 i
    `parent_stage` (nazwa etapu, z ktorego pochodzi).
    """
    out: list[Stage] = []
    for raw in raw_stages or []:
        children = raw.get("children") or []
        node = {k: v for k, v in raw.items() if k != "children"}
        node["depth"] = depth
        node["parent_stage"] = parent_stage
        stage = Stage.model_validate(node)
        out.append(stage)
        if children:
            out.extend(flatten_stages(children, parent_stage=stage.stage_name, depth=depth + 1))
    return out


def filter_drafts(
    items: list[ProcessSummary],
    query: str | None = None,
    date_from: _dt.date | None = None,
    date_to: _dt.date | None = None,
    document_type: str | None = None,
) -> list[ProcessSummary]:
    """Filtruje liste projektow po stronie klienta (API Sejmu nie ma tych filtrow).

    - `query`: case-insensitive substring w `title` albo `title_final`.
    - `date_from` / `date_to`: zakres na `process_start_date` (data wplyniecia do Sejmu).
      Rekordy bez tej daty wypadaja, gdy podano zakres.
    - `document_type`: case-insensitive substring w `document_type` (np 'projekt ustawy')
      albo w `document_type_enum` (np 'BILL'). Dopasowanie jest doslowne, wiec odmiana
      ma znaczenie: 'ustawy' trafia, 'ustawa' nie.
    """
    q = query.casefold() if query else None
    dtype = document_type.casefold() if document_type else None

    out: list[ProcessSummary] = []
    for item in items:
        if q and q not in (item.title or "").casefold() and q not in (item.title_final or "").casefold():
            continue
        if date_from or date_to:
            if item.process_start_date is None:
                continue
            if date_from and item.process_start_date < date_from:
                continue
            if date_to and item.process_start_date > date_to:
                continue
        if dtype:
            haystack = f"{(item.document_type or '').casefold()} {(item.document_type_enum or '').casefold()}"
            if dtype not in haystack:
                continue
        out.append(item)
    return out


def process_from_api(raw: dict[str, Any], term: int, detail: bool = False) -> ProcessSummary:
    """Buduje `ProcessSummary` albo `ProcessDetail` z surowego rekordu API."""
    data = dict(raw)
    data["source_url"] = process_url(term, str(raw["number"]))
    if detail:
        data["stages"] = flatten_stages(raw.get("stages"))
        return ProcessDetail.model_validate(data)
    return ProcessSummary.model_validate(data)


def print_from_api(raw: dict[str, Any], term: int) -> Print:
    """Buduje `Print` z surowego rekordu API, rozwijajac nazwy zalacznikow w URL-e."""
    number = str(raw["number"])
    data = dict(raw)
    data["attachments"] = [
        PrintAttachment(file_name=name, url=attachment_url(term, number, name))
        for name in raw.get("attachments") or []
    ]
    data["source_url"] = print_url(term, number)
    return Print.model_validate(data)
