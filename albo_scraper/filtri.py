"""Conversione e filtro delle date degli atti.
"""

from __future__ import annotations

from datetime import date, datetime


def parse_data(valore: str) -> date:
    return datetime.strptime(valore, "%d-%m-%Y").date()


def a_data(valore: date | str | None) -> date | None:
    """Accetta un date oppure una stringa 'GG-MM-AAAA'."""
    if valore is None or isinstance(valore, date):
        return valore
    return datetime.strptime(valore, "%d-%m-%Y").date()


def filtra_per_data(
    atti: list[dict],
    dal: date | str | None = None,
    al: date | str | None = None,
    campo: str = "data_inizio",
) -> list[dict]:
    """
    Filtra gli atti per data. `dal` e `al` sono inclusi e opzionali
    (date oppure stringhe 'GG-MM-AAAA').

    campo:
      - "data_inizio": data_inizio compresa tra dal e al (default)
      - "data_fine":   data_fine compresa tra dal e al
      - "periodo":     il periodo di pubblicazione si sovrappone all'intervallo
                       dal-al (atti in pubblicazione in almeno un giorno dell'intervallo)

    Gli atti senza la data richiesta vengono esclusi.
    """
    if campo not in ("data_inizio", "data_fine", "periodo"):
        raise ValueError("campo deve essere 'data_inizio', 'data_fine' o 'periodo'")

    dal, al = a_data(dal), a_data(al)
    risultati = []

    for atto in atti:
        inizio, fine = atto["data_inizio"], atto["data_fine"]

        if campo == "periodo":
            if inizio is None or fine is None:
                continue
            ok = (al is None or inizio <= al) and (dal is None or fine >= dal)
        else:
            data = atto[campo]
            if data is None:
                continue
            ok = (dal is None or data >= dal) and (al is None or data <= al)

        if ok:
            risultati.append(atto)

    return risultati


def piu_recenti(atti: list[dict], massimo: int | None) -> list[dict]:
    """
    I `massimo` atti con la data più recente (data di inizio pubblicazione = "Data atto"),
    ordinati dal più recente. A parità di data resta l'ordine della tabella; gli atti
    senza data vengono considerati i più vecchi. `massimo=None`: nessun limite, nessun
    cambio di ordine.
    """
    if massimo is None:
        return list(atti)
    if massimo < 1:
        raise ValueError("il numero massimo di atti deve essere almeno 1")
    ordinati = sorted(atti, key=lambda a: a.get("data_inizio") or date.min, reverse=True)
    return ordinati[:massimo]
