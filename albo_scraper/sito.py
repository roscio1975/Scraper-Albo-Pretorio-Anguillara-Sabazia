"""Interazione con il sito dell'albo: tabella degli atti e modale 'Pubblicazione'.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Locator, Page, Playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from . import config
from .config import (
    ATTESA_CAMBIO_PAGINA_MS,
    DESCRIZIONI_ESCLUSE,
    MODALE,
    RE_DATE,
    SELETTORI_NUMERO_PAGINA,
    SELETTORI_PAGINA_SUCCESSIVA,
    TABELLA_ATTI,
    USER_AGENT,
)
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


def apri_modale(page: Page, indice_riga: int) -> Locator:
    """Apri la modale 'Pubblicazione' della riga."""
    riga = page.locator(f"{TABELLA_ATTI} tbody tr").nth(indice_riga)
    pulsante = riga.get_by_role("button", name="Pubblicazione")
    target = pulsante.get_attribute("data-bs-target") or pulsante.get_attribute(
        "data-target"
    )

    if not target:
        href = pulsante.get_attribute("href") or ""
        target = href if href.startswith("#") else None

    logger.debug(
        f"Apertura della modale 'Pubblicazione' (riga {indice_riga}, target={target!r})"
    )
    pulsante.click()

    if target:
        modale = page.locator(target)
        try:
            modale.wait_for(state="visible", timeout=5_000)
            return modale
        except PlaywrightTimeout:
            logger.debug(f"Target {target!r} non visibile; cerco la modale attiva")

    # Fallback per modali con ID variabile o senza target dichiarato sul pulsante.
    for selettore in (".modal.show", ".modal.in", "div.modal:visible", "[role='dialog']:visible"):
        candidate = page.locator(selettore)
        try:
            candidate.first.wait_for(state="visible", timeout=3_000)
            for i in range(candidate.count()):
                if candidate.nth(i).is_visible():
                    return candidate.nth(i)
        except PlaywrightTimeout:
            continue

    # Ultimo fallback per siti con markup non Bootstrap.
    modale = page.locator(MODALE)
    modale.wait_for(state="visible", timeout=5_000)
    return modale


def chiudi_modale(page: Page, modale: Locator) -> None:
    page.keyboard.press("Escape")
    try:
        modale.wait_for(state="hidden", timeout=3_000)
    except PlaywrightTimeout:
        logger.debug("Escape non ha chiuso la modale: uso il pulsante di chiusura")
        chiudi = modale.locator(
            ".btn-close, [data-dismiss='modal'], [data-bs-dismiss='modal']"
        )
        chiudi.first.click()
        modale.wait_for(state="hidden", timeout=5_000)


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

    modale = apri_modale(page, indice_riga)

    righe = modale.locator("fieldset tbody tr")  # tabella "Documenti Allegati"
    try:
        righe.first.wait_for(timeout=10_000)
    except PlaywrightTimeout:
        logger.info(f"[riga {indice_riga}] nessun documento allegato")
        chiudi_modale(page, modale)
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

    chiudi_modale(page, modale)
    return risultati


# --------------------------------------------------------------- paginazione
def _firma_tabella(page: Page) -> str:
    """
    Testo del corpo della tabella degli atti ('' se la tabella non c'è o sta cambiando):
    serve a capire quando la pagina è cambiata.
    """
    try:
        return page.locator(f"{TABELLA_ATTI} tbody").first.inner_text(timeout=1_000)
    except PlaywrightError:  # include il timeout e la pagina in fase di ricaricamento
        return ""


def _attendi_cambio_pagina(page: Page, prima: str) -> bool:
    """
    Attende (al massimo ATTESA_CAMBIO_PAGINA_MS) che il contenuto della tabella sia diverso
    da `prima` e resti stabile. Controlla di continuo con gli stessi selettori usati per
    leggere la tabella, quindi regge sia ai caricamenti AJAX sia ai ricaricamenti di pagina.
    """
    scadenza = time.monotonic() + ATTESA_CAMBIO_PAGINA_MS / 1000
    while time.monotonic() < scadenza:
        firma = _firma_tabella(page)
        if firma and firma != prima:
            page.wait_for_timeout(500)  # il contenuto deve essere finito di cambiare
            if _firma_tabella(page) == firma:
                return True
        page.wait_for_timeout(300)
    return False


def salva_istantanea(page: Page, file_html: str, file_png: str) -> None:
    """Salva HTML (senza script, stili e icone) e screenshot dell'intera pagina."""
    html = page.evaluate(
        """() => {
            const c = document.body.cloneNode(true);
            c.querySelectorAll('script, style, svg').forEach(e => e.remove());
            return c.outerHTML;
        }"""
    )
    Path(file_html).write_text(html, encoding="utf-8")
    page.screenshot(path=file_png, full_page=True)


def _diagnostica_cambio_pagina(page: Page, prima: str, pagina_corrente: int) -> None:
    """Dopo un cambio pagina non riuscito: registra cosa si vede e salva HTML e screenshot."""
    prossima = pagina_corrente + 1
    try:
        stato = page.evaluate("() => ({url: location.href, pronta: document.readyState})")
        dettaglio = (
            f"URL={stato['url']}, readyState={stato['pronta']}, "
            f"righe nella tabella degli atti={page.locator(f'{TABELLA_ATTI} tbody tr').count()}, "
            f"tabelle nella pagina={page.locator('table').count()}, "
            f"contenuto uguale a prima={_firma_tabella(page) == prima}, "
            f"schede aperte={len(page.context.pages)}"
        )
    except PlaywrightError as e:
        dettaglio = f"diagnostica non riuscita ({e})"

    file_html, file_png = f"debug_paginazione_{prossima}.html", f"debug_paginazione_{prossima}.png"
    try:
        salva_istantanea(page, file_html, file_png)
        salvati = f"Salvati {file_html} e {file_png}."
    except PlaywrightError as e:
        salvati = f"Salvataggio della diagnostica non riuscito ({e})."
    logger.error(
        f"Dopo il clic sulla pagina {prossima} la tabella non è cambiata entro "
        f"{ATTESA_CAMBIO_PAGINA_MS // 1000} s: considero finite le pagine. {dettaglio}. {salvati}"
    )


def _non_cliccabile(elemento: Locator) -> bool:
    """True per gli elementi disabilitati o che non fanno parte della paginazione."""
    return elemento.evaluate(
        """e => !!e.closest("table, #idModale1, .disabled, [disabled], [aria-disabled='true']")"""
    )


def _primo_cliccabile(page: Page, selettori: Iterable[str]) -> tuple[Locator, str] | None:
    """Primo elemento visibile e cliccabile trovato dai selettori (nell'ordine dato)."""
    for selettore in selettori:
        elementi = page.locator(selettore)
        for i in range(min(elementi.count(), 10)):
            elemento = elementi.nth(i)
            if elemento.is_visible() and not _non_cliccabile(elemento):
                return elemento, selettore
    return None


def vai_a_pagina_successiva(page: Page, pagina_corrente: int) -> bool:
    """
    Clicca sul numero della pagina successiva (o, se non c'è, sul pulsante "successiva")
    e attende che la tabella cambi. Restituisce False se non ci sono altre pagine.
    """
    prossima = pagina_corrente + 1
    trovato = _primo_cliccabile(
        page, [s.format(n=prossima) for s in SELETTORI_NUMERO_PAGINA]
    ) or _primo_cliccabile(page, SELETTORI_PAGINA_SUCCESSIVA)
    if trovato is None:
        logger.debug(f"Nessun link alla pagina {prossima}: considero finite le pagine")
        return False

    link, selettore = trovato
    prima = _firma_tabella(page)
    logger.debug(f"Passaggio alla pagina {prossima} (clic su {selettore!r})")
    link.scroll_into_view_if_needed()
    link.click()
    if not _attendi_cambio_pagina(page, prima):
        _diagnostica_cambio_pagina(page, prima, pagina_corrente)
        return False
    return True


def descrivi_paginazione(page: Page, pagina_corrente: int = 1) -> str:
    """Diagnostica: quale link alla pagina successiva verrebbe usato (per la modalità debug)."""
    prossima = pagina_corrente + 1
    trovato = _primo_cliccabile(page, [s.format(n=prossima) for s in SELETTORI_NUMERO_PAGINA])
    origine = "numero di pagina"
    if trovato is None:
        trovato = _primo_cliccabile(page, SELETTORI_PAGINA_SUCCESSIVA)
        origine = "pulsante successiva"
    if trovato is None:
        return f"nessun link alla pagina {prossima} trovato"
    link, selettore = trovato
    html = link.evaluate("e => e.outerHTML")
    return f"link alla pagina {prossima} trovato ({origine}, selettore {selettore!r}): {html[:300]}"
