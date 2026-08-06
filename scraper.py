#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper multi-fonte 10eLotto 5 minuti
Prova le fonti in ordine; unisce i risultati senza duplicati.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timedelta
from pathlib import Path

import requests

OUT = Path("data/archivio.csv")

# ══════════════════════════════════════════════════════════════
# ELENCO FONTI — ordine = priorità
# tipo "live"    = pagina ultime estrazioni
# tipo "storico" = pagina/archivio (anche per data)
# ══════════════════════════════════════════════════════════════
FONTI = [
    {
        "nome": "10elottoogni5minuti.it",
        "url": "https://10elottoogni5minuti.it/",
        "tipo": "live",
    },
    {
        "nome": "Lottologia",
        "url": "https://lottologia.com/10elotto5minuti/estrazioni",
        "tipo": "storico",
    },
    {
        "nome": "10elotto5.it",
        "url": "https://www.10elotto5.it/archivio-10elotto5-minuti/",
        "tipo": "storico",
    },
    {
        "nome": "Lotto-Italia",
        "url": "https://www.lotto-italia.it/10elotto/",
        "tipo": "storico",
    },
    {
        "nome": "EstrazioniDelLotto",
        "url": "https://www.estrazionidellotto.it/10elotto",
        "tipo": "storico",
    },
]

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
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def log(msg: str) -> None:
    print(f"[{datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC] {msg}")


