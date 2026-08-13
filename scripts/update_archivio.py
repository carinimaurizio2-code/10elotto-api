#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scarica archivio 10eLotto da estrazionedellotto.it (2009 -> oggi)
e salva data/archivio_serale.csv nel formato dell'app VB.NET.

Formato CSV:
Data;Concorso;Numeri;Oro;DoppioOro
"""

from __future__ import annotations

import datetime as dt
import html as html_lib
import pathlib
import re
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "archivio_serale.csv"
LOG_PATH = ROOT / "data" / "LAST_RUN.txt"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# Pattern URL scoperto da te
URL_YEAR = (
    "https://www.estrazionedellotto.it/10elotto/risultati/archivio-10elotto-{year}"
)

RX_NUM = re.compile(r"^\d{1,2}$")
RX_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
            "Referer": "https://www.estrazionedellotto.it/",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


class TableParser(HTMLParser):
    """Estrae tutte le tabelle come liste di righe (celle testo)."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cur_table: list[list[str]] = []
        self._cur_row: list[str] = []
        self._cur_cell: list[str] = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "table":
            self._in_table = True
            self._cur_table = []
        elif self._in_table and t == "tr":
            self._in_row = True
            self._cur_row = []
        elif self._in_row and t in ("td", "th"):
            self._in_cell = True
            self._cur_cell = []

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("td", "th") and self._in_cell:
            text = html_lib.unescape("".join(self._cur_cell))
            text = re.sub(r"\s+", " ", text).strip()
            self._cur_row.append(text)
            self._in_cell = False
        elif t == "tr" and self._in_row:
            if self._cur_row:
                self._cur_table.append(self._cur_row)
            self._in_row = False
        elif t == "table" and self._in_table:
            if self._cur_table:
                self.tables.append(self._cur_table)
            self._in_table = False

    def handle_data(self, data):
        if self._in_cell:
            self._cur_cell.append(data)


def parse_data(s: str) -> dt.datetime | None:
    m = RX_DATE.match(s.strip())
    if not m:
        return None
    g, me, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return dt.datetime(a, me, g, 20, 0, 0)
    except ValueError:
        return None


def row_to_estrazione(cells: list[str]) -> dict | None:
    """
    Atteso (come da tua copia):
    Concorso | Data | N1..N20 | Oro | DoppioOro | [Extra...]
    minimo 24 colonne utili.
    """
    if len(cells) < 24:
        return None

    # salta header
    c0 = cells[0].strip().lower()
    if c0 in ("concorso", "n.", "n", "#") or "concorso" in c0:
        return None
    if not re.fullmatch(r"\d{1,5}", cells[0].strip()):
        return None

    concorso = int(cells[0].strip())
    data = parse_data(cells[1])
    if data is None or data.year < 2009:
        return None

    try:
        numeri = [int(x.strip()) for x in cells[2:22]]
        oro = int(cells[22].strip())
        doppio = int(cells[23].strip())
    except ValueError:
        return None

    if len(numeri) != 20 or len(set(numeri)) != 20:
        return None
    if any(n < 1 or n > 90 for n in numeri):
        return None
    # Oro/Doppio devono stare nei 20; se no prova a salvare con 0
    if oro not in numeri:
        oro = 0
    if doppio not in numeri:
        doppio = 0
    # se manca oro su dati recenti, scarta (spesso riga rotta)
    if oro == 0 and doppio == 0 and data.year >= 2018:
        return None

    return {
        "data": data,
        "concorso": concorso,
        "numeri": numeri,
        "oro": oro,
        "doppio": doppio,
    }


def parse_html_tables(page_html: str) -> list[dict]:
    parser = TableParser()
    try:
        parser.feed(page_html)
    except Exception as ex:
        log(f"  parser html err: {ex}")
        return []

    out: list[dict] = []
    seen: set[tuple] = set()

    log(f"  tabelle trovate: {len(parser.tables)}")
    for ti, table in enumerate(parser.tables):
        ok = 0
        for cells in table:
            row = row_to_estrazione(cells)
            if not row:
                continue
            key = (row["data"].date().isoformat(), row["concorso"])
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
            ok += 1
        if ok:
            log(f"  tabella[{ti}]: +{ok} estrazioni")

    return out


