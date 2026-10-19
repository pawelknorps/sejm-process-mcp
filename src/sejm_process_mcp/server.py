"""FastMCP server - 3 super-tools dla procesu legislacyjnego Sejmu.

Uruchamianie:
    python -m sejm_process_mcp.server

Lub jako entry point po pip install:
    sejm-process-mcp
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from typing import Any

import httpx
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import audit
from .client import SejmProcessClient
from .coverage import Coverage, build_coverage
from .models import (
    Print,
    ProcessDetail,
    filter_drafts,
    print_from_api,
    process_from_api,
)

# ---------------------------------------------------------------------------
# Instructions (procedural orchestration) - wstrzykiwane do system promptu
# klienta MCP. LLM widzi to PRZED pierwszym tool call.
# ---------------------------------------------------------------------------

INSTRUCTIONS = """\
Ten serwer MCP udostepnia proces legislacyjny Sejmu z oficjalnego API api.sejm.gov.pl (JSON, bez auth): projekty ustaw/uchwal (procesy), ich historie etapow oraz druki parlamentarne. Term (kadencja) jest parametrem - domyslnie biezaca `"10"`; starsze kadencje to `"9"`, `"8"`, itd.

## Kolejnosc wywolan

### Szukanie projektu
1. `search_drafts` - lista projektow w kadencji (`term`, default `"10"`). Filtry `query` (substring w tytule, bez wielkosci liter), `date_from`/`date_to` (YYYY-MM-DD, po dacie wplyniecia do Sejmu), `document_type` (np `"projekt ustawy"` albo enum `"BILL"`; dopasowanie substring, wiec uwazaj na odmiane) dzialaja po stronie klienta. Paginacja przez `limit`/`offset`. Zwraca kompaktowe rekordy z `number`.

### Historia procesu (rdzen wartosci)
2. `get_process` - pelny proces po `number` z listy powyzej: splaszczona os czasu `stages[]` (daty, nazwy etapow, decyzje, komisje, druki) plus wyniki glosowan (`voting`: `yes`/`no`/`abstain`/`not_participating`/`total_voted`, `majority_type`, `pdf_url`). Etapy zagniezdzone maja `depth` > 0 i `parent_stage`.

### Druk
3. `get_print` - rekord druku (`number`) i jego zalaczniki jako URL-e (`file_name` + `url`). Tool NIE pobiera plikow.

### Granice konektora
4. `sejm_coverage` - wywolaj PRZED powiedzeniem uzytkownikowi, ze czegos "nie ma" w procesie legislacyjnym, i zawsze gdy szukanie zwraca pustke. To moze byc luka konektora, a nie brak w prawie. Kazda luka ma `fallback`.

## Twarde ograniczenia

- **`search_drafts` filtruje jedna strone** (limit, default 50) - API Sejmu nie ma wyszukiwania server-side. Przy pustce po `query` przejrzyj kolejne strony (`offset`) albo poluzuj daty; brak trafienia nie znaczy, ze projekt nie istnieje.
- **`number` jest kluczem w obrebie kadencji** - `get_process(term="10", number="32")` i `get_process(term="9", number="32")` to rozne procesy. Nie przenos numeru miedzy kadencjami.
- **Brak lookupu po ELI** - rekordy nosza `eli` (`MP/2023/1261`), ale narzedzia rozwiazuja po `number`. Najpierw `search_drafts`, potem `number`.
- **Nie pobieramy tresci** - zalaczniki drukow zwracamy jako URL-e; konektor nie czyta PDF/DOCX.
- **Tekst obowiazujacy to nie ten konektor** - `passed: true` to wynik procesu, nie tekst w mocy. Po tekst uchwalony idz do konektora `isap` / eli.gov.pl.
- **Bez modyfikacji tresci urzedowej** - tytuly i nazwy etapow zwracamy verbatim z API Sejmu.
- **Audit log JSONL** - kazdy tool call zapisuje audit do `~/.matematic/audit/sejm-process-mcp.jsonl` (bez pelnych tresci drukow).

## Iteracja po bledach

Tool zwraca structured error z prefixem `[code]`:
- `missing_arg` - brakujacy wymagany parametr (np pusty `number`).
- `invalid_arg` - parametr poza zakresem (np `limit > 500`, `offset < 0`, `term` nie-liczbowy, zla data, `date_from` po `date_to`).
- `not_found` - proces albo druk o tym numerze nie istnieje w tej kadencji (HTTP 404). Sprobuj innego `term` lub `search_drafts`.
- `upstream_error` - blad API Sejmu (HTTP, timeout, niepoprawny JSON). Retry raz przed surface do uzytkownika.

## Styl odpowiedzi

