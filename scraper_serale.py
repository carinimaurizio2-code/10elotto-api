#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper 10eLotto SERALE per GitHub Actions (Versione Ottimizzata).
- Timeout ridotto per evitare blocchi.
- Watchdog di sicurezza (max 3 minuti).
- Gestione festività italiane.
"""

import csv
import os
import re
import sys
import signal
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# --- WATCHDOG: Uccidi lo script se supera i 3 minuti (180 secondi) ---
def handler(signum, frame):
    print("!!! TIMEOUT GLOBALE: Lo script ha superato i 3 minuti. Uscita forzata.", flush=True)
    sys.exit(1)

# Imposta l'allarme (funziona su Linux/Mac/GitHub Actions)
try:
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(180)
except AttributeError:
    pass # Su Windows locale non funziona, ma su GitHub Actions (Linux) sì.

# --- CONFIGURAZIONE ---
TZ = ZoneInfo("Europe/Rome")
GIORNI_ESTRAZIONE = (1, 3, 4, 5)          # weekday(): lun=0 -> mar(1), gio(3), ven(4), sab(5)
ORA_ESTRAZIONE_MIN = 20 * 60 + 5          # 20:05
ORA_ALLARME_MIN = 21 * 60 + 30            # 21:30

CSV_PATH = "data/archivio_serale.csv"
CAMPI = ["Data", "Concorso", "Numeri", "Oro", "DoppioOro"]

# Festività fisse (GG/MM)
FESTIVITA_FISSE = {
    "01/01", "06/01", "25/04", "01/05", "02/06", 
    "15/08", "01/11", "08/12", "25/12", "26/12"
}

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
    raw = raw.strip()
    if len(raw) == 4:
        d = int(raw[2:4])
        return d if d in numeri else None
    if len(raw) == 3:
        c1, c2 = int(raw[:1]), int(raw[1:])
        c3, c4 = int(raw[:2]), int(raw[2:])
        if c1 == oro and c2 in numeri: return c2
        if c3 == oro and c4 in numeri: return c4
        return None
    if len(raw) == 2:
        d = int(raw)
        return d if d in numeri else None
    return None

def valida(numeri, oro, doppio):
    if len(numeri) != 20 or len(set(numeri)) != 20: return False
    if any(n < 1 or n > 90 for n in numeri): return False
    if not (1 <= oro <= 90 and oro in numeri): return False
    if not (1 <= doppio <= 90 and doppio in numeri): return False
    s = sorted(numeri)
    run = best = 1
    for i in range(1, 20):
        run = run + 1 if s[i] == s[i - 1] + 1 else 1
        best = max(best, run)
    if best >= 10: return False
    if not (500 <= sum(s) <= 1350): return False
    return True

# ---------------------------------------------------------------------------
# PARSERS
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
            if i_num < 0 or i_dop < 0: continue
            i_oro = low.find("oro", i_num)
            if i_oro < 0 or i_oro >= i_dop: continue
            i_ext = low.find("extra", i_dop)
            fine_dop = i_ext if i_ext >= 0 else len(blocco)
            c_num = "".join(c for c in blocco[i_num + 6:i_oro] if c.isdigit())[:40]
            c_oro = "".join(c for c in blocco[i_oro + 3:i_dop] if c.isdigit())
            c_dop = "".join(c for c in blocco[i_dop + 10:fine_dop] if c.isdigit())
            if len(c_num) < 40: continue
            numeri = [int(c_num[p:p + 2]) for p in range(0, 40, 2)]
            oro = int(c_oro[:2]) if len(c_oro) >= 2 else numeri[0]
            doppio = split_doppio(c_dop, oro, numeri) if c_dop else numeri[1]
            if doppio is None: continue
            if not valida(numeri, oro, doppio): continue
            k = f"{g:02d}/{me:02d}/{a}"
            if k in visti: continue
            visti.add(k)
            out.append((datetime(a, me, g, 20, 0), numeri, oro, doppio))
        except Exception: continue
    return out

def parse_edl(html):
    testo = pulisci_html(html)
    rx = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
    ms = list(rx.finditer(testo))
    out, visti = [], set()
    for i, m in enumerate(ms):
        try:
            g, me, a = map(int, m.groups())
            if a < 2009: continue
            blocco = testo[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(testo)]
            ix = blocco.lower().find("extra")
            if ix >= 0: blocco = blocco[:ix]
            mo = re.search(r"numero\s+oro\s+(\d{1,2})", blocco, re.I)
            md = re.search(r"doppio\s+oro\s+(\d{2,4})", blocco, re.I)
            nums = [int(x) for x in re.findall(r"\b([1-9]|[1-8]\d|90)\b", blocco)]
            unici = list(dict.fromkeys(nums))
            if len(unici) < 20: continue
            n20 = unici[:20]
            oro = int(mo.group(1)) if mo else n20[0]
            doppio = split_doppio(md.group(1), oro, n20) if md else n20[1]
            if doppio is None or not valida(n20, oro, doppio): continue
            k = f"{g:02d}/{me:02d}/{a}"
            if k in visti: continue
            visti.add(k)
            out.append((datetime(a, me, g, 20, 0), n20, oro, doppio))
        except Exception: continue
    return out

def parse_dieci5(html):
    testo = pulisci_html(html)
    rx = re.compile(r"Estrazione\s+10eLotto\s+Serale\s+del\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", re.I)
    ms = list(rx.finditer(testo))
    out, visti = [], set()
    for i, m in enumerate(ms):
        try:
            g = int(m.group(1)); me = MESI_FULL.get(m.group(2).lower()); a = int(m.group(3))
            if not me: continue
            blocco = testo[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(testo)]
            ix = blocco.upper().find("EXTRA")
            if ix >= 0: blocco = blocco[:ix]
            nums = [int(x) for x in re.findall(r"\b([1-9]|[1-8]\d|90)\b", blocco)]
            if len(nums) < 22: continue
            n20, oro, doppio = nums[:20], nums[20], nums[21]
            if not valida(n20, oro, doppio): continue
            k = f"{g:02d}/{me:02d}/{a}"
            if k in visti: continue
            visti.add(k)
            out.append((datetime(a, me, g, 20, 0), n20, oro, doppio))
        except Exception: continue
    return out

PARSERS = {"lottologia": parse_lottologia, "edl": parse_edl, "dieci5": parse_dieci5}

# ---------------------------------------------------------------------------
# GESTIONE CSV
# ---------------------------------------------------------------------------
def carica_archivio():
    archivio = {}
    if os.path.exists(CSV_PATH):
        try:
            with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f, delimiter=";"):
                    if row.get("Data"):
                        data_key = row["Data"].split()[0]
                        archivio[data_key] = row
        except Exception as e:
            log(f"Errore lettura archivio esistente: {e}")
    return archivio

def salva_archivio(archivio):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    tmp = CSV_PATH + ".tmp"
    def chiave_ordine(r):
        try: return datetime.strptime(r["Data"], "%d/%m/%Y %H:%M")
        except ValueError: return datetime.strptime(r["Data"].split()[0], "%d/%m/%Y")
    
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPI, delimiter=";")
        w.writeheader()
        w.writerows(sorted(archivio.values(), key=chiave_ordine))
    os.replace(tmp, CSV_PATH)
    log(f"Archivio salvato in {CSV_PATH}")

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    ora = datetime.now(TZ)
    oggi_str = ora.strftime("%d/%m/%Y")
    oggi_festa_key = ora.strftime("%d/%m")
    minuti = ora.hour * 60 + ora.minute
    
    giorno_settimana = ora.weekday()
    giorno_estrazione_teorico = giorno_settimana in GIORNI_ESTRAZIONE
    is_festivo = oggi_festa_key in FESTIVITA_FISSE
    
    log(f"Avvio aggiornamento: Oggi è {oggi_str} ({ora.strftime('%A')})")
    log(f"Giorno estrazione teorico: {'SI' if giorno_estrazione_teorico else 'NO'} | Festività: {'SI' if is_festivo else 'NO'}")

    archivio = carica_archivio()
    log(f"Archivio caricato: {len(archivio)} righe.")

    if is_festivo:
        log("Oggi è festivo: nessuna estrazione attesa. Esco senza errori.")
        sys.exit(0)

    if not giorno_estrazione_teorico:
        log("Oggi non è giorno di estrazione. Esco senza errori.")
        sys.exit(0)

    if oggi_str in archivio:
        log(f"L'estrazione di oggi ({oggi_str}) è già presente nell'archivio.")
    
    nuove = 0
    limite_recente = (ora - timedelta(days=15)).date()

    for fonte in FONTI:
        if nuove > 0 and oggi_str in archivio and fonte["nome"] != "Lottologia":
            log("Dati odierni trovati e aggiornati. Skip fonti secondarie.")
            break
            
        log(f"-> Download da {fonte['nome']}...")
        try:
            # TIMEOUT RIDOTTO A 10 SECONDI per evitare blocchi su GitHub Actions
            resp = requests.get(fonte["url"], headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                log(f"   Errore HTTP {resp.status_code}")
                continue
            
            dati = PARSERS[fonte["parser"]](resp.text)
            
            dati_filtrati = []
            for d, numeri, oro, doppio in dati:
                if fonte["parser"] == "lottologia" or d.date() >= limite_recente:
                    dati_filtrati.append((d, numeri, oro, doppio))
            
            log(f"   Trovate {len(dati_filtrati)} estrazioni valide.")
            
            for d, numeri, oro, doppio in dati_filtrati:
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
                log(f"   [+] Aggiunta estrazione del {k}")
                
        except requests.exceptions.RequestException as e:
            log(f"   Errore rete (timeout o connessione): {e}")
        except Exception as e:
            log(f"   Errore parsing: {e}")

    if nuove > 0:
        salva_archivio(archivio)
        log(f"Aggiornamento completato: +{nuove} nuove estrazioni.")
    else:
        log("Nessuna nuova estrazione trovata.")

    if minuti >= ORA_ALLARME_MIN and oggi_str not in archivio:
        log(f"!!! ALLARME: Sono le {ora.strftime('%H:%M')}, è giorno di estrazione, ma non ho trovato i dati di oggi.")
        log("!!! Le fonti potrebbero essere down o cambiate. Verificare manualmente.")
        sys.exit(1)

    sys.exit(0)

if __name__ == "__main__":
    main()
