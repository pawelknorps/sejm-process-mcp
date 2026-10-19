# sejm-process-mcp

Serwer MCP dla **procesu legislacyjnego Sejmu**: projekty ustaw i uchwal (procesy),
ich historia etapow oraz druki parlamentarne. Zrodlo: oficjalne API
`api.sejm.gov.pl` (JSON, bez auth).

Domyslna kadencja to biezaca (`term="10"`); starsze kadencje podaje sie jawnie
(`term="9"`, `"8"`, ...).

## Instalacja

```bash
uv pip install -e ".[dev]"
```

## Narzedzia

| Tool | Opis |
|------|------|
| `search_drafts(term, query, date_from, date_to, document_type, limit, offset)` | lista projektow w kadencji; filtry po stronie klienta (API Sejmu nie ma wyszukiwania server-side) |
| `get_process(term, number)` | pelny proces + splaszczona os czasu `stages[]` z wynikami glosowan |
| `get_print(term, number)` | druk parlamentarny i URL-e zalacznikow |
| `sejm_coverage()` | co konektor pokrywa, a czego nie (kazda luka ma `fallback`) |

## Uruchomienie

```bash
sejm-process-mcp          # stdio
python -m sejm_process_mcp.server
```

## Rozwoj

```bash
pytest
ruff check
```

Audit log: `~/.matematic/audit/sejm-process-mcp.jsonl`
(override: `SEJM_PROCESS_MCP_AUDIT_DIR`). Logowane sa metadane wywolan
(params_hash, result_summary, source_urls, latency_ms) - bez pelnych tresci drukow.
