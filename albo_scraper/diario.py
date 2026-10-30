"""
Diario in linguaggio semplice degli atti pubblicati.

Legge la tabella HTML già prodotta (--output), la fa riassumere a Ollama in forma discorsiva
e scrive una pagina `diario_atti.html` con il testo del diario seguito dalla tabella.
"""

from __future__ import annotations

import json
import re
from html import escape as esc_html
from html.parser import HTMLParser
from pathlib import Path

from .config import (
    COLONNE_TABELLA,
    LOGHI_DIARIO,
    MODELLO_LOCALE,
    NUM_CTX,
    NUM_CTX_DIARIO_MAX,
    OLLAMA_URL,
    PROMPT_DIARIO,
    SOTTOTITOLO_DIARIO,
    TITOLO_DIARIO,
    TITOLO_PAGINA_DIARIO,
)
from .log import logger
from .ollama import chiedi_a_ollama
from .report import CSS_TABELLA, VUOTO, Riga, pagina_html, tabella_html

FILE_DIARIO = "diario_atti.html"  # scritto nella stessa cartella del file della tabella
RE_DATA = re.compile(r"\d{2}-\d{2}-\d{4}")
CARATTERI_PER_TOKEN = 3  # stima prudente per l'italiano
TOKEN_PER_LA_RISPOSTA = 1024

CSS_DIARIO = """
h1 { font-size: 2.2rem; text-align: center; margin-bottom: .5rem; }
.sottotitolo { text-align: center; color: var(--muted); font-size: 1.1rem; margin: 0 0 1.5rem; }
.logos { display: flex; justify-content: center; align-items: center; gap: .5rem;
         margin-bottom: 1.5rem; }
.logo { width: 48px; height: auto; }
.diario { max-width: 1000px; margin: 0 auto 2rem; padding: 1rem 1.25rem;
          background: var(--testata); border-left: 3px solid var(--bordo);
          border-radius: 8px; font-style: italic; }
.diario p { margin: 0 0 .75rem; }
.diario ul { margin: 0 0 .75rem 1.25rem; padding: 0; }
.dettaglio h2 { text-align: center; margin: 2rem 0 1rem; }
"""

# Tabella del diario. Su schermi larghi: colonne a larghezza fissa, con il titolo stretto e a
# carattere più piccolo (il riassunto prende lo spazio rimasto). Sotto i 720 px: una "scheda"
# per atto al posto della tabella; le etichette delle schede (Data atto, Titolo atto...)
# vengono da COLONNE_TABELLA, al posto di {ETICHETTE}.
_CSS_TABELLA_DIARIO = """
.tabella-diario { --larghezza-titolo: 14%; }  /* colonna del titolo: aumenta per allargarla */
.tabella-diario .contenitore { max-width: 1000px; margin: 0 auto; }
.tabella-diario table { table-layout: fixed; min-width: 0; }
.tabella-diario th, .tabella-diario td { box-sizing: border-box; }
.tabella-diario th:nth-child(1), .tabella-diario td:nth-child(1) { width: 6.5rem; }
.tabella-diario th:nth-child(2), .tabella-diario td:nth-child(2) { width: var(--larghezza-titolo); }
.tabella-diario th:nth-child(3), .tabella-diario td:nth-child(3) { width: 5.5rem; }
.tabella-diario td.titolo { font-size: .8rem; line-height: 1.35; overflow-wrap: anywhere;
                            hyphens: auto; }
.tabella-diario td.riassunto { min-width: 0; overflow-wrap: anywhere; }

@media (max-width: 720px) {
  .tabella-diario .contenitore { border: none; overflow: visible; }
  .tabella-diario table, .tabella-diario tbody,
  .tabella-diario tr, .tabella-diario td { display: block; }
  .tabella-diario thead { position: absolute; width: 1px; height: 1px; overflow: hidden;
                          clip: rect(0 0 0 0); }
  .tabella-diario tr { border: 1px solid var(--bordo); border-radius: 8px;
                       padding: .5rem .85rem; margin-bottom: .75rem; }
  .tabella-diario td { width: auto !important; padding: .35rem 0; border: none;
                       white-space: normal; }
  .tabella-diario td::before { display: block; font-size: .7rem; font-weight: 600;
                               text-transform: uppercase; letter-spacing: .04em;
                               color: var(--muted); }
  .tabella-diario td.titolo { font-size: .95rem; }
  {ETICHETTE}
}
"""


