"""Flusso principale: legge gli atti, ricava i link, scarica i PDF e li riassume."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from .config import (
    DESCRIZIONI_ESCLUSE,
    MAX_ERRORI_CONSECUTIVI,
    MAX_PAGINE_SICUREZZA,
    MODELLO_LOCALE,
    OCR_LINGUA,
    OLLAMA_URL,
    STATO_FILE,
)
from .filtri import a_data, filtra_per_data, piu_recenti
from .log import configura_logging, logger
from .pdf import id_documento, scarica_pdf
from .riassunti import riassumi_pdf_locale
from .sito import (
    apri_tabella,
    crea_contesto,
    ottieni_link_pdf_atto,
    parse_tabella,
    vai_a_pagina_successiva,
)
from .stato import StatoAtti, adesso


@dataclass
class Impostazioni:
    """Parametri dell'elaborazione, raggruppati per passarli alle funzioni."""

    # documenti
    cartella: Path
    scarica: bool
    riassumi: bool
    modello: str
    ollama_url: str
    ocr: bool
    ocr_lingua: str
    stato: StatoAtti
    escludi: Iterable[str]
    # selezione degli atti
    dal: date | str | None
    al: date | str | None
    campo: str
    max_atti: int | None
    max_pagine: int | None


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


def _elabora_atto(
    page: Page, context: BrowserContext, atto: dict, imp: Impostazioni
) -> bool:
    """
    Ricava i link dell'atto (modale 'Pubblicazione') e, se richiesto, scarica e riassume.
    Se l'atto non si riesce a elaborare (es. la modale non si apre) registra l'errore e
    restituisce False, senza interrompere gli altri atti.
    """
    try:
        atto["link_pdf"] = ottieni_link_pdf_atto(page, atto["indice_riga"], imp.escludi)
    except PlaywrightError as e:
        motivo = str(e).strip().splitlines()[0]
        logger.error(f"Atto non elaborato ({atto['testo_atto'][:80]}): {motivo}", exc_info=True)
        atto["link_pdf"] = []
        atto["errore"] = motivo
        try:  # chiude un'eventuale modale rimasta a metà, per non intralciare l'atto successivo
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except PlaywrightError:
            pass
        return False

    logger.info(f"Atto: {atto['testo_atto'][:80]}")
    for doc in atto["link_pdf"]:
        logger.info(f"   [{doc['descrizione']}] {doc['url']}")

    if imp.scarica:
        _scarica_documenti(context, atto, imp)
    else:
        _riporta_riassunti_salvati(atto, imp.stato)
    return True


def _oltre_data_minima(atti_pagina: list[dict], imp: Impostazioni) -> bool:
    """
    True se la pagina contiene atti precedenti a `dal`: poiché la tabella va dal più recente
    al più vecchio, le pagine successive non avrebbero atti utili. Vale solo per il filtro
    sulla data di inizio (con data_fine o periodo non si può sapere).
    """
    if not imp.dal or imp.campo != "data_inizio":
        return False
    minima = a_data(imp.dal)
    return any(a["data_inizio"] and a["data_inizio"] < minima for a in atti_pagina)


def _limite_pagine(imp: Impostazioni) -> int:
    """Quante pagine al massimo leggere, in base ai criteri indicati."""
    if imp.max_pagine is not None:
        return min(imp.max_pagine, MAX_PAGINE_SICUREZZA)

    if imp.max_atti is None and not (imp.dal or imp.al):
        logger.info(
            "Nessun limite indicato (--max-atti, --dal/--al, --max-pagine): "
            "leggo solo la prima pagina"
        )
        return 1

    if imp.max_atti is None and not imp.dal:
        logger.info("Nessun limite inferiore (--dal) né --max-atti: scorro tutte le pagine")
    elif imp.max_atti is None and imp.campo != "data_inizio":
        logger.info(
            f"Con il filtro su '{imp.campo}' non posso fermarmi in base a --dal: "
            "scorro tutte le pagine (usa --max-atti o --max-pagine per limitarle)"
        )
    return MAX_PAGINE_SICUREZZA


