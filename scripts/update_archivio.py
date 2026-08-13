#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivio 10eLotto da estrazionedellotto.it (2009->oggi).
Il sito NON usa <table>: parsing su testo/JSON + debug.
"""

from __future__ import annotations

import datetime as dt
import html as html_lib
import json
import pathlib
import re
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "archivio_serale.csv"
LOG_PATH = ROOT / "data" / "LAST_RUN.txt"
DEBUG_PATH = ROOT / "data" / "debug_sample.txt"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
URL_YEAR = (
    "https://www.estrazionedellotto.it/10elotto/risultati/archivio-10elotto-{year}"
)

RX_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
RX_INT = re.compile(r"\b(\d{1,2})\b")


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


def strip_html(page: str) -> str:
    page = re.sub(r"(?is)<script[^>]*>.*?</script>", "\n", page)
    page = re.sub(r"(?is)<style[^>]*>.*?</style>", "\n", page)
    page = re.sub(r"(?is)<br\s*/?>", "\n", page)
    page = re.sub(r"(?is)</p\s*>", "\n", page)
    page = re.sub(r"(?is)</div\s*>", "\n", page)
    page = re.sub(r"(?is)</tr\s*>", "\n", page)
    page = re.sub(r"(?is)</li\s*>", "\n", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    page = html_lib.unescape(page)
    page = page.replace("\xa0", " ")
    # normalizza spazi ma tiene i newline
    page = re.sub(r"[ \t\r\f\v]+", " ", page)
    page = re.sub(r"\n+", "\n", page)
    return page


def make_row(data: dt.datetime, concorso: int, nums: list[int], oro: int, doppio: int):
    if data.year < 2009:
        return None
    if concorso < 1:
        return None
    if len(nums) < 20:
        return None
    numeri = nums[:20]
    if any(n < 1 or n > 90 for n in numeri):
        return None
    if len(set(numeri)) != 20:
        return None
    if oro not in numeri:
        oro = 0
    if doppio not in numeri:
        doppio = 0
    return {
        "data": dt.datetime(data.year, data.month, data.day, 20, 0, 0),
        "concorso": concorso,
        "numeri": numeri,
        "oro": oro,
        "doppio": doppio,
    }


def parse_data_str(s: str) -> dt.datetime | None:
    m = RX_DATE.search(s)
    if not m:
        return None
    g, me, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return dt.datetime(a, me, g, 20, 0, 0)
    except ValueError:
        return None


def parse_token_line(line: str) -> dict | None:
    """
    Formato tipo quello che hai copiato:
    128 11/08/2026 2 4 5 ... (20 num) 38 79 [extra...]
    oppure data prima del concorso.
    """
    line = line.strip()
    if not line or line.lower().startswith("concorso"):
        return None

    # trova data
    dm = RX_DATE.search(line)
    if not dm:
        return None
    data = parse_data_str(dm.group(0))
    if data is None:
        return None

    # tutti i numeri interi nella riga
    # spezza intorno alla data
    left = line[: dm.start()].strip()
    right = line[dm.end() :].strip()

    left_nums = [int(x) for x in re.findall(r"\d+", left)]
    right_nums = [int(x) for x in re.findall(r"\d+", right)]

    # concorso: di solito subito prima della data
    concorso = left_nums[-1] if left_nums else 0
    if concorso < 1 or concorso > 200000:
        # a volte concorso dopo la data
        if right_nums and 1 <= right_nums[0] <= 200000 and right_nums[0] > 90:
            concorso = right_nums[0]
            right_nums = right_nums[1:]
        else:
            concorso = data.timetuple().tm_yday

    # right_nums dovrebbe iniziare con i 20 estratti + oro + doppio (+ extra)
    if len(right_nums) < 22:
        return None

    # i 20 numeri sono 1..90; prendi i primi 20 validi come set distinto
    candidati = [n for n in right_nums if 1 <= n <= 90]
    if len(candidati) < 22:
        return None

    numeri = candidati[:20]
    if len(set(numeri)) != 20:
        # prova a scorrere finestra
        ok = None
        for i in range(0, len(candidati) - 21):
            win = candidati[i : i + 20]
            if len(set(win)) == 20:
                ok = i
                break
        if ok is None:
            return None
        numeri = candidati[ok : ok + 20]
        oro = candidati[ok + 20]
        doppio = candidati[ok + 21]
    else:
        oro = candidati[20]
        doppio = candidati[21]

    return make_row(data, concorso, numeri, oro, doppio)


def parse_by_lines(text: str) -> list[dict]:
    out, seen = [], set()
    for line in text.splitlines():
        row = parse_token_line(line)
        if not row:
            continue
        k = (row["data"].date().isoformat(), row["concorso"])
        if k in seen:
            continue
        seen.add(k)
        out.append(row)
    return out


def parse_by_date_blocks(text: str) -> list[dict]:
    """Spezza il testo per ogni data e prova a leggere 22+ numeri dopo."""
    out, seen = [], set()
    matches = list(RX_DATE.finditer(text))
    for i, m in enumerate(matches):
        data = parse_data_str(m.group(0))
        if data is None:
            continue
        start = max(0, m.start() - 12)
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(text), m.end() + 400)
        blocco = text[start:end]
        # collassa a una riga logica
        blocco_1 = re.sub(r"\s+", " ", blocco).strip()
        row = parse_token_line(blocco_1)
        if not row:
            continue
        k = (row["data"].date().isoformat(), row["concorso"])
        if k in seen:
            continue
        seen.add(k)
        out.append(row)
    return out


def walk_json(obj, out: list[dict], depth: int = 0) -> None:
    if depth > 12:
        return
    if isinstance(obj, dict):
        # prova chiavi tipiche
        keys = {k.lower(): k for k in obj.keys() if isinstance(k, str)}
        def g(*names):
            for n in names:
                if n in keys:
                    return obj[keys[n]]
            return None

        data_raw = g("data", "date", "giorno", "day")
        conc = g("concorso", "nconcorso", "numero", "id", "draw")
        nums = g("numeri", "numbers", "estratti", "vals", "balls")
        oro = g("oro", "numero_oro", "gold", "jolly")
        doppio = g("doppiooro", "doppio_oro", "doublegold", "doppio")

        if data_raw is not None and nums is not None:
            # normalizza
            if isinstance(data_raw, str):
                data = parse_data_str(data_raw.replace("-", "/"))
                if data is None:
                    # yyyy-mm-dd
                    try:
                        y, m, d = [int(x) for x in re.split(r"[/-]", data_raw)[:3]]
                        if y > 31:
                            data = dt.datetime(y, m, d, 20, 0, 0)
                        else:
                            data = dt.datetime(d, m, y, 20, 0, 0) if y > 31 else None
                    except Exception:
                        data = None
            else:
                data = None

            nlist = nums
            if isinstance(nlist, str):
                nlist = [int(x) for x in re.findall(r"\d+", nlist)]
            if isinstance(nlist, list) and data is not None:
                try:
                    nlist = [int(x) for x in nlist]
                    c = int(conc) if conc is not None else data.timetuple().tm_yday
                    o = int(oro) if oro is not None else 0
                    dpp = int(doppio) if doppio is not None else 0
                    row = make_row(data, c, nlist, o, dpp)
                    if row:
                        out.append(row)
                except Exception:
                    pass

        for v in obj.values():
            walk_json(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            walk_json(v, out, depth + 1)


def parse_json_blobs(page: str) -> list[dict]:
    out: list[dict] = []
    # script type json
    for m in re.finditer(
        r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
        page,
        re.I | re.S,
    ):
        raw = m.group(1).strip()
        try:
            walk_json(json.loads(raw), out)
        except Exception:
            pass

    # assegnazioni JS comuni
    patterns = [
        r"var\s+\w+\s*=\s*(\[.*?\]);",
        r"const\s+\w+\s*=\s*(\[.*?\]);",
        r"window\.__\w+\s*=\s*(\{.*?\});",
        r"(\{\s*\"data\"\s*:\s*\[.*\]\s*\})",
    ]
    for pat in patterns:
        for m in re.finditer(pat, page, re.S):
            blob = m.group(1)
            if len(blob) < 50 or len(blob) > 2_000_000:
                continue
            try:
                walk_json(json.loads(blob), out)
            except Exception:
                continue

    # dedup
    seen, uniq = set(), []
    for r in out:
        k = (r["data"].date().isoformat(), r["concorso"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq


def scarica_anno(year: int, write_debug: bool = False) -> list[dict]:
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
    text = strip_html(page)
    n_dates = len(RX_DATE.findall(text))
    log(f"  date nel testo: {n_dates}")
    log(f"  campione testo: {text[:400]!r}")

    if write_debug:
        DEBUG_PATH.write_text(
            f"URL={url}\nBYTES={len(page)}\nDATES={n_dates}\n\n"
            f"--- TEXT SAMPLE ---\n{text[:5000]}\n\n"
            f"--- HTML SAMPLE ---\n{page[:5000]}\n",
            encoding="utf-8",
        )
        log(f"  debug scritto in {DEBUG_PATH}")

    # 1) JSON
    rows = parse_json_blobs(page)
    log(f"  via json: {len(rows)}")

    # 2) riga per riga
    if len(rows) < 10:
        r2 = parse_by_lines(text)
        log(f"  via lines: {len(r2)}")
        rows = r2 if len(r2) > len(rows) else rows

    # 3) blocchi per data
    if len(rows) < 10:
        r3 = parse_by_date_blocks(text)
        log(f"  via date-blocks: {len(r3)}")
        rows = r3 if len(r3) > len(rows) else rows

    # filtra anno richiesto (tolleranza)
    rows = [r for r in rows if r["data"].year == year or abs(r["data"].year - year) <= 1]
    # dedup finale
    seen, uniq = set(), []
    for r in rows:
        k = (r["data"].date().isoformat(), r["concorso"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)

    log(f"  totale anno {year}: {len(uniq)}")
    if uniq:
        r = uniq[0]
        log(
            f"  esempio: {r['data']:%d/%m/%Y} #{r['concorso']} "
            f"oro={r['oro']} doppio={r['doppio']} {r['numeri'][:5]}..."
        )
    return uniq


def load_csv(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
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
            oro, doppio = int(p[3]), int(p[4])
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
    if prima < 500:
        anni = list(range(2009, anno_oggi + 1))
    else:
        anni = [anno_oggi - 1, anno_oggi]

    for i, year in enumerate(anni):
        rows = scarica_anno(year, write_debug=(i == len(anni) - 1 or year == anno_oggi))
        added = merge(archivio, rows)
        log(f"  merge {year}: +{added}  tot={len(archivio)}")
        time.sleep(0.7)

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

    # non fallire se abbiamo debug: committa comunque sample
    if len(archivio) == 0:
        log("ANCORA 0: apri data/debug_sample.txt nel repo dopo il commit")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
