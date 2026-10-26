"""Scrittura della tabella finale in un file HTML.
"""

from __future__ import annotations

from datetime import datetime
from html import escape as esc_html
from pathlib import Path

from .config import COLONNE_TABELLA
from .log import logger
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import json
import re
from .config import (
    COLONNE_TABELLA,
    OLLAMA_URL, # Assicurati che sia qui o importata da config
    PROMPT_DIARIO, # Qui definito sopra in config.py
    USER_AGENT, # User agent per Playwright
)


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
        titolo = titolo.title()
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

def _pulisci_riga_atti(testo: str) -> dict | None:
    """
    Estrae i dati da una riga di tabella HTML locale.
    Ritorna un dict o None se non ha contenuto.
    Cerca <td> con testo che contiene 'Data atto' o il pattern della data, 
    oppure usa gli indici (4a colonna = riassunto).
    """
    if not testo:
        return None

    # Selezioniamo le celle tramite regex semplice su innerText della riga o split su tab
    # Usiamo Playwright per estrarre il contenuto pulito se possibile, ma per leggere HTML statico,
    # useremo una logica di splitting basata sulle colonne note (Data, Titolo, Link, Riassunto).
    
    # Qui semplifichiamo: assumiamo che l'HTML abbia <tr> e dentro <td>.
    righe = re.findall(r'<td[^>]*>(.*?)</td>', testo, flags=re.DOTALL | re.IGNORECASE)
    
    if len(righe) < 4:
        # Se non ha almeno 4 colonne, saltiamo
        return None

    data_inizio_str = righe[0].strip().replace("--", "").split()[0] if righe[0] else ""
    titolo = re.sub(r'<[^>]+>', '', righe[1]).strip()
    link = righe[2].strip() # Spesso vuoto o link relativo/assoluto
    riassunto = re.sub(r'<[^>]+>', '', righe[3]).strip()

    return {
        "data": data_inizio_str,
        "titolo": titolo,
        "link": link,
        "riassunto": riassunto,
    }

def estrai_riassunti_dal_html(percorso_html: Path | str) -> list[dict]:
    """Legge il file HTML e restituisce una lista di dict con i dati dei riassunti."""
    with open(percorso_html, 'r', encoding='utf-8') as f:
        html = f.read()

    # Carica l'HTML localmente in un browser per renderizzare e leggere meglio (opzionale ma robusto)
    # Oppure parse puro. Usiamo Playwright come nel resto del progetto.
    
    if not logger.handlers:
        configura_logging()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        
        try:
            page.set_content(html, wait_until="domcontentloaded")
            
            # Seleziona la tabella generata da scrivi_tabella (spesso ha class="contenitore" o simile)
            # Cerchiamo il primo <tbody> con tr
            rows = page.query_selector_all("body .contenitore table tbody tr")
            
            atti_estratti = []
            for row in rows:
                try:
                    # Costruiamo un selectore per la riga e ne leggiamo le celle pulite
                    testo_riga = row.inner_text() # include i tag? inner_text no, strip_tags sì? playwright.playwright.text_content
                    # playwright.playwright.locator("td").all_inner_text() è meglio.
                    
                    # Usiamo il locatore per le celle td
                    cells = row.query_selector_all("td")
                    if len(cells) >= 4:
                        # Estraiamo il testo pulito delle prime 4 colonne
                        c1 = cells[0].text_content()
                        c2 = cells[1].text_content()
                        c3 = cells[2].text_content()
                        c4 = cells[3].text_content()
                        
                        # Logica per identificare la data e il riassunto in base alla posizione o al contenuto
                        # La tabella ha colonne: Data, Titolo, Link, Riassunto (dall'HTML generato)
                        
                        if "Data" in c1 or re.search(r"\d{2}-\d{2}-\d{4}", c1):
                            atti_estratti.append({
                                "data": c1.strip(),
                                "titolo": c2.strip(),
                                "link": c3,
                                "riassunto": c4.strip()
                            })
                except Exception as e:
                    # Se la riga è corrotta o non standardabile, saltala
                    continue
            
            return atti_estratti
            
        finally:
            browser.close()

def genera_diario(percorso_html: Path | str, modello: str = "llama3.1:8b") -> Path | None:
    """
    Legge i riassunti dal file HTML (usando --output) e chiama Ollama per generare un diario.
    Restituisce il percorso del file di diario salvato (diario_atti.txt).
    """
    import json
    import urllib.request
    
    # Estrai dati
    try:
        liste_riassunti = estrai_riassunti_dal_html(percorso_html)
    except Exception as e:
        logger.error(f"Errore nell'analisi HTML per il diario: {e}")
        return None

    if not liste_riassunti:
        logger.warning("Nessun atto trovato nell'HTML fornito.")
        return None

    # Costruisci il prompt da mandare a Ollama
    # Prepara i dati in formato leggibile (JSON minified o testo pulito)
    prompt = PROMPT_DIARIO.replace("{dati_atti}", json.dumps(liste_riassunti, indent=2))

    logger.info(f"Invio richiesta a Ollama per il diario ({len(liste_riassunti)} eventi)...")
    
    payload = {
        "model": modello,
        "stream": False,
        "options": {"num_ctx": 8192}, # Ridurre consumo se serve
        "messages": [
            {"role": "user", "content": prompt}
        ],
    }
    logger.debug(f"Payload inviato a Ollama: {json.dumps(payload, indent=2)}")

    try:
        richiesta = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        
        with urllib.request.urlopen(richiesta, timeout=900) as risposta:
            dati = json.loads(risposta.read().decode("utf-8"))
            diario_testo = dati.get("message", {}).get("content", "").strip()
            
    except Exception as e:
        logger.error(f"Errore nella chiamata a Ollama per il diario: {e}")
        return None

    # Salva il diario in un file dedicato o sovrascrive l'output?
    # Meglio creare un nuovo file "diario_atti.txt" accanto al progetto
    from .config import DIARIO_FILE
    percorso_output = Path(DIARIO_FILE)
    
    try:
        with open(percorso_output, 'w', encoding='utf-8') as f:
            f.write(diario_testo)
        logger.info(f"Diario salvato in {percorso_output}")
        return percorso_output
    except Exception as e:
        logger.error(f"Errore nella scrittura del file diario: {e}")
        return None
