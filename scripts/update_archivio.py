import requests
import re
import csv
import os
import sys
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# ============================================================================
# CONFIGURAZIONE FONTI A CASCATA
# ============================================================================
FONTI = [
    {"nome": "Lottologia", "url": "https://www.lottologia.com/10elotto/estrazioni/"},
    {"nome": "Estrazioni-Lotto", "url": "https://www.estrazioni-del-lotto-e-10elotto.it/10elotto-serale"},
    {"nome": "Lotto.it", "url": "https://www.lotto.it/10eLotto/Estrazioni"},
    {"nome": "ADM-Monopoli", "url": "https://www.adm.gov.it/portale/web/guest/10elotto-estrazioni"}
]

CSV_PATH = "data/archivio_serale.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}

MESI = {
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12
}

# ============================================================================
# PARSER GENERICO (Simile a quello VB.NET)
# ============================================================================
def parse_generico(html, nome_fonte):
    estrazioni = []
    # Pulizia HTML
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup(["script", "style"]):
        script.extract()
    testo = soup.get_text(separator=" ")
    testo = re.sub(r'\s+', ' ', testo).strip()

    # Cerca date (dd/mm/yyyy o dd mm yyyy)
    rx_data = re.compile(r'\b(\d{1,2})[/\-\s](\d{1,2}|[A-Za-z]{3})[/\-\s](\d{2,4})\b', re.IGNORECASE)
    matches = list(rx_data.finditer(testo))

    for i, m in enumerate(matches):
        try:
            giorno = int(m.group(1))
            mese_str = m.group(2)
            anno_str = m.group(3)

            if mese_str.isdigit():
                mese = int(mese_str)
            elif mese_str.lower() in MESI:
                mese = MESI[mese_str.lower()]
            else:
                continue

            anno = int(anno_str)
            if anno < 100: anno += 2000

            data_estr = datetime(anno, mese, giorno, 20, 0, 0)
            
            # Blocco di testo fino alla prossima data
            start = m.end()
            end = matches[i+1].start() if i + 1 < len(matches) else len(testo)
            if end - start > 2000: end = start + 2000
            
            blocco = testo[start:end]
            
            # Estrai numeri 1-90
            nums = [int(n) for n in re.findall(r'\b([1-9]|[1-8]\d|90)\b', blocco)]
            unici = list(dict.fromkeys(nums)) # Mantiene ordine e rimuove duplicati
            
            if len(unici) < 20:
                continue
                
            primi_20 = unici[:20]
            
            # Validazione base (somma e range)
            if sum(primi_20) < 500 or sum(primi_20) > 1350:
                continue
                
            # Ricerca Oro/Doppio (euristica semplice)
            oro = primi_20[0]
            doppio = primi_20[1]
            
            # Salvataggio
            estrazioni.append({
                "data": data_estr.strftime("%d/%m/%Y %H:%M"),
                "concorso": (data_estr.timetuple().tm_yday),
                "numeri": " ".join(f"{n:02d}" for n in primi_20),
                "oro": oro,
                "doppio": doppio,
                "fonte": nome_fonte
            })
        except Exception as e:
            continue
            
    return estrazioni

# ============================================================================
# MAIN
# ============================================================================
def main():
    print(f"[{datetime.now()}] Avvio aggiornamento archivio...")
    
    # 1. Leggi CSV esistente
    archivio_esistente = {}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                # Usa la data come chiave univoca
                archivio_esistente[row['Data'].split()[0]] = row

    nuove_aggiunte = 0
    fonte_vincente = "Nessuna"

    # 2. Prova le fonti a cascata
    for fonte in FONTI:
        print(f"-> Tentativo su {fonte['nome']}...")
        try:
            resp = requests.get(fonte['url'], headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                dati = parse_generico(resp.text, fonte['nome'])
                if len(dati) > 0:
                    print(f"   OK! Trovate {len(dati)} estrazioni da {fonte['nome']}")
                    fonte_vincente = fonte['nome']
                    
                    # Merge con archivio esistente
                    for d in dati:
                        chiave_data = d['data'].split()[0]
                        if chiave_data not in archivio_esistente:
                            archivio_esistente[chiave_data] = {
                                "Data": d['data'],
                                "Concorso": d['concorso'],
                                "Numeri": d['numeri'],
                                "Oro": d['oro'],
                                "DoppioOro": d['doppio']
                            }
                            nuove_aggiunte += 1
                    break # Esce dal ciclo: la prima fonte valida vince
        except Exception as e:
            print(f"   Fallito ({fonte['nome']}): {e}")
            continue

    # 3. Salva il CSV aggiornato
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["Data", "Concorso", "Numeri", "Oro", "DoppioOro"], delimiter=';')
        writer.writeheader()
        
        # Ordina per data crescente
        sorted_data = sorted(archivio_esistente.values(), key=lambda x: datetime.strptime(x['Data'], "%d/%m/%Y %H:%M"))
        writer.writerows(sorted_data)

    print(f"[{datetime.now()}] Fine. Fonte usata: {fonte_vincente}. Nuove aggiunte: {nuove_aggiunte}. Totale: {len(archivio_esistente)}")
    
    if nuove_aggiunte == 0 and fonte_vincente == "Nessuna":
        sys.exit(1) # Fallisce la Action se non trova nulla

if __name__ == "__main__":
    main()
