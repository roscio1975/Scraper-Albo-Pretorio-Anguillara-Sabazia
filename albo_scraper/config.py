"""Costanti e impostazioni di default dello scraper.
"""

from __future__ import annotations

import os
import re


# --- Sito
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


# --- Logging
LOG_FILE = "scraper_albo.log"
FORMATO_LOG = "%(asctime)s | %(levelname)-5s | %(message)s"
FORMATO_DATA = "%Y-%m-%d %H:%M:%S"


# --- Riassunti con LLM locale (Ollama)
PROMPT_RIASSUNTO = (
    "Riassumi in italiano, in al massimo {max_righe} righe, il contenuto di questo "
    "atto amministrativo. Indica l'oggetto, i soggetti coinvolti e, se presenti, "
    "importi e scadenze, facendo particolare attenzione alla determina. Rispondi solo con il riassunto, senza introduzioni."
)

# Indirizzo di Ollama: variabile d'ambiente OLLAMA_URL (utile in Docker) oppure locale.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODELLO_LOCALE = "llama3.1:8b"  # un modello già scaricato: controlla con `ollama list`
MAX_CARATTERI = 12_000  # testo massimo inviato al modello (evita di sforare il contesto)
NUM_CTX = 8192  # finestra di contesto richiesta a Ollama


# --- OCR per i PDF scansionati (Tesseract)
OCR_LINGUA = "ita"  # lingua/e di Tesseract, es. "ita" oppure "ita+eng"
OCR_DPI = 300  # risoluzione con cui le pagine vengono trasformate in immagine
MIN_CARATTERI_PAGINA = 50  # sotto questa soglia una pagina è considerata una scansione


# --- Tabella finale
COLONNE_TABELLA = ("Data atto", "Titolo atto", "Link remoto al PDF", "Riassunto")
