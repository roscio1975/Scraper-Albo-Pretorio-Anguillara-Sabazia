"""Flusso principale: legge gli atti, ricava i link, scarica i PDF e li riassume."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright

from .config import DESCRIZIONI_ESCLUSE, MODELLO_LOCALE, OCR_LINGUA, OLLAMA_URL, STATO_FILE
from .filtri import filtra_per_data
from .log import configura_logging, logger
from .pdf import id_documento, scarica_pdf
from .riassunti import riassumi_pdf_locale
from .sito import apri_tabella, crea_contesto, ottieni_link_pdf_atto, parse_tabella
from .stato import StatoAtti, adesso


@dataclass
class Impostazioni:
    """Parametri di elaborazione dei documenti, raggruppati per passarli alle funzioni."""

    cartella: Path
    riassumi: bool
    modello: str
    ollama_url: str
    ocr: bool
    ocr_lingua: str
    stato: StatoAtti


def _riporta_dallo_stato(atto: dict, doc: dict, voce: dict) -> None:
    """Copia in `atto` e `doc` quanto già registrato (file e riassunto)."""
    file = voce.get("file")
    if file:
        doc["file"] = file
        atto["file_pdf"].append(file)
    if voce.get("riassunto"):
        doc["riassunto"] = voce["riassunto"]
        atto["riassunti"][file or doc["url"]] = voce["riassunto"]


def _riporta_riassunti_salvati(atto: dict, stato: StatoAtti) -> None:
    """Senza download: mostra comunque i riassunti già registrati (per la tabella)."""
    for doc in atto["link_pdf"]:
        voce = stato.get(id_documento(doc["url"]))
        if voce and voce.get("riassunto"):
            doc["riassunto"] = voce["riassunto"]


def _riassumi_documento(
    atto: dict, doc: dict, percorso: Path, id_doc: str, imp: Impostazioni
) -> None:
    """Riassume un PDF, salva il testo in `doc`, in `atto['riassunti']` e nello stato."""
    try:
        riassunto = riassumi_pdf_locale(
            percorso,
            modello=imp.modello,
            url=imp.ollama_url,
            ocr=imp.ocr,
            lingua_ocr=imp.ocr_lingua,
        )
    except Exception as e:  # un errore non blocca gli altri atti
        logger.error(
            f"   riassunto non riuscito per {percorso.name}: {e}",
            exc_info=True,
        )
        return
    atto["riassunti"][str(percorso)] = riassunto
    doc["riassunto"] = riassunto
    imp.stato.aggiorna(id_doc, riassunto=riassunto, modello=imp.modello, riassunto_il=adesso())
    logger.info("   riassunto: " + " ".join(riassunto.split()))


def _scarica_documenti(context: BrowserContext, atto: dict, imp: Impostazioni) -> None:
    """
    Scarica (o riusa) i PDF dell'atto e, se richiesto, li riassume.
    I documenti già scaricati e riassunti in precedenza (secondo lo stato) vengono saltati.
    """
    atto["file_pdf"] = []
    atto["riassunti"] = {}  # percorso file -> riassunto
    data = atto["data_inizio"].isoformat() if atto.get("data_inizio") else ""

    for doc in atto["link_pdf"]:
        id_doc = id_documento(doc["url"])
        voce = imp.stato.get(id_doc) or {}

        # Già fatto tutto ciò che serve: né download, né OCR, né riassunto
        if voce.get("file") and (voce.get("riassunto") or not imp.riassumi):
            logger.info(f"   già elaborato in precedenza, salto: [{doc['descrizione']}] {id_doc}")
            _riporta_dallo_stato(atto, doc, voce)
            continue

        percorso = scarica_pdf(
            context,
            doc["url"],
            atto["testo_atto"],
            doc["descrizione"],
            imp.cartella,
        )
        if not percorso:
            continue

        atto["file_pdf"].append(str(percorso))
        doc["file"] = str(percorso)
        imp.stato.aggiorna(
            id_doc,
            titolo=atto["testo_atto"],
            descrizione=doc["descrizione"],
            data_inizio=data,
            file=str(percorso),
            scaricato_il=voce.get("scaricato_il") or adesso(),
        )

        if not imp.riassumi:
            continue
        if voce.get("riassunto"):  # riassunto già noto, serviva solo il file
            doc["riassunto"] = voce["riassunto"]
            atto["riassunti"][str(percorso)] = voce["riassunto"]
        else:
            _riassumi_documento(atto, doc, percorso, id_doc, imp)


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
    stato_file: str | Path | None = STATO_FILE,
    ignora_stato: bool = False,
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
    I documenti già scaricati e riassunti in precedenza sono registrati in `stato_file`
    (JSON) e non vengono rifatti; `stato_file=None` disattiva la memoria e
    `ignora_stato=True` rifà tutto ma aggiorna comunque il file.
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

    imp = Impostazioni(
        cartella=Path(cartella),
        riassumi=riassumi,
        modello=modello,
        ollama_url=ollama_url,
        ocr=ocr,
        ocr_lingua=ocr_lingua,
        stato=StatoAtti(stato_file, ignora_stato),
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
                    _scarica_documenti(context, atto, imp)
                else:
                    _riporta_riassunti_salvati(atto, imp.stato)

            logger.info(f"Elaborazione completata: {len(atti)} atti")
            return atti
        except Exception:
            logger.error("Errore durante lo scraping", exc_info=True)
            raise
        finally:
            browser.close()
