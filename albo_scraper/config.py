"""Costanti e impostazioni di default dello scraper.
"""

from __future__ import annotations

import os
import re


# --- Sito
URL = "https://cloud.urbi.it/urbi/progs/urp/ur1ME001.sto?DB_NAME=n1200704&w3cbt=S"
MODALE = "#idModale1"

# La tabella degli atti si riconosce dalla colonna "Atti pubblicati" e non dal suo id
# (#idTabella2): il sito può cambiare l'id quando carica un'altra pagina. Le tabelle
# dentro la modale sono escluse.
TABELLA_ATTI = "table:has(th:has-text('Atti pubblicati')):not(.modal *)"

# Allegati da escludere (colonna "Descrizione" della modale): non vengono né
# scaricati né riassunti né inseriti nella tabella. Il confronto ignora maiuscole,
# minuscole e spazi multipli. Altre descrizioni si aggiungono con --escludi.
DESCRIZIONI_ESCLUSE = ("VISTO CONTABILE PER LIQUIDAZIONI",)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

RE_DATE = re.compile(r"dal\s+(\d{2}-\d{2}-\d{4})\s+al\s+(\d{2}-\d{2}-\d{4})")


# --- Attese e tolleranza agli errori
ATTESA_MODALE_MS = 10_000  # attesa massima perché compaia la modale 'Pubblicazione'
MAX_ERRORI_CONSECUTIVI = 3  # dopo tanti atti di fila non elaborati ci si ferma


# --- Paginazione della tabella degli atti
# Selettori (in ordine di tentativo) del link al numero di pagina {n}.
SELETTORI_NUMERO_PAGINA = (
    "ul.pagination :is(a, button):text-is('{n}')",
    "nav[aria-label*='agin' i] :is(a, button):text-is('{n}')",
    ":is(a, button, [role='button']):text-is('{n}')",
    ":is(a, button)[aria-label='Pagina {n}' i]",
    ":is(a, button)[title='Pagina {n}' i]",
    ":is(a, button)[aria-label*='ina {n}' i]",
)
# Selettori del pulsante "pagina successiva", usati se il numero non è visibile.
SELETTORI_PAGINA_SUCCESSIVA = (
    "[rel='next']",
    ":is(a, button)[aria-label*='successiv' i]",
    ":is(a, button)[title*='successiv' i]",
    ":is(a, button):text-is('Successiva')",
    ":is(a, button):text-is('Pagina successiva')",
    ":is(a, button):text-is('Next')",
    ":is(a, button):text-is('›')",
    ":is(a, button):text-is('»')",
    ":is(a, button):text-is('>')",
)
MAX_PAGINE_SICUREZZA = 500  # tetto assoluto di pagine, contro cicli infiniti
ATTESA_CAMBIO_PAGINA_MS = 60_000  # attesa massima perché la tabella cambi dopo il clic


# --- Logging
LOG_FILE = "scraper_albo.log"
FORMATO_LOG = "%(asctime)s | %(levelname)-5s | %(message)s"
FORMATO_DATA = "%Y-%m-%d %H:%M:%S"


# --- Riassunti con LLM locale (Ollama)
PROMPT_RIASSUNTO = (
    "Riassumi in italiano, in al massimo {max_righe} righe, il contenuto di questo "
    "atto amministrativo. Indica l'oggetto, i soggetti coinvolti e, se presenti, "
    "importi e scadenze, facendo particolare attenzione alle sezioni «Appurato che» e «Determina». "
    "Rispondi solo con il riassunto, senza introduzioni."
)

# Indirizzo di Ollama: variabile d'ambiente OLLAMA_URL (utile se gira su un altro
# computer) oppure locale.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODELLO_LOCALE = "llama3.1:8b"  # un modello già scaricato: controlla con `ollama list`
MAX_CARATTERI = 12_000  # testo massimo inviato al modello (evita di sforare il contesto)
NUM_CTX = 8192  # finestra di contesto richiesta a Ollama per i riassunti


# --- OCR per i PDF scansionati (Tesseract)
OCR_LINGUA = "ita"  # lingua/e di Tesseract, es. "ita" oppure "ita+eng"
OCR_DPI = 300  # risoluzione con cui le pagine vengono trasformate in immagine
MIN_CARATTERI_PAGINA = 50  # sotto questa soglia una pagina è considerata una scansione


# --- Memoria degli atti già elaborati
STATO_FILE = "stato_atti.json"


# --- Email ---
# Configura i dati del tuo account (es. Gmail, Outlook, o un altro server SMTP)
SMTP_SERVER = "smtp.mail.ovh.net"
SMTP_PORT = 587
SMTP_USER = "info@granfacucinaletteraria.it"
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")  # mai nel codice: variabile d'ambiente
EMAIL_FROM = "info@granfacucinaletteraria.it"
RECEIPTS_FILE = "receipts.txt"
# --- Tabella finale
COLONNE_TABELLA = ("Data atto", "Titolo atto", "Link remoto al PDF", "Riassunto")


# --- Diario (--diario): resoconto discorsivo generato da Ollama a partire dalla tabella
PROMPT_DIARIO = """\
Crea un resoconto amichevole, discorsivo e leggibile in italiano, adatto a un pubblico generico, dei seguenti atti amministrativi pubblicati sul sito dell'Albo Pretorio.
Se non ci sono riassunti specifici (solo "—"), descrivi che l'attività è stata pubblicata senza ulteriore dettaglio.
Non usare formattazioni Markdown complesse. Usa paragrafi semplici ed elenchi puntati se necessario.

Ecco i dati (un atto per riga, in formato JSON):
{dati_atti}
"""
NUM_CTX_DIARIO_MAX = 16384  # contesto massimo richiesto per il diario (vedi diario.py)

# Intestazione della pagina del diario
TITOLO_PAGINA_DIARIO = "Diario - Sinistra Italia e AVS"
TITOLO_DIARIO = "Sinistra Italia e AVS informano"
SOTTOTITOLO_DIARIO = "Cosa è successo questa settimana nel Comune di Anguillara Sabazia"
LOGHI_DIARIO = (  # (indirizzo dell'immagine, testo alternativo); () per non mostrare loghi
    (
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/7f/Sinistra_Italiana.svg/250px-Sinistra_Italiana.svg.png",
        "Sinistra Italiana",
    ),
    (
        "https://verdisinistra.it/wp-content/uploads/2022/07/Alleanza-Verdi-Sinistra-10cm-copia@2x.png",
        "AVS",
    ),
)
