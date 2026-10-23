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
usage: scraper_albo.py [-h] [--livello-log {debug,info,error}] [--log {console,file,entrambi}] [--debug [true|false]] [--scarica [true|false]] [--file-log FILE_LOG] [--output OUTPUT]
                       [--cartella CARTELLA] [--headless [true|false]] [--dal DAL] [--al AL] [--campo {data_inizio,data_fine,periodo}] [--riassumi [true|false]] [--modello MODELLO]
                       [--stato FILE] [--ignora-stato [true|false]] [--ocr [true|false]] [--ocr-lingua LINGUA] [--ollama-url URL] [--escludi DESCRIZIONE] [--max-atti MAX_ATTI]

Scraper dell'albo pretorio: legge gli atti, ricava i link dei PDF,
li scarica e (opzionale) li riassume con un LLM locale (Ollama).

options:
  -h, --help            show this help message and exit

opzioni principali:
  --livello-log {debug,info,error}
                        livello minimo dei messaggi registrati (default: info)
  --log {console,file,entrambi}
                        dove scrivere il log (default: entrambi)
  --debug [true|false]  modalità debug: salva HTML e screenshot della modale della prima riga ed esce, senza scaricare nulla (browser visibile se c'è uno schermo) (default: False)
  --scarica [true|false]
                        scarica i PDF (false = stampa solo i link) (default: True)

altre opzioni:
  --file-log FILE_LOG   nome del file di log (default: scraper_albo.log)
  --output OUTPUT       file HTML in cui scrivere la tabella finale (data, titolo, link PDF, riassunto) (default: tabella_atti.html)
  --cartella CARTELLA   cartella dei PDF scaricati (default: download_atti)
  --headless [true|false]
                        browser senza finestra (default: True)
  --dal DAL             filtro data: da (GG-MM-AAAA o 'oggi') (default: None)
  --al AL               filtro data: a (GG-MM-AAAA o 'oggi') (default: None)
  --campo {data_inizio,data_fine,periodo}
                        campo su cui applicare il filtro per data (default: data_inizio)
  --riassumi [true|false]
                        riassume ogni PDF scaricato (richiede --scarica true) (default: False)
  --modello MODELLO     modello Ollama usato per i riassunti con --riassumi true (nome come in ollama list, es. gemma3:12b) (default: llama3.1:8b)
  --stato FILE          file JSON che ricorda i documenti già scaricati e riassunti, per non rifarli (stringa vuota = non usare la memoria) (default: stato_atti.json)
  --ignora-stato [true|false]
                        rifà tutto anche per i documenti già registrati (il file di stato viene comunque aggiornato) (default: False)
  --ocr [true|false]    legge con l'OCR i PDF scansionati prima di riassumerli (richiede Tesseract) (default: True)
  --ocr-lingua LINGUA   lingua/e di Tesseract per l'OCR, es. ita oppure ita+eng (default: ita)
  --ollama-url URL      indirizzo del server Ollama (default: variabile d'ambiente OLLAMA_URL, altrimenti locale) (default: http://localhost:11434)
  --escludi DESCRIZIONE
                        descrizione di un allegato da escludere, come appare nella modale (si può ripetere); si aggiunge a quelle già escluse: VISTO CONTABILE PER LIQUIDAZIONI (default:
                        None)
  --max-atti MAX_ATTI   Numero massimo di atti da processare (dal più recente) (default: None)
  --invia-mail          invia una mail con l'allegato alla tabella finale (default: False)

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
  python scraper_albo.py --max-atti 5 --invia-mail         processa gli ultimi 5 atti e invia la mail

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

## Notifiche via email

Notifiche via Email
Attivando l'opzione --invia-mail, lo script invierà automaticamente il file HTML generato (il report degli atti) a tutti i destinatari elencati in un file locale.

**Configurazione:**

Destinatari: Crea un file chiamato receipts.txt nella cartella principale del progetto. Ogni riga deve contenere un indirizzo email valido (es. utente@esempio.it).
Server SMTP: Il software utilizza un server SMTP per l'invio. Assicurati di configurare correttamente le credenziali (server, porta, utente e password) nel codice o nelle variabili d'ambiente.
Sicurezza: Se utilizzi servizi come Gmail o Outlook, è necessario generare una Password per le App (App Password) per consentire all'applicazione di inviare email.

