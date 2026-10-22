"""Interazione con il sito dell'albo: tabella degli atti e modale 'Pubblicazione'.
"""

from __future__ import annotations

from collections.abc import Iterable

from playwright.sync_api import Browser, BrowserContext, Page, Playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from . import config
from .config import DESCRIZIONI_ESCLUSE, MODALE, RE_DATE, TABELLA_ATTI, USER_AGENT
from .filtri import parse_data
from .log import logger


def crea_contesto(playwright: Playwright, headless: bool) -> tuple[Browser, BrowserContext]:
    """Avvia Chromium e crea un contesto con viewport ampio e user agent normale."""
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(
        viewport={"width": 1366, "height": 900},
        user_agent=USER_AGENT,
    )
    return browser, context


def apri_tabella(page: Page) -> None:
    """Apre il sito, clicca 'Avanti' e attende il caricamento della tabella."""
    logger.info(f"Apertura del sito: {config.URL}")
    page.goto(config.URL, wait_until="domcontentloaded")

    avanti = page.get_by_role("button", name="Avanti")
    if avanti.count() == 0:
        avanti = page.locator("a:has-text('Avanti'), input[value='Avanti']")
    logger.debug("Clic su 'Avanti'")
    avanti.first.click()

    page.wait_for_selector(f"{TABELLA_ATTI} tbody tr", timeout=30_000)
    logger.debug("Tabella degli atti caricata")


def parse_tabella(page: Page) -> list[dict]:
    """Restituisce una lista di dict, uno per ogni atto presente nella tabella."""
    risultati = []
    righe = page.locator(f"{TABELLA_ATTI} tbody tr")

    for i in range(righe.count()):
        cella = righe.nth(i).locator("td").nth(1)  # colonna "Atti pubblicati"

        # I 3 <strong> contengono, nell'ordine: ente, tipologia, testo dell'atto
        strong = cella.locator("strong")
        ente = strong.nth(0).text_content().strip()
        tipologia = strong.nth(1).text_content().strip()
        testo = strong.nth(2).text_content().strip()

        m = RE_DATE.search(cella.text_content())
        data_inizio = parse_data(m.group(1)) if m else None
        data_fine = parse_data(m.group(2)) if m else None

        risultati.append(
            {
                "ente_mittente": ente,
                "tipologia_atto": tipologia,
                "testo_atto": testo,
                "data_inizio": data_inizio,
                "data_fine": data_fine,
                "indice_riga": i,  # posizione nella tabella, serve per aprire la modale
            }
        )

    logger.info(f"Tabella letta: {len(risultati)} atti")
    for atto in risultati:
        logger.debug(
            f"  riga {atto['indice_riga']}: {atto['data_inizio']} -> {atto['data_fine']} | "
            f"{atto['tipologia_atto']} | {atto['testo_atto'][:60]}"
        )
    return risultati


def apri_modale(page: Page, indice_riga: int) -> None:
    riga = page.locator(f"{TABELLA_ATTI} tbody tr").nth(indice_riga)
    logger.debug(f"Apertura della modale 'Pubblicazione' (riga {indice_riga})")
    riga.get_by_role("button", name="Pubblicazione").click()
    page.locator(MODALE).wait_for(state="visible", timeout=15_000)


def chiudi_modale(page: Page) -> None:
    page.keyboard.press("Escape")
    try:
        page.locator(MODALE).wait_for(state="hidden", timeout=3_000)
    except PlaywrightTimeout:
        # Fallback: pulsante di chiusura
        logger.debug("Escape non ha chiuso la modale: uso il pulsante di chiusura")
        page.locator(f"{MODALE} .btn-close").first.click()
        page.locator(MODALE).wait_for(state="hidden", timeout=5_000)


def _normalizza(testo: str) -> str:
    return " ".join(testo.split()).casefold()


def ottieni_link_pdf_atto(
    page: Page,
    indice_riga: int,
    escludi: Iterable[str] = DESCRIZIONI_ESCLUSE,
) -> list[dict]:
    """
    Apre la modale 'Pubblicazione' della riga e restituisce, per ogni documento
    allegato, un dict {'descrizione': ..., 'url': ...} con l'URL del PDF.

    Per ogni allegato la modale mostra tre badge: P7M (busta firmata),
    FILE (documento contenuto nella busta = PDF) e FIRMA (dettagli della firma).
    Si prende "FILE" (URL con P7M=S); se manca, si usano gli altri link fecore02.
    """
    risultati: list[dict] = []
    escluse = {_normalizza(d) for d in escludi}

    apri_modale(page, indice_riga)
    modale = page.locator(MODALE)

    righe = modale.locator("fieldset tbody tr")  # tabella "Documenti Allegati"
    try:
        righe.first.wait_for(timeout=10_000)
    except PlaywrightTimeout:
        logger.info(f"[riga {indice_riga}] nessun documento allegato")
        chiudi_modale(page)
        return risultati

    for j in range(righe.count()):
        riga = righe.nth(j)
        descrizione = (riga.locator("td").first.text_content() or "").strip()

        if _normalizza(descrizione) in escluse:
            logger.debug(
                f"[riga {indice_riga}] allegato escluso: '{' '.join(descrizione.split())}'"
            )
            continue

        # a.href restituisce già l'URL assoluto
        hrefs = riga.locator("a[href*='fecore02.sto']").evaluate_all(
            "els => els.map(a => a.href)"
        )
        contenuto_busta = [h for h in hrefs if "P7M=S" in h]
        for url in contenuto_busta or hrefs:
            logger.debug(f"[riga {indice_riga}] allegato '{descrizione}': {url}")
            risultati.append({"descrizione": descrizione, "url": url})

    chiudi_modale(page)
    return risultati