- Cytuj proces po numerze i kadencji: `proces nr 32 (kadencja 10)` + `source_url`. Jesli `eli` jest znany, podaj takze ELI.
- Historie etapow podawaj chronologicznie (tabela: data | etap | decyzja | glosowanie). Nie przestawiaj etapow.
- W glosowaniu rozdzielaj `abstain` od `not_participating` - NIE sumuj ich.
- NIE wymyslaj numerow, dat ani wynikow glosowan - wszystko z `structuredContent`.
- Terminologia: "projekt" (draft) to nie "ustawa"; dopoki proces jest otwarty (`closure_date` puste), nie mow o uchwaleniu.
"""


# Strukturalne kody bledow - widoczne dla LLM z prefixem [code].
class SejmProcessError(Exception):
    """Strukturalny blad dla sejm-process MCP tools."""

    VALID_CODES = frozenset({
        "missing_arg",
        "invalid_arg",
        "not_found",
        "upstream_error",
    })

    def __init__(self, code: str, message: str):
        if code not in self.VALID_CODES:
            raise ValueError(f"Unknown SejmProcessError code: {code}. Valid: {sorted(self.VALID_CODES)}")
        self.code = code
        super().__init__(f"[{code}] {message}")


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    idempotentHint=True,
    destructiveHint=False,
    openWorldHint=True,  # live API Sejmu
)


mcp = FastMCP(name="sejm-process-mcp", instructions=INSTRUCTIONS)


# ---------- helpers ----------


def _parse_term(term: str) -> int:
    """Waliduje kadencje i zwraca numer (API buduje z niego `term{N}`)."""
    t = str(term).strip().lower().removeprefix("term")
    if not t.isdigit() or int(t) < 1:
        raise SejmProcessError("invalid_arg", f"`term` musi byc numerem kadencji (np '10', '9'), dostano {term!r}.")
    return int(t)


def _parse_iso_date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SejmProcessError("invalid_arg", f"`{field}` musi byc w formacie YYYY-MM-DD: {exc}") from exc


def _require_number(number: str) -> str:
    n = str(number).strip()
    if not n:
        raise SejmProcessError("missing_arg", "Parametr `number` jest wymagany (np '32'). Ustal go przez `search_drafts`.")
    return n


async def _fetch(coro) -> tuple[Any, str]:
    """Wykonuje request klienta, mapujac bledy HTTP na kody strukturalne."""
    try:
        return await coro
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise SejmProcessError(
                "not_found",
                f"API Sejmu nie zna tego zasobu w tej kadencji (HTTP 404): {exc.request.url}.",
            ) from exc
        raise SejmProcessError("upstream_error", f"Blad API Sejmu: {exc}") from exc
    except httpx.HTTPError as exc:
        raise SejmProcessError("upstream_error", f"Blad API Sejmu: {exc}") from exc


# ---------- TOOL 1: search_drafts ----------


@mcp.tool(annotations=READ_ONLY)
async def search_drafts(
    term: str = "10",
    query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    document_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Szuka projektow (proces legislacyjny) w danej kadencji Sejmu.

    API Sejmu nie ma wyszukiwania server-side, wiec filtry `query`/`date_from`/
    `date_to`/`document_type` dzialaja po stronie klienta na pobranej stronie
    (`limit` rekordow od `offset`). Przy pustym wyniku przejdz na kolejna strone.

    Args:
        term: numer kadencji (default "10"; starsze: "9", "8", ...)
        query: substring w `title` albo `title_final` (bez wielkosci liter)
        date_from: YYYY-MM-DD, dolna granica `process_start_date`
        date_to: YYYY-MM-DD, gorna granica `process_start_date`
        document_type: substring w `document_type` ("projekt ustawy") albo enum ("BILL")
        limit: ile rekordow pobrac (default 50, max 500)
        offset: przesuniecie w liscie (default 0)

    Returns:
        dict: {term, limit, offset, fetched, count, items: [...], source_url, retrieved_at}
    """
    t0 = time.monotonic()
    term_num = _parse_term(term)

    if limit < 1 or limit > 500:
        raise SejmProcessError("invalid_arg", f"`limit` musi byc w zakresie 1-500, dostano {limit}.")
    if offset < 0:
        raise SejmProcessError("invalid_arg", f"`offset` musi byc >= 0, dostano {offset}.")

    df = _parse_iso_date(date_from, "date_from")
    dt = _parse_iso_date(date_to, "date_to")
    if df and dt and df > dt:
        raise SejmProcessError("invalid_arg", f"date_from ({df}) jest po date_to ({dt}).")

    async with SejmProcessClient() as client:
        raw_list, source_url = await _fetch(
            client.list_processes(term_num, limit=limit, offset=offset)
        )

    items = [process_from_api(raw, term_num) for raw in raw_list]
    matched = filter_drafts(items, query=query, date_from=df, date_to=dt, document_type=document_type)

    result = {
        "term": term_num,
        "limit": limit,
        "offset": offset,
        "fetched": len(items),
        "count": len(matched),
        "items": [m.model_dump(mode="json") for m in matched],
        "source_url": source_url,
        "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }

    audit.log_event(
        tool="search_drafts",
        params={
            "term": term,
            "query": query,
            "date_from": date_from,
            "date_to": date_to,
            "document_type": document_type,
            "limit": limit,
            "offset": offset,
        },
        result_summary={"fetched": len(items), "count": len(matched)},
        source_urls=[source_url],
        latency_ms=(time.monotonic() - t0) * 1000,
        cache_hit=False,
    )
    return result


# ---------- TOOL 2: get_process ----------


@mcp.tool(annotations=READ_ONLY)
async def get_process(term: str = "10", number: str = "") -> dict:
    """Pelny proces legislacyjny z historia etapow (rdzen wartosci tego konektora).

    `stages[]` z API jest drzewem; zwracamy je jako uporzadkowana (depth-first)
    os czasu. Etapy zagniezdzone maja `depth` > 0 i `parent_stage`; glosowania
    sa w `voting` (yes/no/abstain/not_participating/total_voted/majority_type/pdf_url).

    Args:
        term: numer kadencji (default "10")
        number: numer procesu z `search_drafts` (np "32") - klucz tylko w obrebie kadencji

    Returns:
        ProcesDetail jako dict: pola ProcessSummary + `stages`, `legislative_committee`,
        `principle_of_subsidiarity`, `prints_considered_jointly`.
    """
    t0 = time.monotonic()
    term_num = _parse_term(term)
    num = _require_number(number)

    async with SejmProcessClient() as client:
        raw, source_url = await _fetch(client.get_process(term_num, num))

    detail: ProcessDetail = process_from_api(raw, term_num, detail=True)  # type: ignore[assignment]

    audit.log_event(
        tool="get_process",
        params={"term": term, "number": num},
        result_summary={"number": detail.number, "stages": len(detail.stages), "passed": detail.passed, "eli": detail.eli},
        source_urls=[source_url],
        latency_ms=(time.monotonic() - t0) * 1000,
        cache_hit=False,
    )
    return detail.model_dump(mode="json")


# ---------- TOOL 3: get_print ----------


@mcp.tool(annotations=READ_ONLY)
async def get_print(term: str = "10", number: str = "") -> dict:
    """Druk parlamentarny (druk) wraz z zalacznikami.

    Zalaczniki zwracamy jako URL-e (`file_name` + `url`) - konektor NIE pobiera
    plikow (PDF/DOCX zostaja po stronie klienta).

    Args:
        term: numer kadencji (default "10")
        number: numer druku (np "503", takze z sufiksem jak "503-A")

    Returns:
        Print jako dict: {number, term, title, document_date, delivery_date,
        change_date, process_print, attachments, source_url, retrieved_at}
    """
    t0 = time.monotonic()
    term_num = _parse_term(term)
    num = _require_number(number)

    async with SejmProcessClient() as client:
        raw, source_url = await _fetch(client.get_print(term_num, num))

    doc: Print = print_from_api(raw, term_num)

    audit.log_event(
        tool="get_print",
        params={"term": term, "number": num},
        result_summary={"number": doc.number, "attachments": len(doc.attachments), "process_print": doc.process_print},
        source_urls=[source_url],
        latency_ms=(time.monotonic() - t0) * 1000,
        cache_hit=False,
    )
    return doc.model_dump(mode="json")


# ---------- TOOL 4: sejm_coverage ----------


@mcp.tool(annotations=READ_ONLY)
async def sejm_coverage() -> Coverage:
    """Declare what this connector covers, how it is sourced, and what it does NOT cover.

    Call this before telling a user that the legislative process "does not contain"
    something, and whenever a search comes back empty: the absence may be a gap in this
    connector rather than in the Sejm record. Every gap carries a fallback saying where
    to look instead.

    Returns:
        ``Coverage`` with families, an as-of note, and a non-empty list of known gaps.
    """
    t0 = time.monotonic()
    coverage = build_coverage()
    audit.log_event(
        tool="sejm_coverage",
        params={},
        result_summary={"families": len(coverage.families), "gaps": len(coverage.known_gaps)},
        source_urls=[],
        latency_ms=(time.monotonic() - t0) * 1000,
        cache_hit=False,
    )
    return coverage


# ---------- entry point ----------


def main() -> None:
    """Entry point dla stdio MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
