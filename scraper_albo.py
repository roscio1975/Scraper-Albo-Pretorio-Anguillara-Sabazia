"""
Scraper dell'albo pretorio (cloud.urbi.it) - Comune di Anguillara Sabazia.

Il codice è nel pacchetto `albo_scraper/` (vedi albo_scraper/__init__.py per
la descrizione dei moduli): questo file serve solo da punto di ingresso.

Requisiti:
    pip install -r requirements.txt
    playwright install chromium
    # riassunti: Omlx (predefinito) oppure Ollama
    #   Omlx: server attivo su OMLX_URL (default http://127.0.0.1:8000/v1)
    #   Ollama: `ollama pull <modello>` e Ollama attivo
    brew install tesseract tesseract-lang   # solo per l'OCR dei PDF scansionati (macOS)

Uso (python scraper_albo.py --help per l'elenco completo):
    python scraper_albo.py                                  # link + download dei PDF
    python scraper_albo.py --scarica false                  # solo link, niente download
    python scraper_albo.py --livello-log debug --log file   # log dettagliato solo su file
    python scraper_albo.py --debug true                     # salva HTML/screenshot della modale
    python scraper_albo.py --dal 01-10-2026 --al oggi --riassumi true
    python scraper_albo.py --riassumi true                  # riassunti con Omlx (predefinito)
    python scraper_albo.py --riassumi true --provider ollama --modello gemma3:12b
    python scraper_albo.py --escludi "VISTO CONTABILE PER IMPEGNI"  # altri allegati da escludere
    python scraper_albo.py --escludi "*matrimonio*"                 # jolly, ignora maiuscole

Memoria: i documenti già scaricati e riassunti sono registrati in stato_atti.json e non
vengono rifatti (--ignora-stato true per rifare tutto, --stato "" per disattivarla).

Log: ogni riga ha timestamp e livello (DEBUG/INFO/ERROR); destinazione e livello
si scelgono con --log (console, file, entrambi) e --livello-log.
"""

from albo_scraper.cli import main

if __name__ == "__main__":
    main()
