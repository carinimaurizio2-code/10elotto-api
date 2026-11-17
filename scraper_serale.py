#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper 10eLotto SERALE (estrazione ore 20:00, mar/gio/ven/sab).
Scrive data/archivio_serale.csv (stesso formato letto dal programma VB).

- Lottologia ha un parser dedicato (affidabile).
- Le altre fonti usano un parser generico (meno affidabile): servono solo come
  riserva se manca l'estrazione di oggi, e accettano solo date recenti.
- Se in un giorno di estrazione, dopo le 21:30 italiane, l'estrazione di oggi
  non e' stata trovata, lo script termina con errore (GitHub ti manda una mail).
"""

import csv
import os
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# ============================================================================
# CONFIGURAZIONE
# ============================================================================
TZ = ZoneInfo("Europe/Rome")
GIORNI_ESTRAZIONE = (1, 3, 4, 5)  # weekday(): lun=0 -> mar, gio, ven, sab
ORA_ESTRAZIONE_MIN = 20 * 60 + 5   # da quando cercare l'estrazione di oggi
ORA_ALLARME_MIN = 21 * 60 + 30     # dopo questa ora, se manca -> errore

CSV_PATH = "data/archivio_serale.csv"

FONTI = [
    {"nome": "Lottologia", "url": "https://www.lottologia.com/10elotto/estrazioni/"},
    {"nome": "Estrazioni-Lotto", "url": "https://www.estrazioni-del-lotto-e-10elotto.it/10elotto-serale"},
    {"nome": "Lotto.it", "url": "https://www.lotto.it/10eLotto/Estrazioni"},
    {"nome": "ADM-Monopoli", "url": "https://www.adm.gov.it/portale/web/guest/10elotto-estrazioni"},
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9",
}

MESI = {
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
}

CAMPI = ["Data", "Concorso", "Numeri", "Oro", "DoppioOro"]


def log(msg):
    print(f"[{datetime.now(TZ):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ============================================================================
# PARSER GENERICO (fonti diverse da Lottologia)
# ============================================================================
def parse_generico(html, nome_fonte):
    estrazioni = []
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.extract()
    testo = re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()

    rx_data = re.compile(
        r"\b(\d{1,2})[/\-\s](\d{1,2}|[A-Za-z]{3})[/\-\s](\d{2,4})\b", re.I
    )
    matches = list(rx_data.finditer(testo))

    for i, m in enumerate(matches):
        try:
            giorno = int(m.group(1))
            mese_str = m.group(2)
            if mese_str.isdigit():
                mese = int(mese_str)
            elif mese_str.lower() in MESI:
                mese = MESI[mese_str.lower()]
            else:
                continue
            anno = int(m.group(3))
            if anno < 100:
                anno += 2000
            data_estr = datetime(anno, mese, giorno, 20, 0, 0)

            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(testo)
            if end - start > 2000:
                end = start + 2000
            blocco = testo[start:end]

            nums = [int(n) for n in re.findall(r"\b([1-9]|[1-8]\d|90)\b", blocco)]
            unici = list(dict.fromkeys(nums))
            if len(unici) < 20:
                continue
            primi_20 = unici[:20]
            if sum(primi_20) < 500 or sum(primi_20) > 1350:
                continue

            estrazioni.append({
                "data": data_estr,
                "numeri": primi_20,
                "oro": primi_20[0],
                "doppio": primi_20[1],
                "fonte": nome_fonte,
            })
        except Exception:
            continue
    return estrazioni


# ============================================================================
# PARSER LOTTOLOGIA (stessa logica del programma VB)
# ============================================================================
def parse_lottologia(html, nome_fonte):
    estrazioni = []
    testo = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    testo = re.sub(r"<style[\s\S]*?</style>", " ", testo, flags=re.I)
    testo = re.sub(r"<[^>]+>", " ", testo)
    testo = testo.replace("&nbsp;", " ")
    testo = re.sub(r"\s+", " ", testo)

    rx = re.compile(
        r"\b(\d{1,2})\s+(Gen|Feb|Mar|Apr|Mag|Giu|Lug|Ago|Set|Ott|Nov|Dic)\.?\s+(\d{4})\b",
        re.I,
    )
    matches = list(rx.finditer(testo))
    visti = set()
    for i, m in enumerate(matches):
        try:
            giorno = int(m.group(1))
            mese = MESI[m.group(2).lower()]
            anno = int(m.group(3))
            fine = matches[i + 1].start() if i + 1 < len(matches) else len(testo)
            blocco = testo[m.end():fine]
            low = blocco.lower()

            i_num = low.find("numeri")
            i_dop = low.find("doppio oro")
            if i_num < 0 or i_dop < 0:
                continue
            i_oro = low.find("oro", i_num)
            if i_oro < 0 or i_oro >= i_dop:
                continue
            i_ext = low.find("extra", i_dop)
            fine_dop = i_ext if i_ext >= 0 else len(blocco)

            c_num = "".join(c for c in blocco[i_num + 6:i_oro] if c.isdigit())
            c_oro = "".join(c for c in blocco[i_oro + 3:i_dop] if c.isdigit())
            c_dop = "".join(c for c in blocco[i_dop + 10:fine_dop] if c.isdigit())
            if len(c_num) < 40:
                continue
            c_num = c_num[:40]
            numeri = [int(c_num[p:p + 2]) for p in range(0, 40, 2)]
            if len(set(numeri)) != 20 or any(n < 1 or n > 90 for n in numeri):
                continue

            oro = int(c_oro[:2]) if len(c_oro) >= 2 else numeri[0]
            if len(c_dop) >= 4:
                doppio = int(c_dop[2:4])
            elif len(c_dop) >= 2:
                doppio = int(c_dop[:2])
            else:
                doppio = numeri[1]
            if not (1 <= oro <= 90 and 1 <= doppio <= 90):
                continue

            data_estr = datetime(anno, mese, giorno, 20, 0, 0)
            chiave = data_estr.strftime("%d/%m/%Y")
            if chiave in visti:
                continue
            visti.add(chiave)
            estrazioni.append({
                "data": data_estr,
                "numeri": numeri,
                "oro": oro,
                "doppio": doppio,
                "fonte": nome_fonte,
            })
        except Exception:
            continue
    return estrazioni


# ============================================================================
# LETTURA / SCRITTURA CSV
# ============================================================================
def carica_archivio():
    archivio = {}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                if row.get("Data"):
                    archivio[row["Data"].split()[0]] = row
    return archivio


def salva_archivio(archivio):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    tmp = CSV_PATH + ".tmp"

    def chiave_ordine(r):
        try:
            return datetime.strptime(r["Data"], "%d/%m/%Y %H:%M")
        except ValueError:
            return datetime.strptime(r["Data"].split()[0], "%d/%m/%Y")

    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPI, delimiter=";")
        w.writeheader()
        w.writerows(sorted(archivio.values(), key=chiave_ordine))
    os.replace(tmp, CSV_PATH)


# ============================================================================
# MAIN
# ============================================================================
def main():
    ora = datetime.now(TZ)
    oggi = ora.strftime("%d/%m/%Y")
    minuti = ora.hour * 60 + ora.minute
    giorno_estrazione = ora.weekday() in GIORNI_ESTRAZIONE
    log(f"Avvio aggiornamento archivio serale (oggi {oggi}, "
        f"giorno estrazione: {'si' if giorno_estrazione else 'no'})")

    archivio = carica_archivio()
    log(f"Archivio esistente: {len(archivio)} estrazioni")

    def manca_oggi():
        return giorno_estrazione and minuti >= ORA_ESTRAZIONE_MIN and oggi not in archivio

    nuove_aggiunte = 0
    fonte_vincente = "Nessuna"
    limite_recente = (ora - timedelta(days=7)).date()

    for fonte in FONTI:
        # Dalla seconda fonte in poi si prova solo se non abbiamo ancora dati
        # oppure se manca ancora l'estrazione di oggi.
        if fonte_vincente != "Nessuna" and not manca_oggi():
            break

        log(f"-> Tentativo su {fonte['nome']}...")
        try:
            resp = requests.get(fonte["url"], headers=HEADERS, timeout=20)
            log(f"   HTTP {resp.status_code}, {len(resp.text)} caratteri")
            if resp.status_code != 200:
                continue

            if fonte["nome"] == "Lottologia":
                dati = parse_lottologia(resp.text, fonte["nome"])
            else:
                dati = parse_generico(resp.text, fonte["nome"])
                # Parser meno affidabile: solo date recenti e giorni di estrazione
                dati = [
                    d for d in dati
                    if d["data"].date() >= limite_recente
                    and d["data"].date() <= ora.date()
                    and d["data"].weekday() in GIORNI_ESTRAZIONE
                ]
            log(f"   Estrazioni riconosciute: {len(dati)}")
            if not dati:
                continue

            fonte_vincente = fonte["nome"]
            for d in dati:
                chiave = d["data"].strftime("%d/%m/%Y")
                if chiave in archivio:
                    continue
                archivio[chiave] = {
                    "Data": d["data"].strftime("%d/%m/%Y %H:%M"),
                    "Concorso": d["data"].timetuple().tm_yday,
                    "Numeri": " ".join(f"{n:02d}" for n in d["numeri"]),
                    "Oro": d["oro"],
                    "DoppioOro": d["doppio"],
                }
                nuove_aggiunte += 1
                log(f"   + {chiave} da {fonte['nome']}")

        except requests.exceptions.RequestException as e:
            log(f"   Errore di rete su {fonte['nome']}: {e}")
        except Exception as e:
            log(f"   Fallito ({fonte['nome']}): {e}")

    if nuove_aggiunte > 0 or not os.path.exists(CSV_PATH):
        salva_archivio(archivio)

    log(f"Fine. Ultima fonte valida: {fonte_vincente}. "
        f"Nuove aggiunte: {nuove_aggiunte}. Totale: {len(archivio)}")

    # Errore visibile (mail da GitHub) solo se, dopo le 21:30, manca ancora oggi
    if giorno_estrazione and minuti >= ORA_ALLARME_MIN and oggi not in archivio:
        log("ERRORE: estrazione di oggi non trovata da nessuna fonte")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
