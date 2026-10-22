# Scraper albo pretorio

Legge gli atti pubblicati sull'albo (cloud.urbi.it, Comune di Anguillara Sabazia),
scarica i PDF allegati, li riassume con un LLM locale (Ollama) e scrive una tabella HTML.
Opzioni complete: `python scraper_albo.py --help`.

## Con Docker (consigliato)

L'immagine contiene Python, Chromium e il codice. **Ollama non è nell'immagine**:
deve girare sul computer host (su Mac usa la GPU solo se gira fuori da Docker).

```bash
docker build -t scraper-albo .

docker run --rm --init --shm-size=1g -v "$PWD/data:/data" \
  scraper-albo --riassumi true --modello gemma3:12b --dal oggi
```

Con `docker compose` (argomenti di default nel file `docker-compose.yml`):

```bash
docker compose run --rm scraper                        # usa il command del compose
docker compose run --rm scraper --scarica false        # altri argomenti sostituiscono il command
```

PDF, `tabella_atti.html` e `scraper_albo.log` compaiono in `./data`.

### Raggiungere Ollama dal container

L'immagine usa `OLLAMA_URL=http://host.docker.internal:11434` (si cambia con `-e OLLAMA_URL=...`
oppure con `--ollama-url`).

- **Docker Desktop (Mac/Windows)**: `host.docker.internal` esiste già e di solito funziona
  anche con Ollama in ascolto solo su localhost.
- **Linux**: aggiungi `--add-host=host.docker.internal:host-gateway` (il compose lo fa già)
  e avvia Ollama con `OLLAMA_HOST=0.0.0.0 ollama serve`.

### Note

- Il fuso orario del container è `Europe/Rome` (`-e TZ=...` per cambiarlo): conta per l'ora
  nei log e per `--dal oggi`.
- `--debug true` funziona anche nel container (parte senza finestra e salva HTML e screenshot).
- Le versioni di `playwright` e `pypdf` sono bloccate in `requirements.txt` (quelle con cui
  è stato provato il codice); aggiornale insieme e ricostruisci l'immagine.

## Senza Docker

```bash
pip install -r requirements.txt
playwright install chromium
brew install tesseract tesseract-lang     # OCR (macOS); su Debian/Ubuntu: apt install tesseract-ocr tesseract-ocr-ita
python scraper_albo.py --riassumi true --modello gemma3:12b
```

## PDF scansionati (OCR)

Se un PDF contiene solo l'immagine dell'atto (nessun testo), prima di riassumerlo le sue pagine
vengono lette con **Tesseract** (`--ocr true`, attivo di default). L'OCR parte solo per le pagine
senza testo, quindi i PDF normali non rallentano, e si ferma appena c'è abbastanza testo per il
riassunto (`MAX_CARATTERI`).

- Lingua: `--ocr-lingua ita` (default); per documenti misti `--ocr-lingua ita+eng`.
- Serve Tesseract con i dati della lingua: nell'immagine Docker sono già inclusi; su Mac
  `brew install tesseract tesseract-lang`.
- Per disattivarlo: `--ocr false` (le scansioni daranno un errore nel log, senza fermare il resto).