def _elabora_pagine(page: Page, context: BrowserContext, imp: Impostazioni) -> list[dict]:
    """
    Elabora gli atti pagina per pagina, partendo dalla prima (la più recente), finché non si
    raggiunge `max_atti`, non si superano le date indicate, non finiscono le pagine o non si
    arriva a `max_pagine`.
    """
    elaborati: list[dict] = []
    filtra = bool(imp.dal or imp.al)
    limite_pagine = _limite_pagine(imp)
    numero = 1
    errori_consecutivi = 0

    while True:
        atti_pagina = parse_tabella(page)
        logger.info(f"Pagina {numero}: letti {len(atti_pagina)} atti")

        da_elaborare = atti_pagina
        if filtra:
            da_elaborare = filtra_per_data(atti_pagina, imp.dal, imp.al, imp.campo)
            logger.info(
                f"   filtro per data ({imp.campo}, dal={imp.dal}, al={imp.al}): "
                f"{len(da_elaborare)} atti su {len(atti_pagina)}"
            )
        if imp.max_atti is not None:
            da_elaborare = piu_recenti(da_elaborare, imp.max_atti - len(elaborati))

        troppi_errori = False
        for atto in da_elaborare:
            atto["pagina"] = numero
            if _elabora_atto(page, context, atto, imp):
                errori_consecutivi = 0
            else:
                errori_consecutivi += 1
            elaborati.append(atto)
            if errori_consecutivi >= MAX_ERRORI_CONSECUTIVI:
                logger.error(
                    f"{errori_consecutivi} atti consecutivi non elaborati: probabile problema "
                    "generale con il sito, mi fermo (la tabella conterrà quanto raccolto finora)"
                )
                troppi_errori = True
                break
        if troppi_errori:
            break

        # --- condizioni di arresto
        if imp.max_atti is not None and len(elaborati) >= imp.max_atti:
            logger.info(f"Raggiunto il limite di {imp.max_atti} atti: mi fermo")
            break
        if _oltre_data_minima(atti_pagina, imp):
            logger.info(f"Raggiunti atti precedenti al {imp.dal}: mi fermo")
            break
        if numero >= limite_pagine:
            if imp.max_pagine is not None or limite_pagine >= MAX_PAGINE_SICUREZZA:
                logger.info(f"Raggiunto il limite di {limite_pagine} pagine: mi fermo")
            break
        if not vai_a_pagina_successiva(page, numero):
            logger.info(f"Nessuna pagina successiva utilizzabile dopo la {numero}ª: mi fermo")
            if numero == 1 and limite_pagine > 1:
                logger.info(
                    "Se il sito ha più pagine, controlla i messaggi precedenti; per capire come "
                    "è fatta la paginazione lancia con --debug true (salva debug_tabella.html)"
                )
            break
        numero += 1

    logger.info(f"Elaborazione completata: {len(elaborati)} atti in {numero} pagine")
    return elaborati


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
    max_atti: int | None = None,
    max_pagine: int | None = None,
    url: str | None = None,
) -> list[dict]:
    """
    Legge la tabella degli atti (scorrendo le pagine), stampa i link dei PDF di ogni atto e
    restituisce i dati. Ogni dict ha la chiave 'link_pdf' (lista di {'descrizione', 'url'}).
    Con scarica=True salva anche i PDF in `cartella` (chiave 'file_pdf').
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

    Selezione degli atti (la tabella va dal più recente al più vecchio):
    - dal/al/campo filtrano per data (vedi filtra_per_data);
    - max_atti=N elabora al massimo N atti, partendo dal più recente per data dell'atto
      (data di inizio pubblicazione); gli atti già elaborati in precedenza contano nel limite;
    - si passa alla pagina successiva finché non si raggiunge max_atti, non si trovano atti
      precedenti a `dal` (solo con campo="data_inizio"), non finiscono le pagine o non si
      arriva a `max_pagine`;
    - senza alcun criterio (max_atti, dal, al, max_pagine) si legge solo la prima pagina.

    `url` è l'indirizzo dell'albo (di default quello in config.py).
    Un atto che non si riesce a elaborare viene registrato nel log e saltato; dopo
    MAX_ERRORI_CONSECUTIVI atti di fila ci si ferma.
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
        scarica=scarica,
        riassumi=riassumi,
        modello=modello,
        ollama_url=ollama_url,
        ocr=ocr,
        ocr_lingua=ocr_lingua,
        stato=StatoAtti(stato_file, ignora_stato),
        escludi=escludi,
        dal=dal,
        al=al,
        campo=campo,
        max_atti=max_atti,
        max_pagine=max_pagine,
    )

    with sync_playwright() as p:
        browser, context = crea_contesto(p, headless)
        page = context.new_page()
        try:
            apri_tabella(page, url)
            return _elabora_pagine(page, context, imp)
        except Exception:
            logger.error("Errore durante lo scraping", exc_info=True)
            raise
        finally:
            browser.close()
