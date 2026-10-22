"""
Scraper dell'albo pretorio (cloud.urbi.it) - Comune di Anguillara Sabazia.

Passi:
1. apre il sito e clicca "Avanti" per caricare la tabella degli atti
2. legge ogni riga (ente, tipologia, testo, data inizio, data fine)
3. per ogni riga apre la modale "Pubblicazione" e ricava i link dei PDF
   (il badge "FILE" = documento contenuto nella busta firmata P7M)
4. opzionalmente scarica i PDF (quelli già presenti in locale non vengono riscaricati)
5. opzionalmente genera un riassunto di ogni PDF con un LLM locale (Ollama)
6. scrive un file HTML con la tabella: data atto, titolo, link remoto al PDF, riassunto

Requisiti:
    pip install playwright
    playwright install chromium
    pip install pypdf                # riassunti con LLM locale
    ollama pull <modello>            # riassunti con LLM locale (Ollama deve essere attivo)

Uso (python scraper_albo.py --help per l'elenco completo):
    python scraper_albo.py                                  # link + download dei PDF
    python scraper_albo.py --scarica false                  # solo link, niente download
    python scraper_albo.py --livello-log debug --log file   # log dettagliato solo su file
    python scraper_albo.py --debug true                     # salva HTML/screenshot della modale
    python scraper_albo.py --dal 01-10-2026 --al oggi --riassumi true
    python scraper_albo.py --riassumi true --modello gemma3:12b   # modello Ollama a scelta
    python scraper_albo.py --escludi "VISTO CONTABILE PER IMPEGNI"  # altri allegati da escludere

Log: ogni riga ha timestamp e livello (DEBUG/INFO/ERROR); destinazione e livello
si scelgono con --log (console, file, entrambi) e --livello-log.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from collections.abc import Iterable
from datetime import date, datetime
from html import escape as esc_html
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

URL = "https://cloud.urbi.it/urbi/progs/urp/ur1ME001.sto?DB_NAME=n1200704&w3cbt=S"
MODALE = "#idModale1"

# La modale contiene una tabella con lo stesso id (#idTabella2) di quella principale:
# si esclude quella dentro la modale.
TABELLA_ATTI = "#idTabella2:not(#idModale1 *)"

# Allegati da escludere (colonna "Descrizione" della modale): non vengono né
# scaricati né riassunti né inseriti nella tabella. Il confronto ignora maiuscole,
# minuscole e spazi multipli. Altre descrizioni si aggiungono con --escludi.
DESCRIZIONI_ESCLUSE = ("VISTO CONTABILE PER LIQUIDAZIONI",)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

RE_DATE = re.compile(r"dal\s+(\d{2}-\d{2}-\d{4})\s+al\s+(\d{2}-\d{2}-\d{4})")

LOG_FILE = "scraper_albo.log"
FORMATO_LOG = "%(asctime)s | %(levelname)-5s | %(message)s"
FORMATO_DATA = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger("scraper_albo")


class _FormatoConsole(logging.Formatter):
    """Come Formatter, ma senza traceback: sulla console basta il messaggio."""

    def format(self, record: logging.LogRecord) -> str:
        exc_info, exc_text = record.exc_info, record.exc_text
        record.exc_info = record.exc_text = None
        try:
            return super().format(record)
        finally:
            record.exc_info, record.exc_text = exc_info, exc_text


def configura_logging(
    file_log: str = LOG_FILE,
    livello_file: int = logging.DEBUG,
    console: bool = True,
    livello_console: int = logging.INFO,
    su_file: bool = True,
) -> None:
    """
    Configura il logging (timestamp + livello) su file e/o console.
    - su_file=True: scrive su `file_log` (in append) i messaggi da `livello_file`
      in su, con i traceback degli errori.
    - console=True: scrive sulla console i messaggi da `livello_console` in su
      (senza traceback se si registra anche su file).
    """
    if not su_file and not console:
        raise ValueError("serve almeno una destinazione: file o console")

    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)  # il filtro vero è negli handler
    logger.propagate = False

    if su_file:
        handler_file = logging.FileHandler(file_log, encoding="utf-8")
        handler_file.setLevel(livello_file)
        handler_file.setFormatter(logging.Formatter(FORMATO_LOG, FORMATO_DATA))
        logger.addHandler(handler_file)

    if console:
        handler_console = logging.StreamHandler()
        handler_console.setLevel(livello_console)
        classe_formato = _FormatoConsole if su_file else logging.Formatter
        handler_console.setFormatter(classe_formato(FORMATO_LOG, FORMATO_DATA))
        logger.addHandler(handler_console)


def _parse_data(valore: str) -> date:
    return datetime.strptime(valore, "%d-%m-%Y").date()


def apri_tabella(page: Page) -> None:
    """Apre il sito, clicca 'Avanti' e attende il caricamento della tabella."""
    logger.info(f"Apertura del sito: {URL}")
    page.goto(URL, wait_until="domcontentloaded")

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
        data_inizio = _parse_data(m.group(1)) if m else None
        data_fine = _parse_data(m.group(2)) if m else None

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


def _a_data(valore: date | str | None) -> date | None:
    """Accetta un date oppure una stringa 'GG-MM-AAAA'."""
    if valore is None or isinstance(valore, date):
        return valore
    return datetime.strptime(valore, "%d-%m-%Y").date()


def filtra_per_data(
    atti: list[dict],
    dal: date | str | None = None,
    al: date | str | None = None,
    campo: str = "data_inizio",
) -> list[dict]:
    """
    Filtra gli atti per data. `dal` e `al` sono inclusi e opzionali
    (date oppure stringhe 'GG-MM-AAAA').

    campo:
      - "data_inizio": data_inizio compresa tra dal e al (default)
      - "data_fine":   data_fine compresa tra dal e al
      - "periodo":     il periodo di pubblicazione si sovrappone all'intervallo
                       dal-al (atti in pubblicazione in almeno un giorno dell'intervallo)

    Gli atti senza la data richiesta vengono esclusi.
    """
    if campo not in ("data_inizio", "data_fine", "periodo"):
        raise ValueError("campo deve essere 'data_inizio', 'data_fine' o 'periodo'")

    dal, al = _a_data(dal), _a_data(al)
    risultati = []

    for atto in atti:
        inizio, fine = atto["data_inizio"], atto["data_fine"]

        if campo == "periodo":
            if inizio is None or fine is None:
                continue
            ok = (al is None or inizio <= al) and (dal is None or fine >= dal)
        else:
            data = atto[campo]
            if data is None:
                continue
            ok = (dal is None or data >= dal) and (al is None or data <= al)

        if ok:
            risultati.append(atto)

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


def nome_file_sicuro(testo: str, max_len: int = 150) -> str:
    """Ripulisce un testo per usarlo come nome file."""
    testo = re.sub(r'[\\/:*?"<>|]', " ", testo)  # caratteri non validi nei nomi file
    testo = " ".join(testo.split())  # normalizza gli spazi
    return testo[:max_len].rstrip(" .")


def id_documento(url: str) -> str:
    """
    Identificativo stabile del documento ricavato dall'URL: DOCORE_testata e
    DOCORE_versione (se presenti), altrimenti un hash dei parametri, ignorando il
    token di sessione FNSTR che può cambiare a ogni visita.
    """
    parametri = parse_qs(urlparse(url).query)
    testata = parametri.get("DOCORE_testata", [""])[0]
    if testata:
        versione = parametri.get("DOCORE_versione", ["1"])[0]
        return re.sub(r"[^\w.-]", "", f"{testata}-v{versione}")
    resto = sorted((k, v) for k, v in parametri.items() if k.upper() != "FNSTR")
    return hashlib.sha1(urlencode(resto, doseq=True).encode()).hexdigest()[:10]


def _e_pdf_valido(percorso: Path) -> bool:
    try:
        with open(percorso, "rb") as f:
            return b"%PDF" in f.read(1024)
    except OSError:
        return False


def trova_pdf_locale(cartella: Path, id_doc: str) -> Path | None:
    """
    Cerca in `cartella` un PDF già scaricato per questo documento: i file sono
    salvati come "<testo atto> - <descrizione> [<id>].pdf". Un file vuoto o
    corrotto viene ignorato, così verrà riscaricato.
    """
    if not cartella.is_dir():
        return None
    for percorso in sorted(cartella.glob("*.pdf")):
        if percorso.name.endswith(f"[{id_doc}].pdf"):
            if _e_pdf_valido(percorso):
                return percorso
            logger.error(f"File locale non valido, verrà riscaricato: {percorso}")
    return None


def scarica_pdf(
    context: BrowserContext,
    url: str,
    testo_atto: str,
    descrizione: str,
    cartella: Path,
) -> Path | None:
    """
    Restituisce il percorso locale del PDF. Se il documento è già presente in
    `cartella` non viene scaricato e si usa il file esistente; altrimenti lo scarica
    con la sessione (cookie) del browser e lo salva come
    "<testo atto> - <descrizione allegato> [<id>].pdf".
    Restituisce None se il download non è valido.
    """
    cartella.mkdir(parents=True, exist_ok=True)
    id_doc = id_documento(url)

    esistente = trova_pdf_locale(cartella, id_doc)
    if esistente:
        logger.info(f"   già presente in locale, download saltato: {esistente}")
        return esistente

    logger.debug(f"GET {url}")
    risposta = context.request.get(url, timeout=60_000)
    if not risposta.ok:
        logger.error(f"Download fallito (HTTP {risposta.status}): {url}")
        return None

    contenuto = risposta.body()
    if b"%PDF" not in contenuto[:1024]:
        logger.error(f"Il contenuto scaricato non è un PDF: {url}")
        return None

    base = nome_file_sicuro(testo_atto, 120)
    if descrizione:
        base += " - " + nome_file_sicuro(descrizione, 40)

    destinazione = cartella / f"{base} [{id_doc}].pdf"
    temporaneo = destinazione.with_name(destinazione.name + ".part")
    temporaneo.write_bytes(contenuto)
    temporaneo.replace(destinazione)  # scrittura atomica: niente file a metà
    logger.info(f"   scaricato: {destinazione}")
    logger.debug(f"Salvato {destinazione} ({len(contenuto)} byte)")
    return destinazione


PROMPT_RIASSUNTO = (
    "Riassumi in italiano, in al massimo {max_righe} righe, il contenuto di questo "
    "atto amministrativo. Indica l'oggetto, i soggetti coinvolti e, se presenti, "
    "importi e scadenze. Rispondi solo con il riassunto, senza introduzioni."
)


OLLAMA_URL = "http://localhost:11434"
MODELLO_LOCALE = "llama3.1:8b"  # un modello già scaricato: controlla con `ollama list`
MAX_CARATTERI = 12_000  # testo massimo inviato al modello (evita di sforare il contesto)
NUM_CTX = 8192  # finestra di contesto richiesta a Ollama


def estrai_testo_pdf(percorso: str | Path) -> str:
    """Estrae il testo da un PDF (serve `pip install pypdf`)."""
    from pypdf import PdfReader

    lettore = PdfReader(str(percorso))
    testo = "\n".join((pagina.extract_text() or "") for pagina in lettore.pages)
    return testo.strip()


def riassumi_pdf_locale(
    percorso: str | Path,
    modello: str = MODELLO_LOCALE,
    url: str = OLLAMA_URL,
    max_righe: int = 4,
) -> str:
    """
    Riassume un PDF con un LLM locale servito da Ollama.
    Il testo viene estratto con pypdf e inviato al modello (nessun dato esce dal PC).
    """
    import json
    import urllib.request

    testo = estrai_testo_pdf(percorso)
    if not testo:
        raise RuntimeError("il PDF non contiene testo (probabile scansione: serve OCR)")
    logger.debug(
        f"Testo estratto da {Path(percorso).name}: {len(testo)} caratteri "
        f"(inviati al massimo {MAX_CARATTERI}) - modello {modello}"
    )
    testo = testo[:MAX_CARATTERI]

    istruzioni = PROMPT_RIASSUNTO.format(max_righe=max_righe)
    payload = {
        "model": modello,
        "stream": False,
        "options": {"num_ctx": NUM_CTX, "temperature": 0.2},
        "messages": [
            {"role": "user", "content": f"{istruzioni}\n\nTESTO DELL'ATTO:\n{testo}"}
        ],
    }
    richiesta = urllib.request.Request(
        f"{url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(richiesta, timeout=300) as risposta:
        dati = json.load(risposta)
    return dati["message"]["content"].strip()


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
    (come in `ollama list`).
    Gli allegati con una delle descrizioni in `escludi` (vedi DESCRIZIONI_ESCLUSE) non
    vengono scaricati, riassunti né inseriti nei risultati.
    """
    if riassumi and not scarica:
        raise ValueError("riassumi=True richiede scarica=True")

    if not logger.handlers:
        configura_logging()  # configurazione predefinita se non già fatta

    logger.info(
        f"Avvio: headless={headless}, scarica={scarica}, riassumi={riassumi}"
        f"{f' (modello {modello})' if riassumi else ''}, cartella={cartella}"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=USER_AGENT,
        )
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
                    atto["file_pdf"] = []
                    atto["riassunti"] = {}  # percorso file -> riassunto
                    for doc in atto["link_pdf"]:
                        percorso = scarica_pdf(
                            context,
                            doc["url"],
                            atto["testo_atto"],
                            doc["descrizione"],
                            Path(cartella),
                        )
                        if percorso:
                            atto["file_pdf"].append(str(percorso))
                            doc["file"] = str(percorso)

                            if riassumi:
                                try:
                                    riassunto = riassumi_pdf_locale(percorso, modello=modello)
                                except Exception as e:  # un errore non blocca gli altri atti
                                    logger.error(
                                        f"   riassunto non riuscito per {percorso.name}: {e}",
                                        exc_info=True,
                                    )
                                    continue
                                atto["riassunti"][str(percorso)] = riassunto
                                doc["riassunto"] = riassunto
                                logger.info("   riassunto: " + " ".join(riassunto.split()))

            logger.info(f"Elaborazione completata: {len(atti)} atti")
            return atti
        except Exception:
            logger.error("Errore durante lo scraping", exc_info=True)
            raise
        finally:
            browser.close()


def debug_modale(
    indice_riga: int = 0,
    headless: bool = False,
    file_html: str = "debug_modale.html",
    file_png: str = "debug_modale.png",
) -> None:
    """Salva HTML e screenshot della modale 'Pubblicazione' di una riga."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=USER_AGENT,
        )
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


COLONNE_TABELLA = ("Data atto", "Titolo atto", "Link remoto al PDF", "Riassunto")

CSS_TABELLA = """
:root {
  color-scheme: light dark;
  --bg: #ffffff; --fg: #1f2328; --muted: #6b7280; --bordo: #d8dee4;
  --testata: #f3f4f6; --hover: #f8fafc; --link: #0b5cad;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171a; --fg: #e6e8eb; --muted: #9aa4af; --bordo: #2d333b;
    --testata: #1d2228; --hover: #1a1f24; --link: #6cb2ff;
  }
}
body {
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  background: var(--bg); color: var(--fg); margin: 0; padding: 1.5rem; line-height: 1.45;
}
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
.meta { color: var(--muted); margin: 0 0 1rem; font-size: .9rem; }
.contenitore { overflow-x: auto; border: 1px solid var(--bordo); border-radius: 8px; }
table { border-collapse: collapse; width: 100%; min-width: 760px; }
th, td { padding: .6rem .8rem; text-align: left; vertical-align: top;
         border-bottom: 1px solid var(--bordo); }
