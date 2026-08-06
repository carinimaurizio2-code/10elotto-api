import requests
import json
import os
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# ══════════════════════════════════════════════
# CONFIGURAZIONE
# ══════════════════════════════════════════════
URL_PRINCIPALE = "https://10elottoogni5minuti.it/"
FILE_OUTPUT    = "data/estrazioni.json"
FILE_STORICO   = "data/storico.json"
MAX_STORICO    = 20000  # massimo record nel JSON storico

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "it-IT,it;q=0.9",
}

MESI = {
    "gennaio":1,"febbraio":2,"marzo":3,"aprile":4,
    "maggio":5,"giugno":6,"luglio":7,"agosto":8,
    "settembre":9,"ottobre":10,"novembre":11,"dicembre":12
}

# ══════════════════════════════════════════════
# SCARICA PAGINA
# ══════════════════════════════════════════════
def scarica(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"Errore scaricamento {url}: {e}")
        return None

# ══════════════════════════════════════════════
# PARSER — 10elottoogni5minuti.it
# ══════════════════════════════════════════════
def parsa_pagina(html):
    estrazioni = []
    if not html:
        return estrazioni

    # Dividi per sezioni
    blocchi = re.split(r'"sezione"', html)
    if len(blocchi) < 2:
        blocchi = re.split(r'<h1', html)

    for blocco in blocchi:
        try:
            # Concorso e data
            m = re.search(
                r'n\.\s*(\d+)\s+di\s+\w+\s+(\d{1,2})\s+(\w+)\s+(\d{4})',
                blocco, re.IGNORECASE
            )
            if not m:
                continue

            concorso = int(m.group(1))
            giorno   = int(m.group(2))
            mese_str = m.group(3).lower()
            anno     = int(m.group(4))

            if mese_str not in MESI:
                continue
            mese = MESI[mese_str]

            # Calcola orario da numero concorso
            minuti_totali = (concorso * 5) % 1440
            ora    = minuti_totali // 60
            minuto = minuti_totali % 60

            try:
                data = datetime(anno, mese, giorno, ora, minuto)
            except:
                continue

            # 20 numeri verdi
            numeri_m = re.findall(
                r'<p\s+class="numero\s+bg-green-600">(\d{1,2})</p>',
                blocco, re.IGNORECASE
            )
            if len(numeri_m) < 20:
                continue

            numeri = [int(x) for x in numeri_m[:20]]
            if any(n < 1 or n > 90 for n in numeri):
                continue

            # Oro
            oro_m = re.search(
                r'<p\s+class="numero[^"]*bg-yellow-300">(\d{1,2})</p>',
                blocco, re.IGNORECASE
            )
            oro = int(oro_m.group(1)) if oro_m else numeri[0]

            # Doppio Oro
            doppio_m = re.search(
                r'<p\s+class="numero[^"]*bg-yellow-400">(\d{1,2})</p>',
                blocco, re.IGNORECASE
            )
            doppio = int(doppio_m.group(1)) if doppio_m else numeri[1]

            estrazioni.append({
                "data":       data.strftime("%d/%m/%Y"),
                "orario":     data.strftime("%H:%M"),
                "concorso":   concorso,
                "numeri":     numeri,
                "oro":        oro,
                "doppio_oro": doppio,
                "timestamp":  data.strftime("%Y%m%d%H%M")
            })

        except Exception as e:
            print(f"Errore blocco: {e}")
            continue

    return estrazioni

# ══════════════════════════════════════════════
# CALCOLA STATISTICHE
# ══════════════════════════════════════════════
def calcola_statistiche(tutte_estrazioni):
    freq     = {i: 0 for i in range(1, 91)}
    freq_oro = {i: 0 for i in range(1, 91)}
    ultima_uscita = {i: -1 for i in range(1, 91)}

    ordinate = sorted(
        tutte_estrazioni,
        key=lambda x: x["timestamp"]
    )

    for idx, e in enumerate(ordinate):
        for n in e["numeri"]:
            if 1 <= n <= 90:
                freq[n] += 1
                ultima_uscita[n] = idx
        if 1 <= e["oro"] <= 90:
            freq_oro[e["oro"]] += 1

    tot = len(ordinate)
    ritardi = {
        i: (tot if ultima_uscita[i] == -1
            else tot - 1 - ultima_uscita[i])
        for i in range(1, 91)
    }

    top_freq = sorted(
        freq.items(),
        key=lambda x: -x[1]
    )[:10]

    top_rit = sorted(
        ritardi.items(),
        key=lambda x: -x[1]
    )[:10]

    top_oro = sorted(
        freq_oro.items(),
        key=lambda x: -x[1]
    )[:5]

    return {
        "frequenze":     {str(k): v for k, v in freq.items()},
        "ritardi":       {str(k): v for k, v in ritardi.items()},
        "freq_oro":      {str(k): v for k, v in freq_oro.items()},
        "top_frequenti": [
            {"numero": k, "frequenza": v}
            for k, v in top_freq
        ],
        "top_ritardi": [
            {"numero": k, "ritardo": v}
            for k, v in top_rit
        ],
        "top_oro": [
            {"numero": k, "frequenza": v}
            for k, v in top_oro
        ],
        "totale_estrazioni": tot
    }

