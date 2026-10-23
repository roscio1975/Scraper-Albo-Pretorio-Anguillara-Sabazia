# Scraper albo pretorio

Legge gli atti pubblicati sull'albo (cloud.urbi.it, Comune di Anguillara Sabazia),
scarica i PDF allegati, li riassume con un LLM locale (Ollama) e scrive una tabella HTML.
Opzioni complete: `python scraper_albo.py --help`.

## Installazione

Serve Python 3.10 o successivo (su Mac: `brew install python@3.12`).

```bash
python3 -m venv .venv
source .venv/bin/activate                 # da rifare in ogni nuovo terminale
python -m pip install -r requirements.txt
playwright install chromium               # una volta sola
brew install tesseract tesseract-lang     # OCR dei PDF scansionati (macOS)
ollama pull <modello>                     # per i riassunti; Ollama deve essere attivo
```

Su Debian/Ubuntu al posto di brew: `apt install tesseract-ocr tesseract-ocr-ita`.

## Uso

```bash
python scraper_albo.py                                         # link + download dei PDF
python scraper_albo.py --riassumi true --modello gemma3:12b    # con riassunti
python scraper_albo.py --dal 01-10-2026 --al oggi --riassumi true
python scraper_albo.py --scarica false                         # solo link, niente download
python scraper_albo.py --livello-log debug --log file          # log dettagliato solo su file
python scraper_albo.py --debug true                            # salva HTML/screenshot della modale
```

Il risultato è `tabella_atti.html` (cambia nome con `--output`); PDF e log finiscono nella
cartella di lavoro (`download_atti/`, `scraper_albo.log`).

Se Ollama gira su un altro computer: `--ollama-url http://indirizzo:11434` oppure la variabile
d'ambiente `OLLAMA_URL`.

## Memoria degli atti già elaborati

Ogni documento scaricato e riassunto viene registrato in `stato_atti.json` (nella cartella di
lavoro). Alle esecuzioni successive i documenti già fatti vengono saltati del tutto — niente
download, OCR o riassunto — ma restano nella tabella HTML con il riassunto salvato.

- Il file viene aggiornato dopo ogni documento: se interrompi lo script non perdi il lavoro fatto.
- Se in un atto compare un **nuovo allegato** viene elaborato solo quello (la modale di ogni atto
  viene comunque aperta per accorgersene). Una nuova versione di un documento conta come nuova.
- `--ignora-stato true` rifà tutto (utile per confrontare un altro modello con `--modello`);
  `--stato ""` disattiva la memoria; `--stato altro.json` usa un file diverso.
- Eseguire prima solo il download e poi i riassunti funziona: il secondo giro riassume i file
  già scaricati senza riscaricarli.
- Per ripetere un solo documento basta cancellare la sua voce dal file JSON (o il file intero).
- Se il file di stato è illeggibile viene conservato come `stato_atti.json.corrotto` e si riparte da zero.

## PDF scansionati (OCR)

Se un PDF contiene solo l'immagine dell'atto (nessun testo), prima di riassumerlo le sue pagine
vengono lette con **Tesseract** (`--ocr true`, attivo di default). L'OCR parte solo per le pagine
senza testo, quindi i PDF normali non rallentano, e si ferma appena c'è abbastanza testo per il
riassunto (`MAX_CARATTERI`).

- Lingua: `--ocr-lingua ita` (default); per documenti misti `--ocr-lingua ita+eng`.
- Serve Tesseract con i dati della lingua (vedi Installazione).
- Per disattivarlo: `--ocr false` (le scansioni daranno un errore nel log, senza fermare il resto).