def get_html(url: str, timeout: int = 30) -> str | None:
    try:
        r = SESSION.get(url, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as ex:
        log(f"  ✗ download fallito: {ex}")
        return None


def testo_puro(html: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    t = re.sub(r"\s+", " ", t)
    return t


def key_of(row: dict) -> tuple[str, str]:
    return ((row.get("Data") or "")[:10], str(row.get("Concorso", "")).strip())


def load_existing() -> tuple[list[dict], set[tuple[str, str]]]:
    rows, seen = [], set()
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


def make_row(data: datetime, concorso: int, numeri: list[int],
             oro: int, doppio: int) -> dict:
    return {
        "Data": data.strftime("%d/%m/%Y %H:%M"),
        "Concorso": str(concorso),
        "Numeri": " ".join(str(n) for n in numeri[:20]),
        "Oro": str(oro),
        "DoppioOro": str(doppio),
    }


def ok_numeri(numeri: list[int]) -> bool:
    return len(numeri) >= 20 and all(1 <= n <= 90 for n in numeri[:20])


# ─────────────────────────────────────────────────────────────
# PARSER LIVE (sito A — markup green/yellow)
# ─────────────────────────────────────────────────────────────
def parse_live_markup(html: str) -> list[dict]:
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
        mese = MESI.get(m.group(3).lower())
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
        if not ok_numeri(numeri):
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

        out.append(make_row(data, concorso, numeri, oro, doppio))
    return out


# ─────────────────────────────────────────────────────────────
# PARSER GENERICO (testo pagina — storico / altri siti)
# ─────────────────────────────────────────────────────────────
def parse_generico(html: str) -> list[dict]:
    out: list[dict] = []
    testo = testo_puro(html)

    pattern = (
        r"(?:#|N°|N\.|Concorso\s*n?\.?|Estrazione\s*n?\.?)\s*(\d{1,4})"
        r"[\s\S]{0,100}?"
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
                mese = MESI.get(m.group(3)[:3].lower()) or MESI.get(m.group(3).lower())
                anno = int(m.group(4))
                hh, mm = int(m.group(5)), int(m.group(6))
            else:
                giorno = int(m.group(7))
                mese = int(m.group(8))
                anno = int(m.group(9))
                hh, mm = int(m.group(10)), int(m.group(11))

            if not mese:
                continue
            try:
                data = datetime(anno, int(mese), giorno, hh, mm)
            except ValueError:
                continue

            # prova etichette Numeri/Oro
            m_num = re.search(r"Numeri|Estratti|Combinazione", blocco, flags=re.I)
            m_oro = re.search(
                r"Numero\s*Oro|(?<!Doppio\s)(?<!Extra\s)Oro\b",
                blocco, flags=re.I,
            )

            if m_num and m_oro and m_oro.start() > m_num.start():
                sezione = blocco[m_num.start():m_oro.start()]
                nums = [int(x) for x in re.findall(r"\b(\d{1,2})\b", sezione)]
                nums = [n for n in nums if 1 <= n <= 90]
                if len(nums) < 20:
                    continue
                numeri = nums[:20]
                m_dop = re.search(r"Doppio\s*Oro|Extra\s*Oro", blocco, flags=re.I)
                fine_oro = m_dop.start() if m_dop and m_dop.start() > m_oro.start() else len(blocco)
                so = blocco[m_oro.start():fine_oro]
                om = re.search(r"\d{1,2}", so)
                oro = int(om.group()) if om else numeri[0]
                doppio = numeri[1]
                if m_dop:
                    sd = blocco[m_dop.start():m_dop.start() + 80]
                    dm = re.findall(r"\d{1,2}", sd)
                    if dm:
                        v = int(dm[-1])
                        if 1 <= v <= 90:
                            doppio = v
            else:
                # fallback: sequenza di numeri 1-90 nel blocco
                nums = [int(x) for x in re.findall(r"\b(\d{1,2})\b", blocco)]
                nums = [n for n in nums if 1 <= n <= 90]
                if len(nums) < 22:
                    continue
                numeri = nums[:20]
                oro = nums[20] if len(nums) > 20 else numeri[0]
                doppio = nums[21] if len(nums) > 21 else numeri[1]

            if not ok_numeri(numeri):
                continue
            if not (1 <= oro <= 90 and 1 <= doppio <= 90):
                continue

            k = (data.strftime("%d/%m/%Y"), str(concorso))
            if any(
                r["Concorso"] == str(concorso) and r["Data"][:10] == k[0]
                for r in out
            ):
                continue
            out.append(make_row(data, concorso, numeri, oro, doppio))
        except Exception:
            continue
    return out


def parse_qualsiasi(html: str) -> list[dict]:
    """Prova prima markup live, poi parser generico."""
    rows = parse_live_markup(html)
    if rows:
        return rows
    return parse_generico(html)


# ─────────────────────────────────────────────────────────────
# URL extra per fonti "storico" (oggi / ieri / date)
# ─────────────────────────────────────────────────────────────
def urls_per_fonte(fonte: dict, giorni: int = 2) -> list[str]:
    nome = fonte["nome"]
    base = fonte["url"].rstrip("/") + "/"
    today = datetime.utcnow().date()
    urls = [fonte["url"]]

    if nome == "Lottologia":
        urls += [
            "https://lottologia.com/10elotto5minuti/estrazioni",
            "https://lottologia.com/10elotto5minuti/estrazioni-ieri",
        ]
        for off in range(2, giorni + 1):
            urls.append(
                f"https://lottologia.com/10elotto5minuti/estrazioni-{off}gg-fa"
            )
        for off in range(0, giorni + 1):
            d = today - timedelta(days=off)
            urls.append(
                f"https://lottologia.com/10elotto5minuti/estrazioni-{d:%Y-%m-%d}"
            )

    elif nome == "10elotto5.it":
        for off in range(0, giorni + 1):
            d = today - timedelta(days=off)
            urls.append(
                f"https://www.10elotto5.it/archivio-10elotto5-minuti/{d:%Y-%m-%d}"
            )
            urls.append(
                f"https://www.10elotto5.it/estrazioni-10elotto-ogni-5-minuti/{d:%d-%m-%Y}"
            )

    elif nome == "Lotto-Italia":
        # homepage sezione + eventuali variazioni comuni
        urls += [
            "https://www.lotto-italia.it/10elotto/",
            "https://www.lotto-italia.it/10e-lotto/",
            "https://www.lotto-italia.it/10elotto/estrazioni",
        ]

    elif nome == "EstrazioniDelLotto":
        urls += [
            "https://www.estrazionidellotto.it/10elotto",
            "https://www.estrazionidellotto.it/10e-lotto",
            "https://www.estrazionidellotto.it/estrazioni-10elotto",
        ]

    # dedup ordine
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def scarica_fonte(fonte: dict) -> list[dict]:
    log(f"FONTE: {fonte['nome']} ({fonte['tipo']}) → {fonte['url']}")
    collected: list[dict] = []
    seen: set[tuple[str, str]] = set()

    # live: 1 URL; storico: più URL/giorni
    giorni = 0 if fonte["tipo"] == "live" else 2
    lista_url = urls_per_fonte(fonte, giorni=giorni)

    for url in lista_url:
        log(f"  GET {url}")
        html = get_html(url)
        if not html:
            continue
        rows = parse_qualsiasi(html)
        n = 0
        for r in rows:
            k = key_of(r)
            if k not in seen:
                seen.add(k)
                collected.append(r)
                n += 1
        log(f"    lette={len(rows)} uniche_nuove_batch={n}")

    log(f"  ⇒ totale {fonte['nome']}: {len(collected)}")
    return collected


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main() -> None:
    log("=== Avvio scraper multi-fonte ===")
    rows, seen = load_existing()
    log(f"Archivio già presente: {len(rows)} righe")

    batch: list[dict] = []
    report: list[str] = []

    for fonte in FONTI:
        try:
            trovate = scarica_fonte(fonte)
            report.append(f"{fonte['nome']}={len(trovate)}")
            batch.extend(trovate)
        except Exception as ex:
            log(f"  ✗ errore fonte {fonte['nome']}: {ex}")
            report.append(f"{fonte['nome']}=ERR")

    if not batch:
        log("⚠ Nessuna fonte ha dato dati. Archivio invariato.")
        save(rows)
        print("Lette: 0 | Nuove: 0 | Totale:", len(rows))
        print("Report:", ", ".join(report))
        return

    added = 0
    for e in batch:
        k = key_of(e)
        if k not in seen:
            seen.add(k)
            rows.append(e)
            added += 1

    save(rows)
    print(f"Lette batch: {len(batch)} | Nuove: {added} | Totale: {len(rows)}")
    print("Report fonti:", ", ".join(report))
    log("=== Fine ===")


if __name__ == "__main__":
    main()
