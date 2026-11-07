# Scraper albo pretorio

Legge gli atti pubblicati sull'albo (cloud.urbi.it, Comune di Anguillara Sabazia, ma dovrebbe essere compatibili con tutti gli albi pretori che usano la piattaforma ministeriale cloud.urbi)
scarica i PDF allegati, li riassume con un LLM (Omlx oppure Ollama, scelto con `--provider`) e scrive una tabella HTML.
Opzioni complete: `python scraper_albo.py --help`.

## Installazione

Serve Python 3.10 o successivo (su Mac: `brew install python@3.12`).

```bash
python3 -m venv .venv
source .venv/bin/activate                 # da rifare in ogni nuovo terminale
python -m pip install -r requirements.txt
playwright install chromium               # una volta sola
brew install tesseract tesseract-lang     # OCR dei PDF scansionati (macOS)
# riassunti: Omlx (predefinito) oppure Ollama
#   Omlx: server attivo su OMLX_URL (default http://127.0.0.1:8000/v1) e chiave in
#         OMLX_API_KEY (obbligatoria, mai nel codice): export OMLX_API_KEY="..."
#   Ollama: ollama pull <modello> e Ollama attivo (nessuna chiave)
```

Su Debian/Ubuntu al posto di brew: `apt install tesseract-ocr tesseract-ocr-ita`.

## Uso