def parse_plain_fallback(page_html: str) -> list[dict]:
    """
    Fallback: se le tabelle falliscono, prova a leggere testo tipo
    128  11/08/2026  2 4 5 ... 38 79
    """
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", page_html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)

    out: list[dict] = []
    seen: set[tuple] = set()

    # concorso data + almeno 22 numeri (20 + oro + doppio)
    rx = re.compile(
        r"\b(\d{1,4})\s+(\d{1,2}/\d{1,2}/\d{4})\s+((?:\d{1,2}\s+){21}\d{1,2})\b"
    )
    for m in rx.finditer(text):
        concorso = int(m.group(1))
        data = parse_data(m.group(2))
        if data is None:
            continue
        nums = [int(x) for x in m.group(3).split()]
        if len(nums) < 22:
            continue
        numeri = nums[:20]
        oro, doppio = nums[20], nums[21]
        if len(set(numeri)) != 20:
            continue
        if any(n < 1 or n > 90 for n in numeri):
            continue
        if oro not in numeri:
            oro = 0
        if doppio not in numeri:
            doppio = 0
        key = (data.date().isoformat(), concorso)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "data": data,
                "concorso": concorso,
                "numeri": numeri,
                "oro": oro,
                "doppio": doppio,
            }
        )
    return out


def scarica_anno(year: int) -> list[dict]:
    url = URL_YEAR.format(year=year)
    log(f"GET {url}")
    try:
        page = fetch(url)
    except urllib.error.HTTPError as ex:
        log(f"  HTTP {ex.code}")
        return []
    except Exception as ex:
        log(f"  ERR {type(ex).__name__}: {ex}")
        return []

    log(f"  bytes={len(page)}")
    if len(page) < 800:
        log(f"  pagina troppo corta: {page[:200]!r}")
        return []

    rows = parse_html_tables(page)
    if not rows:
        log("  tabelle vuote -> fallback testo")
        rows = parse_plain_fallback(page)

    log(f"  totale anno {year}: {len(rows)}")
    # campione
    if rows:
        r = rows[0]
        log(
            f"  esempio: {r['data']:%d/%m/%Y} #{r['concorso']} "
            f"oro={r['oro']} doppio={r['doppio']} nums={r['numeri'][:5]}..."
        )
    return rows


def load_csv(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.lower().startswith("data"):
            continue
        p = s.split(";")
        if len(p) < 5:
            continue
        try:
            dpart = p[0].split(" ")[0]
            g, me, a = [int(x) for x in dpart.split("/")]
            data = dt.datetime(a, me, g, 20, 0, 0)
            concorso = int(p[1])
            numeri = [int(x) for x in p[2].split()]
            oro = int(p[3])
            doppio = int(p[4])
        except Exception:
            continue
        if len(numeri) >= 20:
            out.append(
                {
                    "data": data,
                    "concorso": concorso,
                    "numeri": numeri[:20],
                    "oro": oro,
                    "doppio": doppio,
                }
            )
    return out


def save_csv(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["data"], r["concorso"]))
    lines = ["Data;Concorso;Numeri;Oro;DoppioOro"]
    for r in rows:
        nums = " ".join(f"{int(n):02d}" for n in r["numeri"][:20])
        lines.append(
            f"{r['data']:%d/%m/%Y %H:%M};{r['concorso']};{nums};{int(r['oro'])};{int(r['doppio'])}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge(dest: list[dict], src: list[dict]) -> int:
    have = {(r["data"].date().isoformat(), int(r["concorso"])) for r in dest}
    n = 0
    for r in src:
        k = (r["data"].date().isoformat(), int(r["concorso"]))
        if k in have:
            continue
        dest.append(r)
        have.add(k)
        n += 1
    return n


def main() -> int:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CSV_PATH.exists():
        CSV_PATH.write_text("Data;Concorso;Numeri;Oro;DoppioOro\n", encoding="utf-8")

    archivio = load_csv(CSV_PATH)
    prima = len(archivio)
    log(f"Archivio locale iniziale: {prima}")

    anno_oggi = dt.date.today().year
    # prima popolazione completa
    if prima < 500:
        anni = list(range(2009, anno_oggi + 1))
    else:
        anni = [anno_oggi - 1, anno_oggi]

    for year in anni:
        rows = scarica_anno(year)
        added = merge(archivio, rows)
        log(f"  merge {year}: +{added}  tot={len(archivio)}")
        time.sleep(0.8)  # non martellare il sito

    save_csv(CSV_PATH, archivio)
    ultima = max((r["data"] for r in archivio), default=None)
    report = "\n".join(
        [
            f"utc={dt.datetime.utcnow():%Y-%m-%d %H:%M:%S}",
            f"fonte=estrazionedellotto.it",
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
        log("ERRORE: 0 estrazioni. Il sito potrebbe usare JS o bloccare il bot.")
        return 1

    log("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
