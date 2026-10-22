"""Flusso principale: legge gli atti, ricava i link, scarica i PDF e li riassume."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright

from .config import DESCRIZIONI_ESCLUSE, MODELLO_LOCALE, OCR_LINGUA, OLLAMA_URL
from .filtri import filtra_per_data
from .log import configura_logging, logger
from .pdf import scarica_pdf
from .riassunti import riassumi_pdf_locale
from .sito import apri_tabella, crea_contesto, ottieni_link_pdf_atto, parse_tabella


def _riassumi_documento(
    atto: dict,
    doc: dict,
    percorso: Path,
    modello: str,
    ollama_url: str,
    ocr: bool,
    ocr_lingua: str,
) -> None:
    """Riassume un PDF e salva il testo in `doc` e in `atto['riassunti']`."""
    try:
        riassunto = riassumi_pdf_locale(
            percorso, modello=modello, url=ollama_url, ocr=ocr, lingua_ocr=ocr_lingua
        )
    except Exception as e:  # un errore non blocca gli altri atti
        logger.error(
            f"   riassunto non riuscito per {percorso.name}: {e}",
            exc_info=True,
        )
        return
    atto["riassunti"][str(percorso)] = riassunto
    doc["riassunto"] = riassunto
    logger.info("   riassunto: " + " ".join(riassunto.split()))


def _scarica_documenti(
    context: BrowserContext,
    atto: dict,
    cartella: Path,
    riassumi: bool,
    modello: str,
    ollama_url: str,
    ocr: bool,
    ocr_lingua: str,
) -> None:
    """Scarica (o riusa) i PDF dell'atto e, se richiesto, li riassume."""
    atto["file_pdf"] = []
    atto["riassunti"] = {}  # percorso file -> riassunto

    for doc in atto["link_pdf"]:
        percorso = scarica_pdf(
            context,
            doc["url"],
            atto["testo_atto"],
            doc["descrizione"],
            cartella,
        )
        if not percorso:
            continue

        atto["file_pdf"].append(str(percorso))
        doc["file"] = str(percorso)

        if riassumi:
            _riassumi_documento(atto, doc, percorso, modello, ollama_url, ocr, ocr_lingua)


def stampa_link_pdf(
    headless: bool = True,
    scarica: bool = False,
    cartella: str = "download_atti",
    dal: date | str | None = None,
    al: date | str | None = None,
    campo: str = "data_inizio",
    riassumi: bool = False,
    modello: str = MODELLO_LOCALE,
    escludi: Iterable[str] = DESCRIZIONI_ESCLUSE,
    ollama_url: str = OLLAMA_URL,
    ocr: bool = True,
    ocr_lingua: str = OCR_LINGUA,
) -> list[dict]:
    """
    Legge la tabella, stampa i link dei PDF di ogni atto e restituisce i dati.
    Ogni dict ha la chiave 'link_pdf' (lista di {'descrizione', 'url'}).
    Con scarica=True salva anche i PDF in `cartella` (chiave 'file_pdf').
    Con dal/al/campo filtra gli atti per data (vedi filtra_per_data) prima di
    aprire le modali, così si visitano solo gli atti che interessano.
    Con riassumi=True (richiede scarica=True) genera un riassunto di ogni PDF
    scaricato (chiave 'riassunti': {percorso file: riassunto}).
    I riassunti usano un LLM locale servito da Ollama: `modello` è il nome del modello
    (come in `ollama list`) e `ollama_url` l'indirizzo del server (default: variabile
    d'ambiente OLLAMA_URL oppure http://localhost:11434).
    Con ocr=True i PDF scansionati (pagine senza testo) vengono letti con Tesseract
    nella lingua `ocr_lingua` prima di essere riassunti.
    Gli allegati con una delle descrizioni in `escludi` (vedi DESCRIZIONI_ESCLUSE) non
    vengono scaricati, riassunti né inseriti nei risultati.
    """
    if riassumi and not scarica:
        raise ValueError("riassumi=True richiede scarica=True")

    if not logger.handlers:
        configura_logging()  # configurazione predefinita se non già fatta

    logger.info(
        f"Avvio: headless={headless}, scarica={scarica}, riassumi={riassumi}"
        f"{f' (modello {modello} su {ollama_url})' if riassumi else ''}, cartella={cartella}"
    )

    with sync_playwright() as p:
        browser, context = crea_contesto(p, headless)
        page = context.new_page()
        try:
            apri_tabella(page)
            atti = parse_tabella(page)
            if dal or al:
                totale = len(atti)
                atti = filtra_per_data(atti, dal, al, campo)
                logger.info(
                    f"Filtro per data ({campo}, dal={dal}, al={al}): "
                    f"{len(atti)} atti su {totale}"
                )

            for atto in atti:
                atto["link_pdf"] = ottieni_link_pdf_atto(
                    page, atto["indice_riga"], escludi
                )

                logger.info(f"Atto: {atto['testo_atto'][:80]}")
                for doc in atto["link_pdf"]:
                    logger.info(f"   [{doc['descrizione']}] {doc['url']}")

                if scarica:
                    _scarica_documenti(
                        context,
                        atto,
                        Path(cartella),
                        riassumi,
                        modello,
                        ollama_url,
                        ocr,
                        ocr_lingua,
                    )

            logger.info(f"Elaborazione completata: {len(atti)} atti")
            return atti
        except Exception:
            logger.error("Errore durante lo scraping", exc_info=True)
            raise
        finally:
            browser.close()