```bash
usage: scraper_albo.py [-h] [--livello-log {debug,info,error}]
                       [--log {console,file,entrambi}] [--debug [true|false]]
                       [--tui [true|false]] [--scarica [true|false]]
                       [--file-log FILE_LOG] [--output OUTPUT]
                       [--cartella CARTELLA] [--headless [true|false]]
                       [--url URL] [--dal DAL] [--al AL] [--max-atti N]
                       [--max-pagine N]
                       [--campo {data_inizio,data_fine,periodo}]
                       [--provider {omlx,ollama}] [--riassumi [true|false]]
                       [--modello MODELLO] [--stato FILE]
                       [--ignora-stato [true|false]] [--ocr [true|false]]
                       [--ocr-lingua LINGUA] [--ollama-url URL]
                       [--omlx-url URL] [--invia-mail [true|false]]
                       [--escludi DESCRIZIONE|PATTERN] [--diario [true|false]]

Scraper dell'albo pretorio: legge gli atti, ricava i link dei PDF,
li scarica e (opzionale) li riassume con un LLM (Omlx oppure Ollama).

opzioni principali:
  -h, --help            mostra questo messaggio ed esce
  --livello-log {debug,info,error}
                        livello minimo dei messaggi registrati (default: info)
  --log {console,file,entrambi}
                        dove scrivere il log (default: entrambi)
  --debug [true|false]  modalità debug: salva HTML e screenshot della tabella
                        (con la paginazione) e della modale della prima riga,
                        poi esce senza scaricare nulla (browser visibile se
                        c'è uno schermo) (default: False)
  --tui [true|false]    apre l'interfaccia a schermo intero: imposta i
                        parametri e avvia da lì (gli altri argomenti fanno da
                        valori iniziali) (default: False)
  --scarica [true|false]
                        scarica i PDF (false = stampa solo i link) (default:
                        True)

altre opzioni:
  --file-log FILE_LOG   nome del file di log (default: scraper_albo.log)
  --output OUTPUT       file HTML in cui scrivere la tabella finale (data,
                        titolo, link PDF, riassunto) (default:
                        tabella_atti.html)
  --cartella CARTELLA   cartella dei PDF scaricati (default: download_atti)
  --headless [true|false]
                        browser senza finestra (default: True)
  --url URL             indirizzo della pagina dell'albo (default: quello di
                        Anguillara Sabazia, impostato in config.py) (default:
                        None)
  --dal DAL             filtro data: da (GG-MM-AAAA o 'oggi') (default: None)
  --al AL               filtro data: a (GG-MM-AAAA o 'oggi') (default: None)
  --max-atti N          elabora al massimo N atti, partendo dal più recente
                        per data dell'atto e passando alle pagine successive
                        se serve (dopo l'eventuale filtro --dal/--al; gli atti
                        già elaborati contano nel limite) (default: None)
  --max-pagine N        legge al massimo N pagine della tabella. Senza --max-
                        atti, --dal/--al né --max-pagine si legge solo la
                        prima pagina (default: None)
  --campo {data_inizio,data_fine,periodo}
                        campo su cui applicare il filtro per data (default:
                        data_inizio)
  --provider {omlx,ollama}
                        modalità da usare per i riassunti: omlx (API OpenAI-
                        compatibile, limite 10000 caratteri) o ollama (modello
                        locale, limite 12000 caratteri) (default: omlx)
  --riassumi [true|false]
                        riassume ogni PDF scaricato (richiede --scarica true)
                        - testo limitato a 12000 caratteri per default con
                        Ollama locale o 10000 caratteri con Omlx (come scelto
                        con --provider) (default: False)
  --modello MODELLO     modello LLM da usare per i riassunti (default:
                        Qwen3.5-9B-MLX-4bit con --provider omlx, llama3.1:8b
                        con --provider ollama) (default: None)
  --stato FILE          file JSON che ricorda i documenti già scaricati e
                        riassunti, per non rifarli (stringa vuota = non usare
                        la memoria) (default: stato_atti.json)
  --ignora-stato [true|false]
                        rifà tutto anche per i documenti già registrati (il
                        file di stato viene comunque aggiornato) (default:
                        False)
  --ocr [true|false]    legge con l'OCR i PDF scansionati prima di riassumerli
                        (richiede Tesseract) (default: True)
  --ocr-lingua LINGUA   lingua/e di Tesseract per l'OCR, es. ita oppure
                        ita+eng (default: ita)
  --ollama-url URL      indirizzo del server Ollama (default: variabile
                        d'ambiente OLLAMA_URL, altrimenti locale) (default:
                        http://localhost:11434)
  --omlx-url URL        indirizzo base dell'API Omlx, OpenAI-compatibile
                        (default: variabile d'ambiente OMLX_URL, altrimenti
                        locale) (default: http://127.0.0.1:8000/v1)
  --invia-mail [true|false]
                        invia una mail con la tabella finale in allegato
                        (destinatari in receipts.txt, password SMTP nella
                        variabile d'ambiente SMTP_PASSWORD) (default: True)
  --escludi DESCRIZIONE|PATTERN
                        descrizione di un allegato da escludere, come appare
                        nella modale (si può ripetere); il confronto ignora
                        maiuscole/minuscole e spazi e `*` vale come jolly (es.
                        "*matrimonio*"); si aggiunge a quelle già escluse:
                        VISTO CONTABILE PER LIQUIDAZIONI (default: None)
  --diario [true|false]
                        non fa scraping: crea un diario in linguaggio semplice
                        (testo del provider LLM + tabella) a partire dal file
                        --output già prodotto e lo salva come diario_atti.html
                        nella stessa cartella. Usa --provider, --modello e
                        l'URL del provider; non invia la mail (default: False)

esempi:
  python scraper_albo.py                                  link + download dei PDF (prima pagina)
  python scraper_albo.py --scarica false                  solo link, niente download
  python scraper_albo.py --max-atti 25                    i 25 atti più recenti (scorre le pagine)
  python scraper_albo.py --max-pagine 3                   solo le prime 3 pagine della tabella
  python scraper_albo.py --dal 01-10-2026 --al oggi       solo gli atti in quell'intervallo
  python scraper_albo.py --riassumi true                  riassunti con Omlx (provider predefinito)
  python scraper_albo.py --riassumi true --provider ollama
                                                          riassunti con Ollama e il modello locale
  python scraper_albo.py --riassumi true --provider ollama --modello gemma3:12b
                                                          riassunti con un modello Ollama a scelta
  python scraper_albo.py --escludi "VISTO CONTABILE PER IMPEGNI"
                                                          esclude anche questo tipo di allegato
  python scraper_albo.py --escludi "*matrimonio*"         esclude ogni allegato che contiene
                                                          "matrimonio" (maiuscole ignorate)
  python scraper_albo.py --invia-mail false               non invia la tabella per mail
  python scraper_albo.py --output risultati.html          nome del file HTML con la tabella finale
  python scraper_albo.py --diario --output risultati.html diario discorsivo dal file già prodotto
  python scraper_albo.py --livello-log debug --log file   log dettagliato solo su file
  python scraper_albo.py --debug true                     salva HTML/screenshot di tabella e modale
  python scraper_albo.py --tui                            interfaccia a schermo intero per impostare i parametri
  python scraper_albo.py --url https://cloud.urbi.it/...  albo di un altro ente
```

Il risultato è `tabella_atti.html` (cambia nome con `--output`); PDF e log finiscono nella
cartella di lavoro (`download_atti/`, `scraper_albo.log`). Il file di log viene ruotato quando
supera 5 MB e vengono conservate al massimo 3 copie (`scraper_albo.log.1`, `.2`, `.3`), così
non cresce all'infinito tra un'esecuzione e l'altra.

### Interfaccia a schermo intero (TUI)

```bash
python scraper_albo.py --tui
```

Apre una schermata unica: a sinistra il modulo con tutti i parametri, a destra il log in
diretta (oltre che sul file di log). La modalità si sceglie in alto:

| Modalità | Cosa fa |
|---|---|
| **Scraping** | legge gli atti, scarica i PDF, li riassume (se attivo) e scrive la tabella |
| **Diario** | crea `diario_atti.html` dalla tabella già prodotta (come `--diario`) |
| **Debug** | salva HTML e screenshot di tabella e modale (come `--debug`) |