thead th { background: var(--testata); font-size: .85rem; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover { background: var(--hover); }
td.data, td.link { white-space: nowrap; }
td.riassunto { white-space: pre-line; min-width: 22rem; }
a { color: var(--link); }
.vuoto { color: var(--muted); }
"""


def righe_tabella(atti: list[dict]) -> list[tuple[str, str, str, str]]:
    """
    Una riga per ogni PDF collegato a un atto (un atto senza allegati ha una sola
    riga con link e riassunto vuoti). 'Data atto' è la data di inizio pubblicazione.
    Se un atto ha più documenti, la descrizione del documento è aggiunta al titolo.
    """
    righe = []
    for atto in atti:
        data = atto["data_inizio"].strftime("%d-%m-%Y") if atto.get("data_inizio") else ""
        documenti = atto.get("link_pdf") or []

        if not documenti:
            righe.append((data, atto["testo_atto"], "", ""))
            continue

        for doc in documenti:
            titolo = atto["testo_atto"]
            if len(documenti) > 1 and doc.get("descrizione"):
                titolo += f" [{doc['descrizione']}]"
            righe.append((data, titolo, doc["url"], doc.get("riassunto", "")))
    return righe


def scrivi_tabella(atti: list[dict], percorso: str | Path) -> Path:
    """
    Scrive su file (UTF-8, sovrascrivendo) una pagina HTML autonoma con la tabella
    Data atto | Titolo atto | Link remoto al PDF | Riassunto.
    Tutti i testi sono "escapati"; i link sono cliccabili solo se http/https.
    """
    vuoto = '<span class="vuoto">—</span>'
    righe = righe_tabella(atti)

    corpo = []
    for data, titolo, url, riassunto in righe:
        if url.startswith(("http://", "https://")):
            u = esc_html(url, quote=True)
            cella_link = f'<a href="{u}" target="_blank" rel="noopener" title="{u}">Apri PDF</a>'
        else:
            cella_link = vuoto
        corpo.append(
            "      <tr>"
            f'<td class="data">{esc_html(data) or vuoto}</td>'
            f'<td class="titolo">{esc_html(" ".join(titolo.split()))}</td>'
            f'<td class="link">{cella_link}</td>'
            f'<td class="riassunto">{esc_html(riassunto.strip()) or vuoto}</td>'
            "</tr>"
        )

    n_documenti = sum(1 for r in righe if r[2])
    generato = datetime.now().strftime("%d-%m-%Y %H:%M")
    intestazione = "".join(f"<th>{esc_html(c)}</th>" for c in COLONNE_TABELLA)

    pagina = (
        '<!DOCTYPE html>\n<html lang="it">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Atti pubblicati</title>\n"
        f"<style>{CSS_TABELLA}</style>\n</head>\n<body>\n"
        "<h1>Atti pubblicati</h1>\n"
        f'<p class="meta">Generato il {generato} · {len(atti)} atti · {n_documenti} documenti</p>\n'
        '<div class="contenitore">\n  <table>\n'
        f"    <thead><tr>{intestazione}</tr></thead>\n    <tbody>\n"
        + "\n".join(corpo)
        + "\n    </tbody>\n  </table>\n</div>\n</body>\n</html>\n"
    )

    percorso = Path(percorso)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(pagina, encoding="utf-8")
    logger.debug(f"Tabella HTML scritta in {percorso}: {len(righe)} righe")
    return percorso


def _bool(valore: str) -> bool:
    """Converte true/false (e varianti) in bool, per gli argomenti da riga di comando."""
    v = str(valore).strip().lower()
    if v in ("true", "t", "1", "si", "sì", "s", "yes", "y"):
        return True
    if v in ("false", "f", "0", "no", "n"):
        return False
    raise argparse.ArgumentTypeError(f"valore non valido: {valore!r} (usa true o false)")


def _data_cli(valore: str) -> date:
    """Converte 'GG-MM-AAAA' oppure 'oggi' in date."""
    if valore.strip().lower() == "oggi":
        return date.today()
    try:
        return datetime.strptime(valore, "%d-%m-%Y").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"data non valida: {valore!r} (usa GG-MM-AAAA oppure 'oggi')"
        ) from None


class _HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter
):
    """Mostra i valori predefiniti e mantiene la formattazione dell'epilogo."""


EPILOGO_HELP = """\
esempi:
  python scraper_albo.py                                  link + download dei PDF
  python scraper_albo.py --scarica false                  solo link, niente download
  python scraper_albo.py --livello-log debug --log file   log dettagliato solo su file
  python scraper_albo.py --debug true                     salva HTML/screenshot della modale
  python scraper_albo.py --output risultati.html         nome del file HTML con la tabella finale
  python scraper_albo.py --dal 01-10-2026 --al oggi       solo gli atti in quell'intervallo
  python scraper_albo.py --riassumi true --modello gemma3:12b
                                                          riassunti con un modello Ollama a scelta
  python scraper_albo.py --escludi "VISTO CONTABILE PER IMPEGNI"
                                                          esclude anche questo tipo di allegato
"""


def _crea_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scraper dell'albo pretorio: legge gli atti, ricava i link dei PDF,\n"
            "li scarica e (opzionale) li riassume con un LLM locale (Ollama)."
        ),
        formatter_class=_HelpFormatter,
        epilog=EPILOGO_HELP,
    )
    bool_kw = dict(type=_bool, nargs="?", const=True, metavar="true|false")

    princ = parser.add_argument_group("opzioni principali")
    princ.add_argument(
        "--livello-log", type=str.lower, choices=["debug", "info", "error"],
        default="info", help="livello minimo dei messaggi registrati",
    )
    princ.add_argument(
        "--log", choices=["console", "file", "entrambi"], default="entrambi",
        help="dove scrivere il log",
    )
    princ.add_argument(
        "--debug", default=False,
        help="modalità debug: salva HTML e screenshot della modale della prima riga "
        "(browser visibile) ed esce, senza scaricare nulla", **bool_kw,
    )
    princ.add_argument(
        "--scarica", default=True,
        help="scarica i PDF (false = stampa solo i link)", **bool_kw,
    )

    altre = parser.add_argument_group("altre opzioni")
    altre.add_argument("--file-log", default=LOG_FILE, help="nome del file di log")
    altre.add_argument(
        "--output", default="tabella_atti.html",
        help="file HTML in cui scrivere la tabella finale (data, titolo, link PDF, riassunto)",
    )
    altre.add_argument("--cartella", default="download_atti", help="cartella dei PDF scaricati")
    altre.add_argument("--headless", default=True, help="browser senza finestra", **bool_kw)
    altre.add_argument("--dal", type=_data_cli, help="filtro data: da (GG-MM-AAAA o 'oggi')")
    altre.add_argument("--al", type=_data_cli, help="filtro data: a (GG-MM-AAAA o 'oggi')")
    altre.add_argument(
        "--campo", choices=["data_inizio", "data_fine", "periodo"], default="data_inizio",
        help="campo su cui applicare il filtro per data",
    )
    altre.add_argument(
        "--riassumi", default=False,
        help="riassume ogni PDF scaricato (richiede --scarica true)", **bool_kw,
    )
    altre.add_argument(
        "--modello", default=MODELLO_LOCALE,
        help="modello Ollama usato per i riassunti con --riassumi true "
        "(nome come in `ollama list`, es. gemma3:12b)",
    )
    altre.add_argument(
        "--escludi", action="append", metavar="DESCRIZIONE",
        help="descrizione di un allegato da escludere, come appare nella modale "
        "(si può ripetere); si aggiunge a quelle già escluse: "
        + ", ".join(DESCRIZIONI_ESCLUSE),
    )

    return parser


