#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivio 10eLotto SERALE da estrazionedellotto.it
URL: /10elotto/risultati/archivio-10elotto-{year}

- Prima popolazione / anni mancanti: scarica dal 2009 all'anno corrente
- Se archivio già ricco: aggiorna anno-1 e anno corrente + eventuali buchi (es. 2009-2013)
- Oro/DoppioOro opzionali (0 ammessi, tipico pre-Doppio Oro)
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

RX_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
ANNO_MIN = 2009


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
    page = re.sub(r"(?is)</(p|div|tr|li|h\d)\s*>", "\n", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    page = html_lib.unescape(page).replace("\xa0", " ")
    page = re.sub(r"[ \t\r\f\v]+", " ", page)
    page = re.sub(r"\n+", "\n", page)
    return page


def parse_data_str(s: str) -> dt.datetime | None:
    m = RX_DATE.search(s.strip())
    if not m:
        return None
    g, me, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return dt.datetime(a, me, g, 20, 0, 0)
    except ValueError:
        return None


def make_row(
    data: dt.datetime,
    concorso: int,
    nums: list[int],
    oro: int,
    doppio: int,
) -> dict | None:
    if data.year < ANNO_MIN:
        return None
    if concorso < 1:
        concorso = data.timetuple().tm_yday
    if len(nums) < 20:
        return None
    numeri = [int(n) for n in nums[:20]]
    if any(n < 1 or n > 90 for n in numeri):
        return None
    if len(set(numeri)) != 20:
        return None
    oro = int(oro or 0)
    doppio = int(doppio or 0)
    if oro and oro not in numeri:
        oro = 0
    if doppio and doppio not in numeri:
        doppio = 0
    return {
        "data": dt.datetime(data.year, data.month, data.day, 20, 0, 0),
        "concorso": int(concorso),
        "numeri": numeri,
        "oro": oro,
        "doppio": doppio,
    }


def extract_window(candidati: list[int]) -> tuple[list[int], int, int] | None:
    """Trova 20 numeri distinti + oro/doppio opzionali dopo."""
    if len(candidati) < 20:
        return None
    for i in range(0, len(candidati) - 19):
        win = candidati[i : i + 20]
        if len(set(win)) != 20:
            continue
        rest = candidati[i + 20 :]
        oro = rest[0] if rest and rest[0] in win else 0
        doppio = 0
        if len(rest) >= 2 and rest[1] in win:
            doppio = rest[1]
        elif len(rest) >= 2 and oro == 0 and rest[1] in win:
            oro = rest[1]
        return win, oro, doppio
    return None


def parse_token_line(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    low = line.lower()
    if "concorso" in low and "data" in low:
        return None
    if low.startswith("n.1") or low.startswith("archivio"):
        return None

    dm = RX_DATE.search(line)
    if not dm:
        return None
    data = parse_data_str(dm.group(0))
    if data is None:
        return None

    left = line[: dm.start()].strip()
    right = line[dm.end() :].strip()
    left_nums = [int(x) for x in re.findall(r"\d+", left)]
    right_nums = [int(x) for x in re.findall(r"\d+", right)]

    concorso = left_nums[-1] if left_nums else 0
    if concorso < 1 or concorso > 500000:
        if right_nums and right_nums[0] > 90:
            concorso = right_nums[0]
            right_nums = right_nums[1:]
        else:
            concorso = data.timetuple().tm_yday

    candidati = [n for n in right_nums if 1 <= n <= 90]
    got = extract_window(candidati)
    if not got:
        # a volte tutta la riga mescolata
        alln = [int(x) for x in re.findall(r"\d+", line) if 1 <= int(x) <= 90]
        got = extract_window(alln)
    if not got:
        return None
    numeri, oro, doppio = got
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
    out, seen = [], set()
    matches = list(RX_DATE.finditer(text))
    for i, m in enumerate(matches):
        start = max(0, m.start() - 16)
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(text), m.end() + 500)
        blocco = re.sub(r"\s+", " ", text[start:end]).strip()
        row = parse_token_line(blocco)
        if not row:
            continue
        k = (row["data"].date().isoformat(), row["concorso"])
        if k in seen:
            continue
        seen.add(k)
        out.append(row)
    return out


def walk_json(obj, out: list[dict], depth: int = 0) -> None:
    if depth > 14:
        return
    if isinstance(obj, dict):
        keys = {str(k).lower(): k for k in obj.keys()}

        def g(*names):
            for n in names:
                if n in keys:
                    return obj[keys[n]]
            return None

        data_raw = g("data", "date", "giorno", "day", "data_estrazione")
        conc = g("concorso", "nconcorso", "numero", "id", "draw", "n")
        nums = g("numeri", "numbers", "estratti", "vals", "balls", "estrazione")
        oro = g("oro", "numero_oro", "gold", "jolly", "numerooro")
        doppio = g("doppiooro", "doppio_oro", "doublegold", "doppio", "numerodoppiooro")

        if data_raw is not None and nums is not None:
            data = None
            if isinstance(data_raw, str):
                data = parse_data_str(data_raw.replace("-", "/"))
                if data is None:
                    parts = re.split(r"[/-]", data_raw.strip())
                    try:
                        if len(parts) >= 3:
                            a, b, c = int(parts[0]), int(parts[1]), int(parts[2])
                            if a > 31:
                                data = dt.datetime(a, b, c, 20, 0, 0)
                            else:
                                data = dt.datetime(c, b, a, 20, 0, 0)
                    except Exception:
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
    for m in re.finditer(
        r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
        page,
        re.I | re.S,
    ):
        try:
            walk_json(json.loads(m.group(1).strip()), out)
        except Exception:
            pass

    for pat in (
        r"var\s+\w+\s*=\s*(\[.*?\]);",
        r"const\s+\w+\s*=\s*(\[.*?\]);",
        r"(\{\s*\"data\"\s*:\s*\[.*\]\s*\})",
    ):
        for m in re.finditer(pat, page, re.S):
            blob = m.group(1)
            if 80 < len(blob) < 2_000_000:
                try:
                    walk_json(json.loads(blob), out)
                except Exception:
                    pass

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
    log(f"  campione: {text[:350]!r}")

    if write_debug:
        DEBUG_PATH.write_text(
            f"URL={url}\nBYTES={len(page)}\nDATES={n_dates}\n\n"
            f"--- TEXT ---\n{text[:8000]}\n\n--- HTML ---\n{page[:4000]}\n",
            encoding="utf-8",
        )
        log(f"  debug -> {DEBUG_PATH.name}")

    rows = parse_json_blobs(page)
    log(f"  json: {len(rows)}")
    if len(rows) < 5:
        r2 = parse_by_lines(text)
        log(f"  lines: {len(r2)}")
        if len(r2) > len(rows):
            rows = r2
    if len(rows) < 5:
        r3 = parse_by_date_blocks(text)
        log(f"  blocks: {len(r3)}")
        if len(r3) > len(rows):
            rows = r3

    # tieni soprattutto l'anno richiesto
    filtered = [r for r in rows if r["data"].year == year]
    if not filtered and rows:
        # tolleranza se date parseate male
        filtered = [r for r in rows if abs(r["data"].year - year) <= 1]

    seen, uniq = set(), []
    for r in filtered:
        k = (r["data"].date().isoformat(), r["concorso"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)

    log(f"  totale anno {year}: {len(uniq)}")
    if uniq:
        r = uniq[0]
        log(
            f"  es: {r['data']:%d/%m/%Y} #{r['concorso']} "
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
        row = make_row(data, concorso, numeri, oro, doppio)
        if row:
            out.append(row)
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


def anni_da_scaricare(archivio: list[dict]) -> list[int]:
    """Sempre ripara i buchi 2009..oggi; se pieno aggiorna solo recenti."""
    anno_oggi = dt.date.today().year
    presenti = {r["data"].year for r in archivio}
    mancanti = [y for y in range(ANNO_MIN, anno_oggi + 1) if y not in presenti]

    # PRIORITÀ: buchi storici (2009-2013 ecc.)
    if mancanti:
        log(f"Anni mancanti da scaricare: {mancanti}")
        return mancanti

    # archivio completo -> solo aggiornamento
    recenti = [anno_oggi - 1, anno_oggi]
    log(f"Nessun buco. Aggiornamento: {recenti}")
    return recenti


def main() -> int:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CSV_PATH.exists():
        CSV_PATH.write_text("Data;Concorso;Numeri;Oro;DoppioOro\n", encoding="utf-8")

    archivio = load_csv(CSV_PATH)
    prima = len(archivio)
    presenti = sorted({r["data"].year for r in archivio})
    log(f"Archivio iniziale: {prima} righe | anni={presenti}")

    anni = anni_da_scaricare(archivio)

    for year in anni:
        # debug soprattutto sugli anni vecchi
        rows = scarica_anno(year, write_debug=(year <= 2013 or year == dt.date.today().year))
        added = merge(archivio, rows)
        log(f"merge {year}: scaricate={len(rows)} +{added} tot={len(archivio)}")
        time.sleep(0.8)

    save_csv(CSV_PATH, archivio)
    finali = sorted({r["data"].year for r in archivio})
    ultima = max((r["data"] for r in archivio), default=None)
    ancora = [y for y in range(ANNO_MIN, 2014) if y not in finali]

    report = "\n".join(
        [
            f"utc={dt.datetime.utcnow():%Y-%m-%d %H:%M:%S}",
            "fonte=estrazionedellotto.it",
            f"prima={prima}",
            f"dopo={len(archivio)}",
            f"aggiunte={len(archivio) - prima}",
            f"anni={finali}",
            f"mancanti_2009_2013={ancora}",
            f"ultima={ultima:%d/%m/%Y}" if ultima else "ultima=-",
            "",
        ]
    )
    LOG_PATH.write_text(report, encoding="utf-8")
    log(report)

    if len(archivio) == 0:
        log("ERRORE: 0 estrazioni in archivio")
        return 1

    if ancora:
        log(f"AVVISO: ancora senza {ancora} (sito vuoto o HTML diverso per quegli anni)")
        # non fallire: tieni l'archivio parziale già buono
    log("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