def _css_tabella_diario() -> str:
    """CSS della tabella del diario, con le etichette delle colonne per la vista a schede."""
    classi = ("data", "titolo", "link", "riassunto")  # classi delle celle (vedi report.py)
    etichette = "\n  ".join(
        f'.tabella-diario td.{classe}::before {{ content: "{_testo_css(nome)}"; }}'
        for classe, nome in zip(classi, COLONNE_TABELLA)
    )
    return _CSS_TABELLA_DIARIO.replace("{ETICHETTE}", etichette)


def _testo_css(testo: str) -> str:
    """Testo adatto a una stringa CSS tra virgolette."""
    return testo.replace("\\", "\\\\").replace('"', '\\"')


# ------------------------------------------------------------ lettura della tabella
class _LettoreTabella(HTMLParser):
    """Raccoglie, per ogni <tr>, il testo e il primo link di ciascuna cella <td>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.righe: list[list[dict]] = []
        self._riga: list[dict] | None = None
        self._cella: dict | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "tr":
            self._riga = []
        elif tag == "td" and self._riga is not None:
            self._cella = {"testo": [], "href": ""}
        elif tag == "a" and self._cella is not None and not self._cella["href"]:
            self._cella["href"] = dict(attrs).get("href") or ""

    def handle_data(self, data: str) -> None:
        if self._cella is not None:
            self._cella["testo"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._cella is not None and self._riga is not None:
            self._riga.append(
                {"testo": "".join(self._cella["testo"]), "href": self._cella["href"]}
            )
            self._cella = None
        elif tag == "tr" and self._riga is not None:
            if self._riga:  # le righe dell'intestazione hanno <th>, non <td>
                self.righe.append(self._riga)
            self._riga = None


def _su_una_riga(testo: str) -> str:
    return " ".join(testo.split())


def _righe_pulite(testo: str) -> str:
    """Mantiene gli a capo, ma toglie spazi e righe vuote in eccesso."""
    return "\n".join(_su_una_riga(r) for r in testo.splitlines() if r.strip())


def leggi_atti_da_html(percorso: str | Path) -> list[dict]:
    """
    Legge la tabella scritta da `scrivi_tabella` e restituisce una lista di dict con le chiavi
    data, titolo, link e riassunto ("—" se il riassunto manca). Non serve un browser.
    """
    lettore = _LettoreTabella()
    lettore.feed(Path(percorso).read_text(encoding="utf-8"))

    atti = []
    for celle in lettore.righe:
        if len(celle) < 4 or not RE_DATA.search(celle[0]["testo"]):
            continue  # non è una riga di atti
        atti.append(
            {
                "data": _su_una_riga(celle[0]["testo"]),
                "titolo": _su_una_riga(celle[1]["testo"]),
                "link": celle[2]["href"],
                "riassunto": _righe_pulite(celle[3]["testo"]),
            }
        )
    return atti


# ------------------------------------------------------------------ chiamata a Ollama
def _atti_che_entrano_nel_contesto(atti: list[dict]) -> list[dict]:
    """
    Se gli atti non entrano nella finestra di contesto massima ne tiene solo i primi (i più
    recenti): oltre il limite Ollama taglierebbe in silenzio l'inizio del prompt, cioè le istruzioni.
    """
    budget = (NUM_CTX_DIARIO_MAX - TOKEN_PER_LA_RISPOSTA) * CARATTERI_PER_TOKEN - len(PROMPT_DIARIO)
    scelti, usati = [], 0
    for atto in atti:
        costo = len(json.dumps(atto, ensure_ascii=False)) + 1
        if usati + costo > budget:
            break
        scelti.append(atto)
        usati += costo
    if len(scelti) < len(atti):
        logger.warning(
            f"Troppi atti per il contesto del modello: nel diario ne uso {len(scelti)} su "
            f"{len(atti)} (i più recenti). Riduci --max-atti o aumenta NUM_CTX_DIARIO_MAX."
        )
    return scelti


def _genera_testo_diario(atti: list[dict], modello: str, ollama_url: str) -> str:
    dati = "\n".join(json.dumps(a, ensure_ascii=False) for a in atti)
    prompt = PROMPT_DIARIO.replace("{dati_atti}", dati)

    token_stimati = len(prompt) // CARATTERI_PER_TOKEN + TOKEN_PER_LA_RISPOSTA
    num_ctx = min(max(NUM_CTX, token_stimati), NUM_CTX_DIARIO_MAX)

    logger.info(f"Invio a Ollama ({modello}) la richiesta del diario per {len(atti)} atti...")
    return chiedi_a_ollama(prompt, modello, ollama_url, num_ctx=num_ctx, timeout=900)


# ----------------------------------------------------------------------- pagina HTML
def _inline(testo: str) -> str:
    """Testo "escapato" con il grassetto Markdown (**testo**) convertito in <strong>."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc_html(testo))


