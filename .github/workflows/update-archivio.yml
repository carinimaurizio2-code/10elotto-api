#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Archivio 10eLotto SERALE 20:00 — Lottoced (+ fallback Lottologia)."""

from __future__ import annotations

import datetime as dt
import pathlib
import re
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "archivio_serale.csv"
LOG_PATH = ROOT / "data" / "LAST_RUN.txt"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

URL_YEAR = "https://www.lottoced.com/10elotto/estrazioni/?anno={year}"
URL_LOTTOLOGIA = "https://www.lottologia.com/10elotto/estrazioni/.csv"

RX_NUM = re.compile(r"\b([1-9]|[1-8]\d|90)\b")
RX_DATA = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
RX_ORA = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,text/csv,*/*;q=0.9",
            "Accept-Language": "it-IT,it;q=0.9",
            "Referer": "https://www.lottoced.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        raw = resp.read()
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def strip_html(html: str) -> str:
    html = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = (
        html.replace("&nbsp;", " ")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
        .replace("&amp;", "&")
    )
    return re.sub(r"\s+", " ", html)


def valida(row: dict, require_oro: bool = True) -> bool:
    nums = row.get("numeri") or []
    if int(row.get("concorso") or 0) < 1 or len(nums) < 20:
        return False
    primi = [int(n) for n in nums[:20]]
    if any(n < 1 or n > 90 for n in primi):
        return False
    if len(set(primi)) != 20:
        return False
    oro = int(row.get("oro") or 0)
    doppio = int(row.get("doppio") or 0)
    if require_oro:
        if oro < 1 or doppio < 1:
            return False
        if oro not in primi or doppio not in primi:
            return False
    else:
        if oro and oro not in primi:
            row["oro"] = 0
        if doppio and doppio not in primi:
            row["doppio"] = 0
    row["numeri"] = primi
    return True


def chiave(row: dict) -> tuple:
    return (row["data"].date().isoformat(), int(row["concorso"]))


def parse_data_solo(s: str):
    try:
        return dt.datetime.strptime(s.strip(), "%d/%m/%Y")
    except ValueError:
        return None


def is_serale_ora(h: int, m: int) -> bool:
    return h == 20 and m == 0


def parse_lottoced(html: str) -> list[dict]:
    """Estrae righe serali 20:00 dal testo pagina."""
    text = strip_html(html)
    out, seen = [], set()

    # Trova tutte le date e lavora a blocchi tra una data e la successiva
    matches = list(RX_DATA.finditer(text))
    log(f"    date trovate in pagina: {len(matches)}")
    if matches:
        # piccolo campione debug
        log(f"    campione testo: {text[:250]!r}")

    for i, m in enumerate(matches):
        d0 = parse_data_solo(m.group(1))
        if d0 is None:
            continue
        if d0.year < 2009:
            continue

        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(text), start + 500)
        blocco = text[start:end]

        # Deve essere fascia serale 20:00 (o testo 'serale')
        ore = [(int(a), int(b)) for a, b in RX_ORA.findall(blocco)]
        has_2000 = any(is_serale_ora(h, mi) for h, mi in ore)
        has_serale_word = bool(re.search(r"\bserale\b", blocco, re.I))
        if ore and not has_2000 and not has_serale_word:
            continue
        if not ore and not has_serale_word:
            # molte pagine annuali = 1 riga al giorno già serale: tieni
            pass

        nums = [int(x) for x in RX_NUM.findall(blocco)]
        # togli giorno/mese/anno confusi: cerca finestra di 20 distinti
        scelti = None
        for off in range(0, max(1, len(nums) - 19)):
            win = nums[off : off + 20]
            if len(win) == 20 and len(set(win)) == 20:
                # evita finestre che sono quasi solo date (improbabile con 20 distinti)
                scelti = win
                break
        if not scelti:
            continue

        # concorso: numero 1-4 cifre nel blocco, non tra i 20 se possibile
        concorso = 0
        mc = re.search(r"(?:concorso|n\.|n°|#)\s*(\d{1,4})", blocco, re.I)
        if mc:
            concorso = int(mc.group(1))
        if concorso < 1:
            # prova token isolati dopo la data
            after = blocco[10:80]
            for tok in re.findall(r"\b(\d{1,4})\b", after):
                v = int(tok)
                if 1 <= v <= 9999 and v not in scelti[:5]:
                    concorso = v
                    break
        if concorso < 1:
            concorso = d0.timetuple().tm_yday

        oro, doppio = 0, 0
        mo = re.search(r"(?<!doppio\s)oro\s*[:=]?\s*(\d{1,2})", blocco, re.I)
        md = re.search(r"doppio\s*oro\s*[:=]?\s*(\d{1,2})", blocco, re.I)
        if mo:
            oro = int(mo.group(1))
        if md:
            doppio = int(md.group(1))
        # fallback: ultimi due numeri del blocco se sono dentro i 20
        if oro < 1 or doppio < 1:
            tail = [int(x) for x in RX_NUM.findall(blocco)]
            if len(tail) >= 22:
                c1, c2 = tail[-2], tail[-1]
                if c1 in scelti:
                    oro = c1
                if c2 in scelti:
                    doppio = c2

        row = {
            "data": dt.datetime(d0.year, d0.month, d0.day, 20, 0, 0),
            "concorso": concorso,
            "numeri": scelti,
            "oro": oro,
            "doppio": doppio,
        }
        # prima prova con oro obbligatorio, poi senza (storico)
        if not valida(row, require_oro=True):
            if not valida(row, require_oro=False):
                continue
        k = chiave(row)
        if k in seen:
            continue
        seen.add(k)
        out.append(row)
    return out


def parse_csv_testo(testo: str) -> list[dict]:
    out, seen = [], set()
    for line in (testo or "").splitlines():
        s = line.strip()
        if not s or s.lower().startswith("data"):
            continue
        parts = [p.strip() for p in s.split(";")]
        if len(parts) < 5:
            parts = [p.strip() for p in s.split(",")]
        if len(parts) < 5:
            continue
        d0 = None
        for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                d0 = dt.datetime.strptime(parts[0].strip(), fmt)
                break
            except ValueError:
                continue
        if d0 is None:
            continue
        digits = re.sub(r"[^\d]", "", parts[1])
        concorso = int(digits) if digits else d0.timetuple().tm_yday
        numeri = [int(x) for x in RX_NUM.findall(parts[2])]
        if len(numeri) < 20:
            # a volte i 20 numeri sono in colonne separate
            numeri = [int(x) for x in RX_NUM.findall(s)]
        if len(numeri) < 20:
            continue
        try:
            oro = int(re.sub(r"[^\d]", "", parts[3]) or "0")
            doppio = int(re.sub(r"[^\d]", "", parts[4]) or "0")
        except ValueError:
            oro, doppio = 0, 0
        row = {
            "data": dt.datetime(d0.year, d0.month, d0.day, 20, 0, 0),
            "concorso": concorso,
            "numeri": numeri[:20],
            "oro": oro,
            "doppio": doppio,
        }
        if not valida(row, require_oro=False):
            continue
        k = chiave(row)
        if k in seen:
            continue
        seen.add(k)
        out.append(row)
    return out


def load_csv(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return parse_csv_testo(path.read_text(encoding="utf-8"))


def save_csv(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["data"], r["concorso"]))
    lines = ["Data;Concorso;Numeri;Oro;DoppioOro"]
    for r in rows:
        nums = " ".join(f"{int(n)}" for n in r["numeri"][:20])
        lines.append(
            f"{r['data']:%d/%m/%Y %H:%M};{r['concorso']};{nums};{int(r['oro'])};{int(r['doppio'])}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge(dest: list[dict], src: list[dict]) -> int:
    have = {chiave(r) for r in dest}
    added = 0
    for r in src:
        k = chiave(r)
        if k in have:
            continue
        dest.append(r)
        have.add(k)
        added += 1
    return added


def scarica_anno(year: int) -> list[dict]:
    url = URL_YEAR.format(year=year)
    try:
        html = fetch(url)
        log(f"  GET {url} bytes={len(html)}")
        if len(html) < 500:
            log(f"  ATTENZIONE pagina troppo corta: {html[:200]!r}")
        rows = parse_lottoced(html)
        log(f"  -> {len(rows)} serali")
        return rows
    except urllib.error.HTTPError as ex:
        log(f"  HTTP {ex.code} {url}")
        return []
    except Exception as ex:
        log(f"  ERR {url} -> {type(ex).__name__}: {ex}")
        return []


def main() -> int:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CSV_PATH.exists():
        CSV_PATH.write_text("Data;Concorso;Numeri;Oro;DoppioOro\n", encoding="utf-8")

    archivio = load_csv(CSV_PATH)
    prima = len(archivio)
    log(f"Archivio locale: {prima}")

    oggi = dt.date.today().year
    # prima popolazione: tutti gli anni 2009..oggi
    anni = list(range(oggi, 2008, -1)) if prima < 500 else [oggi, oggi - 1]

    for year in anni:
        log(f"Lottoced anno={year}...")
        n = merge(archivio, scarica_anno(year))
        log(f"  merge +{n}  tot={len(archivio)}")
        time.sleep(0.5)

    try:
        log("Lottologia CSV...")
        n = merge(archivio, parse_csv_testo(fetch(URL_LOTTOLOGIA)))
        log(f"  Lottologia +{n}  tot={len(archivio)}")
    except Exception as ex:
        log(f"  Lottologia skip -> {ex}")

    save_csv(CSV_PATH, archivio)
    ultima = max((r["data"] for r in archivio), default=None)
    report = "\n".join(
        [
            f"utc={dt.datetime.utcnow():%Y-%m-%d %H:%M:%S}",
            f"prima={prima}",
            f"dopo={len(archivio)}",
            f"aggiunte={len(archivio) - prima}",
            f"ultima={ultima:%d/%m/%Y}" if ultima else "ultima=-",
            "",
        ]
    )
    LOG_PATH.write_text(report, encoding="utf-8")
    log(report)

    if len(archivio) == 0:
        log("ERRORE: ancora 0 estrazioni. Controlla log sopra (pagina bloccata o formato diverso).")
        return 1  # fail visibile su Actions
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
