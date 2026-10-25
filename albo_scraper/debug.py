"""Modalità debug: salva HTML e screenshot della modale 'Pubblicazione'."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from .config import MODALE
from .log import logger
from .sito import (
    apri_modale,
    apri_tabella,
    crea_contesto,
    descrivi_paginazione,
    salva_istantanea,
)


def _senza_schermo() -> bool:
    """True su Linux senza server grafico (tipicamente un server)."""
    return sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )


def debug_modale(
    indice_riga: int = 0,
    headless: bool | None = None,
    file_html: str = "debug_modale.html",
    file_png: str = "debug_modale.png",
    file_tabella: str = "debug_tabella.html",
    file_png_tabella: str = "debug_tabella.png",
) -> None:
    """
    Salva HTML e screenshot della tabella degli atti (compresa la paginazione) e della
    modale 'Pubblicazione' di una riga, e indica quale link alla pagina successiva verrebbe usato.
    headless=None: browser visibile, tranne dove non c'è uno schermo (es. un server).
    """
    if headless is None:
        headless = _senza_schermo()

    with sync_playwright() as p:
        browser, context = crea_contesto(p, headless)
        page = context.new_page()
        try:
            apri_tabella(page)

            # Tabella e paginazione (senza script, stili e icone per tenere il file leggibile)
            salva_istantanea(page, file_tabella, file_png_tabella)
            logger.info(f"Salvati {file_tabella} e {file_png_tabella}")
            logger.info(f"Paginazione: {descrivi_paginazione(page)}")

            apri_modale(page, indice_riga)
            page.wait_for_timeout(3_000)
            page.screenshot(path=file_png)
            html = page.locator(MODALE).evaluate("el => el.outerHTML")
            Path(file_html).write_text(html, encoding="utf-8")
            logger.info(f"Salvati {file_html} e {file_png}")
        finally:
            browser.close()
