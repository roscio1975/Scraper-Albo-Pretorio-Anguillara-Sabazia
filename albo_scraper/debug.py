"""Modalità debug: salva HTML e screenshot della modale 'Pubblicazione'."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from .config import MODALE
from .log import logger
from .sito import apri_modale, apri_tabella, crea_contesto


def debug_modale(
    indice_riga: int = 0,
    headless: bool = False,
    file_html: str = "debug_modale.html",
    file_png: str = "debug_modale.png",
) -> None:
    """Salva HTML e screenshot della modale 'Pubblicazione' di una riga."""
    with sync_playwright() as p:
        browser, context = crea_contesto(p, headless)
        page = context.new_page()
        try:
            apri_tabella(page)
            apri_modale(page, indice_riga)
            page.wait_for_timeout(3_000)
            page.screenshot(path=file_png)
            html = page.locator(MODALE).evaluate("el => el.outerHTML")
            Path(file_html).write_text(html, encoding="utf-8")
            logger.info(f"Salvati {file_html} e {file_png}")
        finally:
            browser.close()