def _leggi_argomenti(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _crea_parser()
    args = parser.parse_args(argv)
    if not args.debug:
        if args.riassumi and not args.scarica:
            parser.error("--riassumi true richiede --scarica true")
        if args.dal and args.al and args.dal > args.al:
            parser.error("--dal deve essere precedente o uguale a --al")
    return args


def main(argv: list[str] | None = None) -> None:
    args = _leggi_argomenti(argv)

    # Usage sempre visibile su console (indipendente da --log)
    print(_crea_parser().format_usage(), end="")
    print("Usa --help per l'elenco completo delle opzioni.\n")

    livello = getattr(logging, args.livello_log.upper())
    configura_logging(
        file_log=args.file_log,
        livello_file=livello,
        console=args.log in ("console", "entrambi"),
        livello_console=livello,
        su_file=args.log in ("file", "entrambi"),
    )
    logger.debug(f"Argomenti: {vars(args)}")

    if args.debug:
        debug_modale(headless=False)
        return

    atti = stampa_link_pdf(
        headless=args.headless,
        scarica=args.scarica,
        cartella=args.cartella,
        dal=args.dal,
        al=args.al,
        campo=args.campo,
        riassumi=args.riassumi,
        modello=args.modello,
        escludi=DESCRIZIONI_ESCLUSE + tuple(args.escludi or ()),
    )

    percorso = scrivi_tabella(atti, args.output)
    logger.info(f"Tabella scritta in {percorso} ({len(atti)} atti)")


if __name__ == "__main__":
    main()