Il modulo mostra solo i campi utili alla modalità scelta. «Avvia» esegue il lavoro in un thread
separato, quindi la finestra resta reattiva e il log continua a scorrere. Al termine «Apri
tabella» apre nel browser il file prodotto.

- `Ctrl+R` avvia, `Ctrl+O` apre la tabella, `Ctrl+Q` esce.
- Il cursore parte dal primo campo: si può scrivere subito. `Tab` passa al campo
  successivo (il modulo scorre da solo per mostrarlo), `Pag↑`/`Pag↓` o la rotellina
  scorrono il modulo; i tre pulsanti restano sempre visibili in basso.
- Gli altri argomenti fanno da valori iniziali: ad esempio
  `python scraper_albo.py --tui --provider ollama --modello gemma3:12b`.
- «Allegati da escludere» accetta una voce per riga, con lo stesso significato di `--escludi`
  (il jolly `*` è supportato: `*matrimonio*`).
- La TUI richiede la libreria **Textual**, già compresa in `requirements.txt`; se manca, il
  programma lo segnala con il comando da eseguire.
- Serve un terminale vero (Terminale, iTerm2, VS Code con terminale integrato…). Se lo standard
  input non è un terminale — pannello di output di un IDE, `--tui < /dev/null`, processo in
  background — la schermata si disegnerebbe ma non risponderebbe a mouse e tastiera: in quel
  caso il programma ora esce subito spiegando il motivo.

### Provider LLM (Omlx / Ollama)

I riassunti e il diario usano il provider scelto con `--provider`:

- **`omlx`** (predefinito): API OpenAI-compatibile. Server e modello predefiniti si cambiano con
  `--omlx-url URL` / `--modello NOME` oppure con le variabili d'ambiente `OMLX_URL`,
  `OMLX_API_KEY` e `MODELLO_OMLX`. Il testo inviato è limitato a 10000 caratteri.
  `OMLX_API_KEY` è **obbligatoria** e non va mai scritta nel codice né in un file versionato:

  ```bash
  export OMLX_API_KEY="la-tua-chiave"   # da rifare in ogni nuovo terminale
  ```

  Senza chiave il provider `omlx` si ferma con un messaggio esplicito, senza inviare
  richieste.
- **`ollama`**: modello locale. Server e modello si cambiano con `--ollama-url URL` / `--modello NOME`
  oppure con `OLLAMA_URL` e `MODELLO_LOCALE`. Il testo inviato è limitato a 12000 caratteri.
  Non richiede chiavi.

Esempi:

```bash
python scraper_albo.py --riassumi true                        # Omlx (predefinito)
python scraper_albo.py --riassumi true --provider ollama      # Ollama
python scraper_albo.py --riassumi true --provider ollama --modello gemma3:12b
python scraper_albo.py --diario --output tabella_atti.html    # diario con il provider scelto
```

## Memoria degli atti già elaborati

Ogni documento scaricato e riassunto viene registrato in `stato_atti.json` (nella cartella di
lavoro). Alle esecuzioni successive i documenti già fatti vengono saltati del tutto — niente
download, OCR o riassunto — ma restano nella tabella HTML con il riassunto salvato.

- Il file viene riscritto ogni pochi documenti (5 per default) e comunque alla fine
  dell'esecuzione, anche se viene interrotta con un errore o Ctrl-C: puoi perdere al massimo
  gli ultimi aggiornamenti del blocco in corso, non tutto il lavoro fatto.
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
riassunto (il limite è 10000 caratteri con Omlx e 12000 con Ollama).

- Lingua: `--ocr-lingua ita` (default); per documenti misti `--ocr-lingua ita+eng`.
- Serve Tesseract con i dati della lingua (vedi Installazione).
- Per disattivarlo: `--ocr false` (le scansioni daranno un errore nel log, senza fermare il resto).

## Notifiche via email

Notifiche via Email
Attivando l'opzione --invia-mail, lo script invierà automaticamente il file HTML generato (il report degli atti) a tutti i destinatari elencati in un file locale.

**Configurazione:**

Destinatari: Crea un file chiamato receipts.txt nella cartella principale del progetto. Ogni riga deve contenere un indirizzo email valido (es. utente@esempio.it). Il file è escluso da git (`.gitignore`).
Server SMTP: Il software utilizza un server SMTP per l'invio. Server, porta, utente e mittente si impostano in `config.py`; la password va **solo** nella variabile d'ambiente `SMTP_PASSWORD` (mai nel codice):

```bash
export SMTP_PASSWORD="la-password-o-app-password"
```
Sicurezza: Se utilizzi servizi come Gmail o Outlook, è necessario generare una Password per le App (App Password) per consentire all'applicazione di inviare email.