# ══════════════════════════════════════════════
# CARICA STORICO ESISTENTE
# ══════════════════════════════════════════════
def carica_storico():
    if not os.path.exists(FILE_STORICO):
        return []
    try:
        with open(FILE_STORICO, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

# ══════════════════════════════════════════════
# CHIAVE UNIVOCA PER DEDUPLICAZIONE
# ══════════════════════════════════════════════
def chiave(e):
    return f"{e['data']}_{e['concorso']}"

# ══════════════════════════════════════════════
# SCARICA STORICO DA LOTTOLOGIA (fino a 14 giorni)
# Usato solo al primo avvio o se lo storico
# locale è vuoto / ha meno di 100 record
# ══════════════════════════════════════════════
def scarica_storico_lottologia(giorni=14):
    print(f"Scarico storico Lottologia ({giorni} giorni)...")
    risultato = []
    errori_consecutivi = 0

    mesi_lott = {
        "gen":1,"feb":2,"mar":3,"apr":4,
        "mag":5,"giu":6,"lug":7,"ago":8,
        "set":9,"ott":10,"nov":11,"dic":12
    }

    for offset in range(giorni):
        if errori_consecutivi >= 3:
            print(f"  Interrotto dopo 3 errori (offset {offset})")
            break

        if offset == 0:
            url = "https://lottologia.com/10elotto5minuti/estrazioni"
        elif offset == 1:
            url = "https://lottologia.com/10elotto5minuti/estrazioni-ieri"
        else:
            url = f"https://lottologia.com/10elotto5minuti/estrazioni-{offset}gg-fa"

        html = scarica(url)
        if not html:
            errori_consecutivi += 1
            continue

        # Testo puro
        testo = re.sub(r'<script[\s\S]*?</script>', ' ', html, flags=re.IGNORECASE)
        testo = re.sub(r'<style[\s\S]*?</style>',  ' ', testo, flags=re.IGNORECASE)
        testo = re.sub(r'<[^>]+>', ' ', testo)
        testo = testo.replace('&nbsp;', ' ').replace('&amp;', '&')
        testo = re.sub(r'\s+', ' ', testo)

        # Pattern: #116 6 Ago 2026 09:40
        spartiacque = list(re.finditer(
            r'#(\d{1,3})\s+(\d{1,2})\s+([A-Za-z]{3,4})\S*\s+(\d{4})\s+(\d{1,2}):(\d{2})',
            testo, re.IGNORECASE
        ))

        if not spartiacque:
            errori_consecutivi += 1
            print(f"  Giorno {offset}: 0 estrazioni trovate")
            continue

        trovate_giorno = 0
        for i, sm in enumerate(spartiacque):
            try:
                fine = (spartiacque[i+1].start()
                        if i < len(spartiacque)-1
                        else len(testo))
                blocco = testo[sm.start():fine]

                concorso = int(sm.group(1))
                giorno   = int(sm.group(2))
                mese_a   = sm.group(3)[:3].lower()
                anno     = int(sm.group(4))
                ora      = int(sm.group(5))
                minuto   = int(sm.group(6))

                if mese_a not in mesi_lott:
                    continue

                data = datetime(anno, mesi_lott[mese_a],
                                giorno, ora, minuto)

                # Sezione numeri
                idx_num = blocco.lower().find("numeri")
                idx_oro = blocco.lower().find("oro")
                if idx_num < 0 or idx_oro < 0 or idx_oro <= idx_num:
                    continue

                sez_num = blocco[idx_num:idx_oro]
                nums_m  = re.findall(r'\d{2}', sez_num)
                if len(nums_m) < 20:
                    continue

                numeri = [int(x) for x in nums_m[:20]]
                if any(n < 1 or n > 90 for n in numeri):
                    continue

                # Oro
                idx_dop = blocco.lower().find("doppio", idx_oro)
                sez_oro = blocco[idx_oro:idx_dop] if idx_dop > idx_oro else blocco[idx_oro:idx_oro+20]
                oro_m   = re.search(r'\d{2}', sez_oro)
                oro     = int(oro_m.group()) if oro_m else numeri[0]

                # Doppio Oro
                if idx_dop > idx_oro:
                    idx_ext   = blocco.lower().find("extra", idx_dop)
                    fine_dop  = idx_ext if idx_ext > idx_dop else idx_dop + 30
                    sez_dop   = blocco[idx_dop:fine_dop]
                    dop_ms    = re.findall(r'\d{2}', sez_dop)
                    doppio    = int(dop_ms[-1]) if dop_ms else numeri[1]
                else:
                    doppio = numeri[1]

                risultato.append({
                    "data":       data.strftime("%d/%m/%Y"),
                    "orario":     data.strftime("%H:%M"),
                    "concorso":   concorso,
                    "numeri":     numeri,
                    "oro":        oro,
                    "doppio_oro": doppio,
                    "timestamp":  data.strftime("%Y%m%d%H%M")
                })
                trovate_giorno += 1

            except Exception as ex:
                print(f"  Blocco errore: {ex}")
                continue

        print(f"  Giorno {offset}: {trovate_giorno} estrazioni")
        errori_consecutivi = 0

        import time
        time.sleep(1.2)

    return risultato

# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════
def main():
    os.makedirs("data", exist_ok=True)

    # Carica storico esistente
    storico = carica_storico()
    chiavi_esistenti = {chiave(e) for e in storico}

    print(f"Storico locale: {len(storico)} record")

    # Se lo storico è quasi vuoto scarica anche da Lottologia
    if len(storico) < 100:
        print("Storico insufficiente — scarico da Lottologia...")
        storiche = scarica_storico_lottologia(giorni=14)
        aggiunte_stor = 0
        for e in storiche:
            if chiave(e) not in chiavi_esistenti:
                storico.append(e)
                chiavi_esistenti.add(chiave(e))
                aggiunte_stor += 1
        print(f"  Da Lottologia: +{aggiunte_stor} record")

    # Scarica pagina live
    print(f"Scarico pagina live...")
    html = scarica(URL_PRINCIPALE)
    nuove = parsa_pagina(html) if html else []
    print(f"Parsate {len(nuove)} estrazioni dalla pagina live")

    # Aggiungi nuove senza duplicati
    aggiunte = 0
    for e in nuove:
        if chiave(e) not in chiavi_esistenti:
            storico.append(e)
            chiavi_esistenti.add(chiave(e))
            aggiunte += 1

    # Ordina e limita
    storico.sort(key=lambda x: x["timestamp"])
    if len(storico) > MAX_STORICO:
        storico = storico[-MAX_STORICO:]

    print(f"+{aggiunte} nuove, totale storico: {len(storico)}")

    # Calcola statistiche
    stats = calcola_statistiche(storico)

    # Ultima estrazione
    ultima = storico[-1] if storico else None

    # ── OUTPUT 1: estrazioni.json ──
    output = {
        "aggiornato_il": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "totale":        len(storico),
        "ultima":        ultima,
        "ultime_10":     storico[-10:][::-1],
        "ultime_288":    storico[-288:][::-1],
        "statistiche":   stats
    }

    with open(FILE_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # ── OUTPUT 2: storico.json ──
    with open(FILE_STORICO, "w", encoding="utf-8") as f:
        json.dump(storico, f, ensure_ascii=False)

    # ── OUTPUT 3: ultima.json ──
    with open("data/ultima.json", "w", encoding="utf-8") as f:
        json.dump({
            "aggiornato_il": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "ultima": ultima
        }, f, ensure_ascii=False)

    print(f"✓ JSON aggiornati con successo")
    print(f"  → data/estrazioni.json")
    print(f"  → data/storico.json")
    print(f"  → data/ultima.json")

if __name__ == "__main__":
    main()
