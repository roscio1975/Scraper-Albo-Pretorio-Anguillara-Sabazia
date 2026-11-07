"""Interfaccia a schermo intero (TUI) per impostare i parametri e avviare lo scraper.

Si apre con `python scraper_albo.py --tui` e richiede la libreria Textual (vedi
requirements.txt). I valori iniziali sono quelli degli altri argomenti da riga di
comando; il pulsante "Avvia" li traduce in argomenti e chiama la stessa funzione
usata dalla CLI (`cli._esegui`), quindi il comportamento è identico.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import threading
import webbrowser
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    TextArea,
)

from .cli import _esegui, _leggi_argomenti
from .config import (
    LOG_FILE,
    MODELLO_LOCALE,
    MODELLO_OMLX,
    OCR_LINGUA,
    OLLAMA_URL,
    OMLX_URL,
    STATO_FILE,
)
from .log import configura_logging, logger

MODALITA = (
    ("Scraping: leggi atti e PDF", "scraping"),
    ("Diario: da una tabella già prodotta", "diario"),
    ("Debug: salva HTML e screenshot", "debug"),
)
PROVIDER = (
    ("Omlx (API OpenAI-compatibile)", "omlx"),
    ("Ollama (modello locale)", "ollama"),
)
CAMPI_DATA = (
    ("Data inizio pubblicazione", "data_inizio"),
    ("Data fine pubblicazione", "data_fine"),
    ("Periodo di pubblicazione", "periodo"),
)
LIVELLI = (("debug", "debug"), ("info", "info"), ("error", "error"))

_CHECKBOX = (
    "scarica",
    "riassumi",
    "ocr",
    "invia-mail",
    "headless",
    "ignora-stato",
)
_SELEZIONI = ("modalita", "provider", "campo", "livello-log")
_INPUT = (
    "modello",
    "dal",
    "al",
    "max-atti",
    "max-pagine",
    "output",
    "cartella",
    "stato",
    "ocr-lingua",
    "url",
    "omlx-url",
    "ollama-url",
    "file-log",
)

# Blocchi del modulo mostrati in base alla modalità scelta. Così i campi non
# serviti dalla modalità spariscono invece di restare lì disattivati.
_BLOCCHI = {
    "scraping": (
        "blocco-sito",
        "blocco-provider",
        "blocco-uscita",
        "blocco-file",
        "blocco-scraping",
        "blocco-filtri",
        "blocco-server",
        "blocco-log",
        "blocco-escludi",
    ),
    "diario": ("blocco-provider", "blocco-uscita", "blocco-server", "blocco-log"),
    "debug": ("blocco-sito", "blocco-log"),
}
_ID_BLOCCHI = (
    "blocco-sito",
    "blocco-provider",
    "blocco-uscita",
    "blocco-file",
    "blocco-scraping",
    "blocco-filtri",
    "blocco-server",
    "blocco-log",
    "blocco-escludi",
)

_STILI_LIVELLO = {
    logging.DEBUG: "dim",
    logging.INFO: "",
    logging.WARNING: "yellow",
    logging.ERROR: "bold red",
    logging.CRITICAL: "bold red",
}


def _vero_falso(valore: bool) -> str:
    return "true" if valore else "false"


def _testo(valori: Mapping[str, Any], chiave: str) -> str:
    valore = valori.get(chiave, "")
    return "" if valore is None else str(valore).strip()


def _booleano(valori: Mapping[str, Any], chiave: str) -> bool:
    valore = valori.get(chiave, False)
    if isinstance(valore, str):
        return valore.strip().lower() in ("true", "t", "1", "si", "sì", "s", "yes", "y")
    return bool(valore)


def _intero(valore: str, etichetta: str) -> int:
    try:
        numero = int(valore)
    except ValueError:
        raise ValueError(f"{etichetta}: serve un numero intero (trovato {valore!r})") from None
    if numero < 1:
        raise ValueError(f"{etichetta}: il numero deve essere almeno 1")
    return numero


def _data(valore: str, etichetta: str) -> date:
    if valore.lower() == "oggi":
        return date.today()
    try:
        return datetime.strptime(valore, "%d-%m-%Y").date()
    except ValueError:
        raise ValueError(
            f"{etichetta}: data non valida ({valore!r}); usa GG-MM-AAAA oppure 'oggi'"
        ) from None


def costruisci_argv(valori: Mapping[str, Any]) -> list[str]:
    """
    Traduce i valori del modulo (dizionario id -> valore) negli argomenti della CLI.

    Funzione pura, senza Textual: serve anche ai test. Solleva ValueError con un
    messaggio in italiano se un valore non va bene; i controlli sono gli stessi
    della CLI (date, numeri, «riassumi» che richiede «scarica»).
    """
    modalita = _testo(valori, "modalita") or "scraping"
    if modalita not in ("scraping", "diario", "debug"):
        raise ValueError(f"modalità sconosciuta: {modalita!r}")

    argv: list[str] = []
    if modalita == "debug":
        argv += ["--debug", "true"]
    elif modalita == "diario":
        argv += ["--diario", "true"]

    provider = _testo(valori, "provider") or "omlx"
    if provider not in ("omlx", "ollama"):
        raise ValueError(f"provider sconosciuto: {provider!r}")
    argv += ["--provider", provider]

    modello = _testo(valori, "modello")
    if modello:
        argv += ["--modello", modello]

    if modalita != "debug":
        output = _testo(valori, "output")
        if not output:
            raise ValueError("Il file di output non può essere vuoto")
        argv += ["--output", output]

    url = _testo(valori, "url")
    if url:
        argv += ["--url", url]

    for chiave, opzione in (("omlx-url", "--omlx-url"), ("ollama-url", "--ollama-url")):
        valore = _testo(valori, chiave)
        if valore:
            argv += [opzione, valore]

    if modalita == "debug":
        argv += ["--headless", _vero_falso(_booleano(valori, "headless"))]
        return argv

    if modalita == "diario":
        return argv

    scarica = _booleano(valori, "scarica")
    riassumi = _booleano(valori, "riassumi")
    if riassumi and not scarica:
        raise ValueError(
            "«Riassumi» richiede «Scarica i PDF»: attiva lo scaricamento "
            "oppure disattiva i riassunti"
        )

    for chiave in ("scarica", "riassumi", "ocr", "invia-mail", "headless", "ignora-stato"):
        argv += [f"--{chiave}", _vero_falso(_booleano(valori, chiave))]

    campo = _testo(valori, "campo") or "data_inizio"
    if campo not in ("data_inizio", "data_fine", "periodo"):
        raise ValueError(f"campo data sconosciuto: {campo!r}")
    argv += ["--campo", campo]

    dal = _testo(valori, "dal")
    al = _testo(valori, "al")
    data_dal = _data(dal, "Data iniziale") if dal else None
    data_al = _data(al, "Data finale") if al else None
    if data_dal and data_al and data_dal > data_al:
        raise ValueError("La data iniziale è successiva alla data finale")
    if dal:
        argv += ["--dal", dal]
    if al:
        argv += ["--al", al]

    for chiave, etichetta in (
        ("max-atti", "Numero massimo di atti"),
        ("max-pagine", "Numero massimo di pagine"),
    ):
        valore = _testo(valori, chiave)
        if valore:
            argv += [f"--{chiave}", str(_intero(valore, etichetta))]

    cartella = _testo(valori, "cartella")
    if not cartella:
        raise ValueError("La cartella dei PDF non può essere vuota")
    argv += ["--cartella", cartella]

    # stringa vuota = nessuna memoria (come `--stato ""` da riga di comando)
    argv += ["--stato", _testo(valori, "stato")]

    lingua = _testo(valori, "ocr-lingua")
    if lingua:
        argv += ["--ocr-lingua", lingua]

    for riga in _testo(valori, "escludi").splitlines():
        riga = riga.strip()
        if riga:
            argv += ["--escludi", riga]

    return argv


def costruisci_argomenti(valori: Mapping[str, Any]) -> argparse.Namespace:
    """Come `costruisci_argv`, ma restituisce il Namespace pronto per `_esegui`."""
    return _leggi_argomenti(costruisci_argv(valori))


class _HandlerRichLog(logging.Handler):
    """Porta i messaggi di log nel pannello RichLog della TUI (da qualunque thread)."""

    def __init__(self, app: TuiAlbo, livello: int) -> None:
        super().__init__(livello)
        self.app = app
        self._thread = threading.get_ident()  # thread in cui gira l'app Textual
        self.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-5s | %(message)s", "%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            testo = self.format(record)
            if record.exc_info:
                testo = f"{testo}\n{self.formatException(record.exc_info)}"
            if threading.get_ident() == self._thread:
                self.app._scrivi(testo, record.levelno)
            else:
                self.app.call_from_thread(self.app._scrivi, testo, record.levelno)
        except Exception:  # noqa: BLE001 - il logging non deve mai far cadere l'app
            pass


class TuiAlbo(App[None]):
    """Schermata unica: modulo dei parametri a sinistra, log in diretta a destra."""

    TITLE = "Scraper Albo Pretorio"
    SUB_TITLE = "Anguillara Sabazia"
    CSS = """
    Screen {
        layout: vertical;
    }

    #corpo {
        height: 1fr;
    }

    #modulo {
        width: 60;
        height: 1fr;
        border: round $primary;
        padding: 1 2;
        scrollbar-size-vertical: 1;
    }

    #modulo Checkbox {
        margin-bottom: 1;
    }

    #modulo Input {
        margin-bottom: 1;
    }

    #modulo Select {
        margin-bottom: 1;
    }

    #modulo TextArea {
        height: 7;
        margin-bottom: 1;
    }

    .etichetta {
        margin-top: 1;
        color: $text-muted;
    }

    .blocco {
        height: auto;
    }

    .intestazione {
        text-style: bold;
        color: $accent;
        margin-top: 2;
    }

    #destra {
        width: 1fr;
        height: 1fr;
    }

    #log {
        height: 1fr;
        border: round $primary;
        padding: 0 1;
        scrollbar-size-vertical: 1;
    }

    #esito {
        height: 2;
        padding: 0 1;
        color: $text-muted;
    }

    #barra {
        height: auto;
        padding: 1 2;
        align: left middle;
    }

    #barra Button {
        margin-right: 2;
    }
    """
    BINDINGS = [
        ("ctrl+r", "avvia", "Avvia"),
        ("ctrl+o", "apri_tabella", "Apri tabella"),
        ("ctrl+q", "quit", "Esci"),
    ]

    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__()
        self._iniziale = args
        self._in_corso = False
        self._ultimo_file: Path | None = None

    # --- costruzione dell'interfaccia -------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="corpo"):
            with VerticalScroll(id="modulo"):
                yield Label("Modalità", classes="etichetta")
                yield Select(MODALITA, value="scraping", allow_blank=False, id="modalita")

                with Vertical(classes="blocco", id="blocco-sito"):
                    yield Label("Sito", classes="intestazione")
                    yield Label(
                        "Indirizzo dell'albo (vuoto = Anguillara Sabazia)",
                        classes="etichetta",
                    )
                    yield Input(placeholder="https://cloud.urbi.it/...", id="url")
                    yield Checkbox("Browser senza finestra (headless)", value=True, id="headless")

                with Vertical(classes="blocco", id="blocco-provider"):
                    yield Label("Provider LLM", classes="intestazione")
                    yield Select(PROVIDER, value="omlx", allow_blank=False, id="provider")
                    yield Label("Modello (vuoto = predefinito del provider)", classes="etichetta")
                    yield Input(placeholder=MODELLO_OMLX, id="modello")

                with Vertical(classes="blocco", id="blocco-uscita"):
                    yield Label("Tabella in uscita", classes="intestazione")
                    yield Label("File HTML in cui scrivere la tabella", classes="etichetta")
                    yield Input(value="tabella_atti.html", id="output")

                with Vertical(classes="blocco", id="blocco-file"):
                    yield Label("File e cartelle", classes="intestazione")
                    yield Label("Cartella dei PDF scaricati", classes="etichetta")
                    yield Input(value="download_atti", id="cartella")
                    yield Label("Memoria degli atti (vuoto = nessuna memoria)", classes="etichetta")
                    yield Input(value=STATO_FILE, id="stato")
                    yield Label("Lingua OCR (es. ita oppure ita+eng)", classes="etichetta")
                    yield Input(value=OCR_LINGUA, id="ocr-lingua")

                with Vertical(classes="blocco", id="blocco-scraping"):
                    yield Label("Scraping", classes="intestazione")
                    yield Checkbox("Scarica i PDF", value=True, id="scarica")
                    yield Checkbox("Riassumi i PDF con l'LLM", value=False, id="riassumi")
                    yield Checkbox("OCR dei PDF scansionati (Tesseract)", value=True, id="ocr")
                    yield Checkbox("Invia la tabella per mail", value=True, id="invia-mail")
                    yield Checkbox(
                        "Ignora la memoria degli atti già fatti", value=False, id="ignora-stato"
                    )

                with Vertical(classes="blocco", id="blocco-filtri"):
                    yield Label("Filtri e quantità", classes="intestazione")
                    yield Label("Data iniziale (GG-MM-AAAA oppure 'oggi')", classes="etichetta")
                    yield Input(placeholder="GG-MM-AAAA oppure oggi", id="dal")
                    yield Label("Data finale (GG-MM-AAAA oppure 'oggi')", classes="etichetta")
                    yield Input(placeholder="GG-MM-AAAA oppure oggi", id="al")
                    yield Label("Campo su cui filtrare le date", classes="etichetta")
                    yield Select(CAMPI_DATA, value="data_inizio", allow_blank=False, id="campo")
                    yield Label(
                        "Numero massimo di atti (vuoto = nessun limite)", classes="etichetta"
                    )
                    yield Input(placeholder="es. 25", id="max-atti")
                    yield Label(
                        "Numero massimo di pagine (vuoto = nessun limite)", classes="etichetta"
                    )
                    yield Input(placeholder="es. 3", id="max-pagine")

                with Vertical(classes="blocco", id="blocco-server"):
                    yield Label("Server LLM", classes="intestazione")
                    yield Label("URL Omlx (API OpenAI-compatibile)", classes="etichetta")
                    yield Input(value=OMLX_URL, id="omlx-url")
                    yield Label("URL Ollama", classes="etichetta")
                    yield Input(value=OLLAMA_URL, id="ollama-url")

                with Vertical(classes="blocco", id="blocco-log"):
                    yield Label("Log", classes="intestazione")
                    yield Label("File di log", classes="etichetta")
                    yield Input(value=LOG_FILE, id="file-log")
                    yield Label("Livello dei messaggi", classes="etichetta")
                    yield Select(LIVELLI, value="info", allow_blank=False, id="livello-log")

                with Vertical(classes="blocco", id="blocco-escludi"):
                    yield Label(
                        "Allegati da escludere (uno per riga; * è un jolly)",
                        classes="intestazione",
                    )
                    yield TextArea(
                        placeholder="es. *matrimonio*\nVISTO CONTABILE PER IMPEGNI",
                        id="escludi",
                    )

            with Vertical(id="destra"):
                yield RichLog(id="log", wrap=True, highlight=False, markup=False, max_lines=2000)
                yield Static("Pronto.", id="esito", markup=False)

        with Horizontal(id="barra"):
            yield Button("Avvia", id="avvia", variant="primary")
            yield Button("Apri tabella", id="apri")
            yield Button("Esci", id="esci", variant="error")
        yield Footer()

    # --- avvio ------------------------------------------------------------

    def on_mount(self) -> None:
        self._applica_iniziali()
        try:
            self._configura_log()
        except OSError as errore:
            self._scrivi(f"Impossibile aprire il file di log: {errore}", logging.ERROR)
        self._aggiorna_modalita()
        self._scrivi(
            "Imposta i parametri e premi Avvia (Ctrl+R). Ctrl+Q per uscire.",
            logging.INFO,
        )
        self.query_one("#avvia", Button).focus()

    def _applica_iniziali(self) -> None:
        args = self._iniziale
        modalita = "debug" if args.debug else "diario" if args.diario else "scraping"
        self.query_one("#modalita", Select).value = modalita

        for chiave in _CHECKBOX:
            attributo = chiave.replace("-", "_")
            self.query_one(f"#{chiave}", Checkbox).value = bool(getattr(args, attributo))

        self.query_one("#provider", Select).value = args.provider
        self.query_one("#campo", Select).value = args.campo
        self.query_one("#livello-log", Select).value = args.livello_log

        testi = {
            "modello": args.modello or "",
            "dal": args.dal.strftime("%d-%m-%Y") if args.dal else "",
            "al": args.al.strftime("%d-%m-%Y") if args.al else "",
            "max-atti": args.max_atti or "",
            "max-pagine": args.max_pagine or "",
            "output": args.output,
            "cartella": args.cartella,
            "stato": args.stato or "",
            "ocr-lingua": args.ocr_lingua,
            "url": args.url or "",
            "omlx-url": args.omlx_url,
            "ollama-url": args.ollama_url,
            "file-log": args.file_log,
        }
        for chiave, valore in testi.items():
            self.query_one(f"#{chiave}", Input).value = str(valore)
        self.query_one("#escludi", TextArea).text = "\n".join(args.escludi or ())

    # --- valori del modulo e log -----------------------------------------

    def _valori(self) -> dict[str, Any]:
        valori: dict[str, Any] = {}
        for chiave in _CHECKBOX:
            valori[chiave] = self.query_one(f"#{chiave}", Checkbox).value
        for chiave in _SELEZIONI:
            valore = self.query_one(f"#{chiave}", Select).value
            valori[chiave] = "" if valore is Select.NULL else str(valore)
        for chiave in _INPUT:
            valori[chiave] = self.query_one(f"#{chiave}", Input).value
        valori["escludi"] = self.query_one("#escludi", TextArea).text
        return valori

    def _configura_log(self) -> None:
        livello = getattr(logging, str(self.query_one("#livello-log", Select).value).upper())
        file_log = self.query_one("#file-log", Input).value.strip()
        if not file_log:
            raise OSError("il file di log non può essere vuoto")
        for handler in logger.handlers:
            with contextlib.suppress(Exception):
                handler.close()
        configura_logging(
            file_log=file_log,
            livello_file=livello,
            console=False,
            livello_console=livello,
            su_file=True,
        )
        logger.addHandler(_HandlerRichLog(self, livello))

    def _scrivi(self, testo: str, livello: int = logging.INFO) -> None:
        try:
            pannello = self.query_one("#log", RichLog)
        except Exception:  # noqa: BLE001 - widget non ancora montato o app chiusa
            return
        pannello.write(Text(testo, style=_STILI_LIVELLO.get(livello, "")))

    # --- eventi -----------------------------------------------------------

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "modalita":
            self._aggiorna_modalita()
        elif event.select.id == "provider":
            self._aggiorna_placeholder_modello()

    def _aggiorna_placeholder_modello(self) -> None:
        provider = str(self.query_one("#provider", Select).value)
        modello = MODELLO_OMLX if provider == "omlx" else MODELLO_LOCALE
        self.query_one("#modello", Input).placeholder = modello

    def _aggiorna_modalita(self) -> None:
        modalita = str(self.query_one("#modalita", Select).value)
        visibili = _BLOCCHI.get(modalita, _BLOCCHI["scraping"])
        for blocco in _ID_BLOCCHI:
            self.query_one(f"#{blocco}").display = blocco in visibili
        self._aggiorna_placeholder_modello()

        suggerimenti = {
            "scraping": "Legge gli atti, scarica i PDF e scrive la tabella HTML.",
            "diario": "Crea diario_atti.html dalla tabella indicata in «Tabella HTML in uscita».",
            "debug": "Salva HTML e screenshot di tabella e modale, poi esce.",
        }
        self.query_one("#esito", Static).update(f"Modalità: {suggerimenti.get(modalita, '')}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "avvia":
            self.action_avvia()
        elif event.button.id == "apri":
            self.action_apri_tabella()
        elif event.button.id == "esci":
            self.exit()

    # --- azioni -----------------------------------------------------------

    def action_avvia(self) -> None:
        if self._in_corso:
            self.notify("Un'esecuzione è già in corso", severity="warning")
            return
        try:
            args = costruisci_argomenti(self._valori())
            self._configura_log()
        except ValueError as errore:
            self.notify(str(errore), severity="error", timeout=8)
            self._scrivi(f"Controlla i parametri: {errore}", logging.ERROR)
            return
        except OSError as errore:
            self.notify(f"File di log non valido: {errore}", severity="error", timeout=8)
            self._scrivi(f"File di log non valido: {errore}", logging.ERROR)
            return

        modo = "diario" if args.diario else "debug" if args.debug else "scraping"
        self._in_corso = True
        self.query_one("#avvia", Button).disabled = True
        self.query_one("#esito", Static).update(f"In corso: {modo}…")
        logger.info(f"Avvio dalla TUI ({modo})")
        self._lavora(args)

    @work(thread=True, exclusive=True, group="esecuzione")
    def _lavora(self, args: argparse.Namespace) -> None:
        """Esegue lo scraper fuori dal thread dell'app, così la TUI resta reattiva."""
        try:
            percorso = _esegui(args)
        except SystemExit as uscita:
            self._dal_thread(self._fine, None, f"Interrotto (codice {uscita.code})", True)
        except Exception as errore:  # noqa: BLE001 - l'errore è già nel log
            logger.error("Errore durante l'esecuzione", exc_info=True)
            self._dal_thread(self._fine, None, f"Errore: {errore}", True)
        else:
            # il diario restituisce None se la generazione non è riuscita
            fallito = percorso is None and not args.debug
            messaggio = "Operazione non riuscita (vedi log)" if fallito else "Completato"
            self._dal_thread(self._fine, percorso, messaggio, fallito)

    def _dal_thread(self, callback, *args) -> None:
        with contextlib.suppress(RuntimeError):
            # RuntimeError se l'app è già stata chiusa mentre il lavoro era in corso
            self.call_from_thread(callback, *args)

    def _fine(self, percorso: Path | None, messaggio: str, errore: bool) -> None:
        self._in_corso = False
        self.query_one("#avvia", Button).disabled = False
        if percorso is not None:
            self._ultimo_file = Path(percorso)
        # nel pannello solo il nome del file: i percorsi lunghi non stanno nella riga
        dettaglio = f" — {Path(percorso).name}" if percorso is not None else ""
        self.query_one("#esito", Static).update(f"{messaggio}{dettaglio}")
        self._scrivi(f"{messaggio}{dettaglio}", logging.ERROR if errore else logging.INFO)
        self.notify(messaggio, severity="error" if errore else "information")

    def action_apri_tabella(self) -> None:
        percorso = self._ultimo_file
        if percorso is None:
            # nessuna esecuzione in questa sessione: uso il file indicato nel modulo
            candidato = self.query_one("#output", Input).value.strip()
            if candidato and Path(candidato).is_file():
                percorso = Path(candidato)
        if percorso is None or not percorso.exists():
            self.notify("Nessuna tabella ancora prodotta", severity="warning")
            return
        webbrowser.open(percorso.resolve().as_uri())


def avvia_tui(args: argparse.Namespace) -> None:
    """Punto di ingresso usato da `cli.main` quando si passa `--tui`."""
    TuiAlbo(args).run()
