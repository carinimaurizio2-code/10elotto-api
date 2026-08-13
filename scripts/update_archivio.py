#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Archivio 10eLotto SERALE 20:00 da Lottoced, dal 2009."""

from __future__ import annotations

import datetime as dt
import pathlib
import re
import time
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
RX_ROW = re.compile(
    r"(\d{2}/\d{2}/\d{4})\s+"
    r"(\d{1,2}:\d{2})\s+"
    r"(\d{1,4})\s+"
    r"((?:(?:[1-9]|[1-8]\d|90)\s+){19}(?:[1-9]|[1-8]\d|90))\s+"
    r"(\d{1,2})\s+"
    r"(\d{1,2})",
    re.I,
)


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,text/csv,*/*;q=0.9",
            "Accept-Language": "it-IT,it;q=0.9",
            "Referer": "https://www.lottoced.com/10elotto/estrazioni/",
        },
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        raw = resp.read()
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def valida(row: dict) -> bool:
    nums = row.get("numeri") or []
    if int(row.get("concorso") or 0) < 1 or len(nums) < 20:
        return False
    primi = [int(n) for n in nums[:20]]
    if any(n < 1 or n > 90 for n in primi):
        return False
    if len(set(primi)) != 20:
        return False
    return row["oro"] in primi and row["doppio"] in primi


def chiave(row: dict) -> tuple:
    return (row["data"].date().isoformat(), int(row["concorso"]), tuple(row["numeri"][:20]))


def parse_data(s: str):
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def strip_html(html: str) -> str:
    html = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", html)


def parse_lottoced(html: str) -> list[dict]:
    out, seen = [], set()
    for m in RX_ROW.finditer(strip_html(html)):
        data = parse_data(m.group(1) + " " + m.group(2))
        if data is None or data.hour != 20:
            continue
        data = dt.datetime(data.year, data.month, data.day, 20, 0, 0)
        row = {
            "data": data,
            "concorso": int(m.group(3)),
            "numeri": [int(x) for x in RX_NUM.findall(m.group(4))][:20],
            "oro": int(m.group(5)),
            "doppio": int(m.group(6)),
        }
        if not valida(row):
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
        data = parse_data(parts[0])
        if data is None:
            continue
        data = dt.datetime(data.year, data.month, data.day, 20, 0, 0)
        digits = re.sub(r"[^\d]", "", parts[1])
        concorso = int(digits) if digits else data.timetuple().tm_yday
        numeri = [int(x) for x in RX_NUM.findall(parts[2])]
        if len(numeri) < 20:
            continue
        try:
            oro = int(re.sub(r"[^\d]", "", parts[3]) or "0")
            doppio = int(re.sub(r"[^\d]", "", parts[4]) or "0")
        except ValueError:
            continue
        row = {
            "data": data,
            "concorso": concorso,
            "numeri": numeri[:20],
            "oro": oro,
            "doppio": doppio,
        }
        if not valida(row):
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
        nums = " ".join(str(n) for n in r["numeri"][:20])
        lines.append(
            f"{r['data']:%d/%m/%Y %H:%M};{r['concorso']};{nums};{r['oro']};{r['doppio']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge(dest: list[dict], src: list[dict]) -> int:
    have = {chiave(r) for r in dest}
    added = 0
    for r in src:
        if not valida(r):
            continue
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
        rows = parse_lottoced(fetch(url))
        log(f"  {url} -> {len(rows)} serali")
        return rows
    except Exception as ex:
        log(f"  skip {url} -> {ex}")
        return []


def main() -> int:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CSV_PATH.exists():
        CSV_PATH.write_text("Data;Concorso;Numeri;Oro;DoppioOro\n", encoding="utf-8")

    archivio = load_csv(CSV_PATH)
    prima = len(archivio)
    log(f"Archivio locale: {prima}")

    oggi = dt.date.today().year
    anni = list(range(oggi, 2008, -1)) if prima < 1000 else [oggi, oggi - 1]
    for year in anni:
        log(f"Lottoced {year}...")
        n = merge(archivio, scarica_anno(year))
        log(f"  anno {year}: +{n}  tot={len(archivio)}")
        time.sleep(0.4)

    try:
        log("Integrazione Lottologia...")
        merge(archivio, parse_csv_testo(fetch(URL_LOTTOLOGIA)))
    except Exception as ex:
        log(f"  Lottologia skip -> {ex}")

    save_csv(CSV_PATH, archivio)
    ultima = max((r["data"] for r in archivio), default=None)
    report = "\n".join([
        f"utc={dt.datetime.utcnow():%Y-%m-%d %H:%M:%S}",
        f"prima={prima}",
        f"dopo={len(archivio)}",
        f"aggiunte={len(archivio) - prima}",
        f"ultima={ultima:%d/%m/%Y}" if ultima else "ultima=-",
        "",
    ])
    LOG_PATH.write_text(report, encoding="utf-8")
    log(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
