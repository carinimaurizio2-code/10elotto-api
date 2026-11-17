#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper 10eLotto SERALE (estrazione ore 20:00, mar/gio/ven/sab).
Scrive data/archivio_serale.csv (stesso formato letto dal programma VB).

Fonti a cascata: se Lottologia non risponde, prova le riserve.
Ogni fonte ha un parser dedicato e TUTTI i dati vengono validati
(20 numeri distinti 1-90, Oro e Doppio Oro dentro la ventina, somme plausibili).
"""

import csv
import os
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("Europe/Rome")
GIORNI_ESTRAZIONE = (1, 3, 4, 5)          # weekday(): lun=0 -> mar, gio, ven, sab
ORA_ESTRAZIONE_MIN = 20 * 60 + 5          # da quando cercare l'estrazione di oggi
ORA_ALLARME_MIN = 21 * 60 + 30            # dopo questa ora, se manca -> errore (mail GitHub)

CSV_PATH = "data/archivio_serale.csv"
CAMPI = ["Data", "Concorso", "Numeri", "Oro", "DoppioOro"]

FONTI = [
    {"nome": "Lottologia",         "url": "https://www.lottologia.com/10elotto/estrazioni/",                        "parser": "lottologia"},
    {"nome": "EstrazioneDelLotto", "url": "https://www.estrazionedellotto.it/10elotto/ultime-estrazioni-10elotto",  "parser": "edl"},
    {"nome": "10elotto5",          "url": "https://www.10elotto5.it/10elotto-serale/",                              "parser": "dieci5"},
]

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept-Language": "it-IT,it;q=0.9",
}

MESI_FULL = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
             "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
             "novembre": 11, "dicembre": 12}
MESI_ABBR = {"gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
             "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12}


def log(msg):
    print(f"[{datetime.now(TZ):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def pulisci_html(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.extract()
    return re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()


def split_doppio(raw, oro, numeri):
    """'3830'->30, '649'->9 (64+9), '859'->59 (8+59), '178'->8 (17+8)."""
    raw = raw.strip()
    if len(raw) == 4:
        d = int(raw[2:4])
        return d if d in numeri else None
    if len(raw) == 3:
        c1, c2 = int(raw[:1]), int(raw[1:])
        c3, c4 = int(raw[:2]), int(raw[2:])
        if c1 == oro and c2 in numeri:
            return c2
        if c3 == oro and c4 in numeri:
            return c4
        return None
    if len(raw) == 2:
        d = int(raw)
        return d if d in numeri else None
    return None


def valida(numeri, oro, doppio):
    if len(numeri) != 20 or len(set(numeri)) != 20:
        return False
    if any(n < 1 or n > 90 for n in numeri):
        return False
    if not (1 <= oro <= 90 and oro in numeri):
        return False
    if not (1 <= doppio <= 90 and doppio in numeri):
        return False
    s = sorted(numeri)
    run = best = 1
    for i in range(1, 20):
        run = run + 1 if s[i] == s[i - 1] + 1 else 1
        best = max(best, run)
    if best >= 10:
        return False
    if not (500 <= sum(s) <= 1350):
        return False
    return True


# ---------------------------------------------------------------------------
# PARSER 1: Lottologia (identico alla logica del programma VB)
# ---------------------------------------------------------------------------
def parse_lottologia(html):
    testo = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    testo = re.sub(r"<style[\s\S]*?</style>", " ", testo, flags=re.I)
    testo = re.sub(r"<[^>]+>", " ", testo).replace("&nbsp;", " ")
    testo = re.sub(r"\s+", " ", testo)

    rx = re.compile(r"\b(\d{1,2})\s+(Gen|Feb|Mar|Apr|Mag|Giu|Lug|Ago|Set|Ott|Nov|Dic)\.?\s+(\d{4})\b", re.I)
    ms = list(rx.finditer(testo))
    out, visti = [], set()
    for i, m in enumerate(ms):
        try:
            g = int(m.group(1)); me = MESI_ABBR[m.group(2).lower()[:3]]; a = int(m.group(3))
            fine = ms[i + 1].start() if i + 1 < len(ms) else len(testo)
            blocco = testo[m.end():fine]
            low = blocco.lower()
            i_num = low.find("numeri"); i_dop = low.find("doppio oro")
            if i_num < 0 or i_dop < 0:
                continue
            i_oro = low.find("oro", i_num)
            if i_oro < 0 or i_oro >= i_dop:
                continue
            i_ext = low.find("extra", i_dop)
            fine_dop = i_ext if i_ext >= 0 else len(blocco)

            c_num = "".join(c for c in blocco[i_num + 6:i_oro] if c.isdigit())[:40]
            c_oro = "".join(c for c in blocco[i_oro + 3:i_dop] if c.isdigit())
            c_dop = "".join(c for c in blocco[i_dop + 10:fine_dop] if c.isdigit())
            if len(c_num) < 40:
                continue
            numeri = [int(c_num[p:p + 2]) for p in range(0, 40, 2)]
            oro = int(c_oro[:2]) if len(c_oro) >= 2 else numeri[0]
            doppio = split_doppio(c_dop, oro, numeri) if c_dop else numeri[1]
            if doppio is None:
                continue
            if not valida(numeri, oro, doppio):
                continue
            k = f"{g:02d}/{me:02d}/{a}"
            if k in visti:
                continue
            visti.add(k)
            out.append((datetime(a, me, g, 20, 0), numeri, oro, doppio))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# PARSER 2: estrazionedellotto.it (ultimi 60 giorni, HTML statico affidabile)
# Formato: "Estrazione n. 183 14/11/2026 ... Numero Oro 38 Doppio Oro 3830 Extra ..."
# ---------------------------------------------------------------------------
def parse_edl(html):
    testo = pulisci_html(html)
    rx = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
    ms = list(rx.finditer(testo))
    out, visti = [], set()
    for i, m in enumerate(ms):
        try:
            g, me, a = map(int, m.groups())
            if a < 2009:
                continue
            blocco = testo[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(testo)]
            ix = blocco.lower().find("extra")
            if ix >= 0:
                blocco = blocco[:ix]
            mo = re.search(r"numero\s+oro\s+(\d{1,2})", blocco, re.I)
            md = re.search(r"doppio\s+oro\s+(\d{2,4})", blocco, re.I)
            nums = [int(x) for x in re.findall(r"\b([1-9]|[1-8]\d|90)\b", blocco)]
            unici = list(dict.fromkeys(nums))
            if len(unici) < 20:
                continue
            n20 = unici[:20]
            oro = int(mo.group(1)) if mo else n20[0]
            doppio = split_doppio(md.group(1), oro, n20) if md else n20[1]
            if doppio is None or not valida(n20, oro, doppio):
                continue
            k = f"{g:02d}/{me:02d}/{a}"
            if k in visti:
                continue
            visti.add(k)
            out.append((datetime(a, me, g, 20, 0), n20, oro, doppio))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# PARSER 3: 10elotto5.it (tabella compatta: 20 numeri + Oro + D.Or in riga)
# Formato: "Estrazione 10eLotto Serale del 14 Novembre 2026 Oro D.Or 1 6 ... 89 38 30 EXTRA ..."
# ---------------------------------------------------------------------------
def parse_dieci5(html):
    testo = pulisci_html(html)
    rx = re.compile(r"Estrazione\s+10eLotto\s+Serale\s+del\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", re.I)
    ms = list(rx.finditer(testo))
    out, visti = [], set()
    for i, m in enumerate(ms):
        try:
            g = int(m.group(1)); me = MESI_FULL.get(m.group(2).lower()); a = int(m.group(3))
            if not me:
                continue
            blocco = testo[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(testo)]
            ix = blocco.upper().find("EXTRA")
            if ix >= 0:
                blocco = blocco[:ix]
            nums = [int(x) for x in re.findall(r"\b([1-9]|[1-8]\d|90)\b", blocco)]
            if len(nums) < 22:
                continue
            n20, oro, doppio = nums[:20], nums[20], nums[21]
            if not valida(n20, oro, doppio):
                continue
            k = f"{g:02d}/{me:02d}/{a}"
            if k in visti:
                continue
            visti.add(k)
            out.append((datetime(a, me, g, 20, 0), n20, oro, doppio))
        except Exception:
            continue
    return out


PARSERS = {"lottologia": parse_lottologia, "edl": parse_edl, "dieci5": parse_dieci5}


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    ora = datetime.now(TZ)
    oggi = ora.strftime("%d/%m/%Y")
    minuti = ora.hour * 60 + ora.minute
    giorno_estrazione = ora.weekday() in GIORNI_ESTRAZIONE
    log(f"Avvio aggiornamento serale (oggi {oggi}, giorno estrazione: {'si' if giorno_estrazione else 'no'})")

    archivio = carica_archivio()
    log(f"Archivio esistente: {len(archivio)} estrazioni")

    def manca_oggi():
        return giorno_estrazione and minuti >= ORA_ESTRAZIONE_MIN and oggi not in archivio

    nuove = 0
    limite_recente = (ora - timedelta(days=10)).date()

    for fonte in FONTI:
        # Le riserve si provano solo se manca ancora l'estrazione di oggi
        # (o se non abbiamo preso nulla dalla prima fonte).
        if nuove > 0 and not manca_oggi():
            break
        log(f"-> Tentativo su {fonte['nome']}...")
        try:
            resp = requests.get(fonte["url"], headers=HEADERS, timeout=25)
            log(f"   HTTP {resp.status_code}, {len(resp.text)} caratteri")
            if resp.status_code != 200:
                continue
            dati = PARSERS[fonte["parser"]](resp.text)
            if fonte["parser"] != "lottologia":
                # le riserve: solo date recenti e giorni di estrazione
                dati = [d for d in dati
                        if limite_recente <= d[0].date() <= ora.date()
                        and d[0].weekday() in GIORNI_ESTRAZIONE]
            log(f"   Estrazioni valide riconosciute: {len(dati)}")
            for d, numeri, oro, doppio in dati:
                k = d.strftime("%d/%m/%Y")
                if k in archivio:
                    continue
                archivio[k] = {
                    "Data": d.strftime("%d/%m/%Y %H:%M"),
                    "Concorso": str(d.timetuple().tm_yday),
                    "Numeri": " ".join(f"{n:02d}" for n in numeri),
                    "Oro": str(oro),
                    "DoppioOro": str(doppio),
                }
                nuove += 1
                log(f"   + {k} da {fonte['nome']}")
        except requests.exceptions.RequestException as e:
            log(f"   Errore di rete su {fonte['nome']}: {e}")
        except Exception as e:
            log(f"   Fallito ({fonte['nome']}): {e}")

    if nuove > 0 or not os.path.exists(CSV_PATH):
        salva_archivio(archivio)

    log(f"Fine. Nuove aggiunte: {nuove}. Totale: {len(archivio)}")

    if giorno_estrazione and minuti >= ORA_ALLARME_MIN and oggi not in archivio:
        log("ERRORE: estrazione di oggi non trovata da nessuna fonte")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
