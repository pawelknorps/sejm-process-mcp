"""sejm-process-mcp - MCP server for the Sejm legislative process (projekty ustaw, druki, etapy)."""

__version__ = "0.1.0"
__author__ = "MateMatic"
__license__ = "Apache-2.0"

USER_AGENT = f"matematic-sejm-process-mcp/{__version__} (+https://matematic.co; kontakt@matematic.co)"

# Oficjalne API Sejmu - stan zweryfikowany 2026-10-19.
# Term jest segmentem sciezki: /sejm/term{N}/... (term10 = kadencja biezaca).
BASE_URL = "https://api.sejm.gov.pl"
