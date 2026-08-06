#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import csv
import re
from datetime import datetime
from pathlib import Path

import requests

URL = "https://10elottoogni5minuti.it/"
OUT = Path("data/archivio.csv")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "it-IT,it;q=0.9",
}

MESI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


def load_existing():
    rows, seen = [], set()
    if not OUT.exists():
        return rows, seen
    with OUT.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            if not row.get("Concorso"):
                continue
            key = ((row.get("Data") or "")[:10], str(row["Concorso"]).strip())
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows, seen


def parse_live(html: str):
    out = []
    blocks = re.split(r'"sezione"|<h1', html, flags=re.I)

    for blocco in blocks:
        m = re.search(
            r"n\.\s*(\d+)\s+di\s+\w+\s+(\d{1,2})\s+(\w+)\s+(\d{4})",
            blocco,
            flags=re.I,
        )
        if not m:
            continue

        concorso = int(m.group(1))
        giorno = int(m.group(2))
        mese = MESI.get(m.group(3).lower())
        anno = int(m.group(4))
        if not mese or concorso < 1:
            continue

        nums = re.findall(
            r'<p\s+class="numero\s+bg-green-600">(\d{1,2})</p>',
            blocco,
            flags=re.I,
        )
        if len(nums) < 20:
            continue

        numeri = [int(x) for x in nums[:20]]
        if any(n < 1 or n > 90 for n in numeri):
            continue

        oro_m = re.search(
            r'<p\s+class="numero[^"]*bg-yellow-300">(\d{1,2})</p>',
            blocco,
            flags=re.I,
        )
        doppio_m = re.search(
            r'<p\s+class="numero[^"]*bg-yellow-400">(\d{1,2})</p>',
            blocco,
            flags=re.I,
        )
        oro = int(oro_m.group(1)) if oro_m else numeri[0]
        doppio = int(doppio_m.group(1)) if doppio_m else numeri[1]

        if 1 <= concorso <= 288:
            mt = (concorso * 5) % 1440
            hh, mm = divmod(mt, 60)
        else:
            hh, mm = 0, 0

        try:
            data = datetime(anno, mese, giorno, hh, mm)
        except ValueError:
            continue

        out.append({
            "Data": data.strftime("%d/%m/%Y %H:%M"),
            "Concorso": str(concorso),
            "Numeri": " ".join(str(n) for n in numeri),
            "Oro": str(oro),
            "DoppioOro": str(doppio),
        })
    return out


def save(rows):
    OUT.parent.mkdir(parents=True, exist_ok=True)

    def sk(r):
        try:
            dt = datetime.strptime(r["Data"], "%d/%m/%Y %H:%M")
        except Exception:
            dt = datetime.min
        try:
            c = int(r["Concorso"])
        except Exception:
            c = 0
        return dt, c

    rows = sorted(rows, key=sk)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["Data", "Concorso", "Numeri", "Oro", "DoppioOro"],
            delimiter=";",
        )
        w.writeheader()
        w.writerows(rows)


def main():
    print(f"[{datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC] Download...")
    r = requests.get(URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    nuove = parse_live(r.text)
    rows, seen = load_existing()
    added = 0

    for e in nuove:
        key = (e["Data"][:10], e["Concorso"])
        if key not in seen:
            rows.append(e)
            seen.add(key)
            added += 1

    save(rows)
    print(f"Lette: {len(nuove)} | Nuove: {added} | Totale: {len(rows)}")


if __name__ == "__main__":
    main()
