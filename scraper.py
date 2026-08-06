#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper multi-fonte 10eLotto 5 minuti
Ordine fallback:
  A) 10elottoogni5minuti.it  (live)
  B) lottologia.com
  C) 10elotto5.it
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timedelta
from pathlib import Path

import requests

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

MESI_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    "gen": 1, "feb": 2, "mar": 3, "apr": 4,
    "mag": 5, "giu": 6, "lug": 7, "ago": 8,
    "set": 9, "ott": 10, "nov": 11, "dic": 12,
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ─────────────────────────────────────────────────────────────
# UTILITÀ
# ─────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    print(f"[{datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC] {msg}")


def get_html(url: str, timeout: int = 30) -> str | None:
    try:
        r = SESSION.get(url, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as ex:
        log(f"  ✗ GET fallita {url} → {ex}")
        return None


def testo_puro(html: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    t = re.sub(r"\s+", " ", t)
    return t


def key_of(row: dict) -> tuple[str, str]:
    """Chiave univoca: giorno + concorso."""
    giorno = (row.get("Data") or "")[:10]
    return (giorno, str(row.get("Concorso", "")).strip())


def load_existing() -> tuple[list[dict], set[tuple[str, str]]]:
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    if not OUT.exists():
        return rows, seen
    with OUT.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            if not row.get("Concorso"):
                continue
            k = key_of(row)
            if k in seen:
                continue
            seen.add(k)
            rows.append(row)
    return rows, seen


def save(rows: list[dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    def sk(r: dict):
        try:
            dt = datetime.strptime(r["Data"], "%d/%m/%Y %H:%M")
        except Exception:
            try:
                dt = datetime.strptime(r["Data"][:10], "%d/%m/%Y")
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


def row_dict(data: datetime, concorso: int, numeri: list[int],
             oro: int, doppio: int) -> dict:
    return {
        "Data": data.strftime("%d/%m/%Y %H:%M"),
        "Concorso": str(concorso),
        "Numeri": " ".join(str(n) for n in numeri),
        "Oro": str(oro),
        "DoppioOro": str(doppio),
    }


def valida_numeri(nums: list[int]) -> bool:
    return len(nums) >= 20 and all(1 <= n <= 90 for n in nums[:20])


# ─────────────────────────────────────────────────────────────
# FONTE A — 10elottoogni5minuti.it (LIVE)
# ─────────────────────────────────────────────────────────────
def parse_fonte_a(html: str) -> list[dict]:
    out: list[dict] = []
    blocks = re.split(r'"sezione"|<h1', html, flags=re.I)

    for blocco in blocks:
        m = re.search(
            r"n\.\s*(\d+)\s+di\s+\w+\s+(\d{1,2})\s+(\w+)\s+(\d{4})",
            blocco, flags=re.I,
        )
        if not m:
            continue

        concorso = int(m.group(1))
        giorno = int(m.group(2))
        mese = MESI_IT.get(m.group(3).lower())
        anno = int(m.group(4))
        if not mese or concorso < 1:
            continue

        nums = re.findall(
            r'<p\s+class="numero\s+bg-green-600">(\d{1,2})</p>',
            blocco, flags=re.I,
        )
        if len(nums) < 20:
            continue
        numeri = [int(x) for x in nums[:20]]
        if not valida_numeri(numeri):
            continue

        oro_m = re.search(
            r'<p\s+class="numero[^"]*bg-yellow-300">(\d{1,2})</p>',
            blocco, flags=re.I,
        )
        doppio_m = re.search(
            r'<p\s+class="numero[^"]*bg-yellow-400">(\d{1,2})</p>',
            blocco, flags=re.I,
        )
        oro = int(oro_m.group(1)) if oro_m else numeri[0]
        doppio = int(doppio_m.group(1)) if doppio_m else numeri[1]
        if not (1 <= oro <= 90 and 1 <= doppio <= 90):
            continue

        if 1 <= concorso <= 288:
            mt = (concorso * 5) % 1440
            hh, mm = divmod(mt, 60)
        else:
            hh, mm = 0, 0

        try:
            data = datetime(anno, mese, giorno, hh, mm)
        except ValueError:
            continue

        out.append(row_dict(data, concorso, numeri, oro, doppio))
    return out


def scarica_fonte_a() -> list[dict]:
    url = "https://10elottoogni5minuti.it/"
    log(f"FONTE A → {url}")
    html = get_html(url)
    if not html:
        return []
    rows = parse_fonte_a(html)
    log(f"  → {len(rows)} estrazioni da fonte A")
    return rows


# ─────────────────────────────────────────────────────────────
# PARSER GENERICO (Lottologia / 10elotto5.it)
# ─────────────────────────────────────────────────────────────
def parse_generico(html: str) -> list[dict]:
    """Parser flessibile su testo pulito da HTML."""
    out: list[dict] = []
    testo = testo_puro(html)

    pattern = (
        r"(?:#|N°|N\.|Concorso\s*n?\.?|Estrazione\s*n?\.?)\s*(\d{1,4})"
        r"[\s\S]{0,80}?"
        r"(?:"
        r"(\d{1,2})\s+([A-Za-zàèéìòù]{3,9})\S*\s+(\d{4})\s+(\d{1,2}):(\d{2})"
        r"|"
        r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\s+(\d{1,2}):(\d{2})"
        r")"
    )

    try:
        matches = list(re.finditer(pattern, testo, flags=re.I))
    except re.error:
        return out

    for i, m in enumerate(matches):
        try:
            inizio = m.start()
            fine = matches[i + 1].start() if i + 1 < len(matches) else len(testo)
            blocco = testo[inizio:fine]

            concorso = int(m.group(1))

            if m.group(2):
                giorno = int(m.group(2))
                mese_txt = m.group(3)[:3].lower()
                mese = MESI_IT.get(mese_txt) or MESI_IT.get(m.group(3).lower())
                anno = int(m.group(4))
                hh = int(m.group(5))
                mm = int(m.group(6))
            else:
                giorno = int(m.group(7))
                mese = int(m.group(8))
                anno = int(m.group(9))
                hh = int(m.group(10))
                mm = int(m.group(11))

            if not mese:
                continue
            try:
                data = datetime(anno, mese, giorno, hh, mm)
            except ValueError:
                continue

            m_num = re.search(r"Numeri|Estratti|Combinazione", blocco, flags=re.I)
            m_oro = re.search(
                r"Numero\s*Oro|(?<!Doppio\s)(?<!Extra\s)Oro\b",
                blocco, flags=re.I,
            )
            if not m_num or not m_oro or m_oro.start() <= m_num.start():
                # fallback: prendi i primi 20 numeri 1-90 nel blocco
                nums_all = [int(x) for x in re.findall(r"\b(\d{1,2})\b", blocco)]
                nums_all = [n for n in nums_all if 1 <= n <= 90]
                # salta concorso/data già parsati: prendi da un po' dopo
                if len(nums_all) < 22:
                    continue
                # euristica: dopo i token data restano i 20 + oro + doppio
                numeri = nums_all[-22:-2][:20] if len(nums_all) >= 22 else nums_all[:20]
                if len(numeri) < 20:
                    continue
                oro = nums_all[-2] if len(nums_all) >= 2 else numeri[0]
                doppio = nums_all[-1] if len(nums_all) >= 1 else numeri[1]
            else:
                sezione_num = blocco[m_num.start():m_oro.start()]
                nums_m = re.findall(r"\b(\d{1,2})\b", sezione_num)
                if len(nums_m) < 20:
                    continue
                numeri = [int(x) for x in nums_m[:20]]
                if not valida_numeri(numeri):
                    continue

                m_doppio = re.search(r"Doppio\s*Oro|Extra\s*Oro", blocco, flags=re.I)
                fine_oro = (
                    m_doppio.start()
                    if m_doppio and m_doppio.start() > m_oro.start()
                    else len(blocco)
                )
                sezione_oro = blocco[m_oro.start():fine_oro]
                oro_m = re.search(r"\d{1,2}", sezione_oro)
                oro = int(oro_m.group()) if oro_m else numeri[0]

                doppio = numeri[1]
                if m_doppio:
                    sezione_d = blocco[m_doppio.start():m_doppio.start() + 80]
                    dm = re.findall(r"\d{1,2}", sezione_d)
                    if dm:
                        v = int(dm[-1])
                        if 1 <= v <= 90:
                            doppio = v

            if not (1 <= oro <= 90 and 1 <= doppio <= 90):
                continue
            if not valida_numeri(numeri):
                continue

            # evita duplicati nello stesso batch
            if any(
                r["Concorso"] == str(concorso) and r["Data"][:10] == data.strftime("%d/%m/%Y")
                for r in out
            ):
                continue

            out.append(row_dict(data, concorso, numeri[:20], oro, doppio))
        except Exception:
            continue

    return out


# ─────────────────────────────────────────────────────────────
# FONTE B — Lottologia
# ─────────────────────────────────────────────────────────────
def urls_lottologia(giorni: int = 3) -> list[str]:
    """Ultime N giornate (oggi, ieri, N gg fa + formato data assoluta)."""
    urls: list[str] = []
    today = datetime.utcnow().date()
    # formato relativo
    urls.append("https://lottologia.com/10elotto5minuti/estrazioni")
    urls.append("https://lottologia.com/10elotto5minuti/estrazioni-ieri")
    for offset in range(2, giorni + 1):
        urls.append(
            f"https://lottologia.com/10elotto5minuti/estrazioni-{offset}gg-fa"
        )
    # formato assoluto
    for offset in range(0, giorni + 1):
        d = today - timedelta(days=offset)
        urls.append(
            f"https://lottologia.com/10elotto5minuti/estrazioni-{d:%Y-%m-%d}"
        )
    # dedup mantenendo ordine
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def scarica_fonte_b(giorni: int = 3) -> list[dict]:
    log("FONTE B → Lottologia")
    collected: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for url in urls_lottologia(giorni):
        log(f"  prova {url}")
        html = get_html(url)
        if not html:
            continue
        rows = parse_generico(html)
        # se il generico fallisce, prova anche parser "numeri in pagina" grezzo
        if not rows:
            rows = parse_fonte_a(html)  # a volte stesso markup
        n_new = 0
        for r in rows:
            k = key_of(r)
            if k not in seen:
                seen.add(k)
                collected.append(r)
                n_new += 1
        log(f"    → {len(rows)} lette, +{n_new} uniche")
        if n_new:
            # una pagina utile basta per andare avanti sulle altre
            pass

    log(f"  → totale fonte B: {len(collected)}")
    return collected


# ─────────────────────────────────────────────────────────────
# FONTE C — 10elotto5.it
# ─────────────────────────────────────────────────────────────
def urls_10elotto5(giorni: int = 3) -> list[str]:
    today = datetime.utcnow().date()
    urls = []
    for offset in range(0, giorni + 1):
        d = today - timedelta(days=offset)
        urls.append(
            f"https://www.10elotto5.it/archivio-10elotto5-minuti/{d:%Y-%m-%d}"
        )
        urls.append(
            f"https://www.10elotto5.it/estrazioni-10elotto-ogni-5-minuti/{d:%d-%m-%Y}"
        )
    return urls


def scarica_fonte_c(giorni: int = 3) -> list[dict]:
    log("FONTE C → 10elotto5.it")
    collected: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for url in urls_10elotto5(giorni):
        log(f"  prova {url}")
        html = get_html(url)
        if not html:
            continue
        rows = parse_generico(html)
        if not rows:
            rows = parse_fonte_a(html)
        n_new = 0
        for r in rows:
            k = key_of(r)
            if k not in seen:
                seen.add(k)
                collected.append(r)
                n_new += 1
        log(f"    → {len(rows)} lette, +{n_new} uniche")

    log(f"  → totale fonte C: {len(collected)}")
    return collected


# ─────────────────────────────────────────────────────────────
# MAIN — fallback a cascata
# ─────────────────────────────────────────────────────────────
def main() -> None:
    log("=== Avvio scraper multi-fonte 10eLotto ===")

    rows, seen = load_existing()
    log(f"Archivio esistente: {len(rows)} righe")

    tutte: list[dict] = []
    fonti_ok: list[str] = []

    # A — sempre provata
    a = scarica_fonte_a()
    if a:
        tutte.extend(a)
        fonti_ok.append(f"A:{len(a)}")
    else:
        log("FONTE A senza dati — attivo fallback")

    # B — se A ha dato poco O sempre come integrazione delle ultime 3 giornate
    # Strategia: se A >= 1 usa B solo come supplemento leggero (1 giorno)
    #            se A == 0 usa B in modo più ampio (3 giorni)
    giorni_b = 3 if not a else 1
    b = scarica_fonte_b(giorni=giorni_b)
    if b:
        tutte.extend(b)
        fonti_ok.append(f"B:{len(b)}")

    # C — solo se A e B insieme hanno 0, oppure come ulteriore scorta se poco
    if len(a) + len(b) == 0:
        log("A+B vuote — provo fonte C ampia")
        c = scarica_fonte_c(giorni=3)
    elif len(a) + len(b) < 3:
        log("Pochi dati da A+B — integro con fonte C")
        c = scarica_fonte_c(giorni=1)
    else:
        c = []

    if c:
        tutte.extend(c)
        fonti_ok.append(f"C:{len(c)}")

    if not tutte:
        log("⚠ NESSUNA fonte ha restituito dati. Archivio invariato.")
        # riscrive comunque l'esistente (no-op utile al log Actions)
        save(rows)
        print("Lette: 0 | Nuove: 0 | Totale:", len(rows))
        return

    added = 0
    for e in tutte:
        k = key_of(e)
        if k not in seen:
            rows.append(e)
            seen.add(k)
            added += 1

    save(rows)
    log(f"Fonti usate: {', '.join(fonti_ok) if fonti_ok else 'nessuna'}")
    print(f"Lette batch: {len(tutte)} | Nuove: {added} | Totale archivio: {len(rows)}")
    log("=== Fine ===")


if __name__ == "__main__":
    main()