def testo_a_html(testo: str) -> str:
    """
    Converte il testo del modello in HTML sicuro: tutto il contenuto viene "escapato" e si
    riconoscono solo paragrafi, elenchi puntati (- / * / •), titoli (#) e grassetto (**).
    """
    blocchi: list[str] = []
    in_elenco = False

    for riga in testo.splitlines():
        riga = riga.strip()
        voce = re.match(r"^[-*•]\s+(.*)$", riga)
        titolo = re.match(r"^#{1,6}\s+(.*)$", riga)

        if voce:
            if not in_elenco:
                blocchi.append("<ul>")
                in_elenco = True
            blocchi.append(f"<li>{_inline(voce.group(1))}</li>")
            continue

        if in_elenco:
            blocchi.append("</ul>")
            in_elenco = False
        if titolo:
            blocchi.append(f"<p><strong>{_inline(titolo.group(1))}</strong></p>")
        elif riga:
            blocchi.append(f"<p>{_inline(riga)}</p>")

    if in_elenco:
        blocchi.append("</ul>")
    return "\n".join(blocchi)


def _pagina_diario(testo_diario: str, atti: list[dict]) -> str:
    righe = [Riga(a["data"], a["titolo"], a["link"], a["riassunto"]) for a in atti]
    loghi = "".join(
        f'<img src="{esc_html(url, quote=True)}" alt="{esc_html(alt, quote=True)}" class="logo">'
        for url, alt in LOGHI_DIARIO
    )
    corpo = (
        (f'<div class="logos">{loghi}</div>\n' if loghi else "")
        + f"<h1>{esc_html(TITOLO_DIARIO)}</h1>\n"
        + f'<p class="sottotitolo">{esc_html(SOTTOTITOLO_DIARIO)}</p>\n'
        + f'<div class="diario">\n{testo_a_html(testo_diario) or VUOTO}\n</div>\n'
        + '<div class="dettaglio"><h2>Dettaglio degli atti</h2></div>\n'
        + f'<div class="tabella-diario">\n{tabella_html(righe)}\n</div>'
    )
    css = CSS_TABELLA + CSS_DIARIO + _css_tabella_diario()
    return pagina_html(TITOLO_PAGINA_DIARIO, corpo, css)


# ------------------------------------------------------------------------- principale
def crea_diario_html(
    percorso: str | Path,
    modello: str = MODELLO_LOCALE,
    ollama_url: str = OLLAMA_URL,
) -> Path | None:
    """
    Crea `diario_atti.html` (nella cartella di `percorso`) a partire dalla tabella HTML
    `percorso`. Restituisce il percorso del diario, oppure None se non è stato possibile
    crearlo (il motivo è nel log).
    """
    if not percorso:
        raise ValueError("Serve un percorso HTML valido per la generazione del diario.")
    percorso = Path(percorso)
    if not percorso.exists():
        logger.error(f"File HTML non trovato: {percorso}")
        return None

    atti = leggi_atti_da_html(percorso)
    if not atti:
        logger.warning(f"Nessun atto trovato in {percorso}")
        return None
    atti = _atti_che_entrano_nel_contesto(atti)

    try:
        testo_diario = _genera_testo_diario(atti, modello, ollama_url)
    except Exception as e:
        logger.error(f"Errore nella chiamata a Ollama per il diario: {e}")
        return None

    destinazione = percorso.with_name(FILE_DIARIO)
    try:
        destinazione.write_text(_pagina_diario(testo_diario, atti), encoding="utf-8")
    except OSError as e:
        logger.error(f"Errore nella scrittura del diario: {e}")
        return None
    logger.info(f"Diario salvato in {destinazione}")
    return destinazione