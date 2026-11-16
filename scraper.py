#!/usr/bin/env python3

import asyncio
import json
import re
from datetime import datetime, timezone, date
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("public")
OUT.mkdir(exist_ok=True)

SITES = [
    ("NESINE", "https://www.nesine.com/iddaa/futbol"),
    ("MACKOLIK", "https://www.mackolik.com/canli-sonuclar"),
]

TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
DATE_RE = re.compile(
    r"^(?:(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})|"
    r"(\d{1,2})[-/.](\d{1,2})(?:[-/.](\d{2,4}))?)$"
)

TEAM_SEP = re.compile(r"\s+(?:-|–|—|vs\.?|v)\s+", re.I)

BAD_WORDS = [
    "copyright",
    "hemen oyna",
    "kupon",
    "oran",
    "canlı maç",
    "canli mac",
    "çeyrek final",
    "yarı final",
    "yarı final",
    "grup ",
    "grubu",
    "elemeleri",
    "son 16",
    "son 32",
    "round",
    "hafta",
    "ligleri",
    "uluslar ligi",
    "nesine",
]


def clean(value):
    return re.sub(r"\s+", " ", (value or "")).strip()


def parse_date(value):
    value = clean(value)
    match = DATE_RE.match(value)

    if not match:
        return None

    try:
        if match.group(1):
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
        else:
            day = int(match.group(4))
            month = int(match.group(5))
            year = int(match.group(6) or datetime.now().year)

            if year < 100:
                year += 2000

        return date(year, month, day).isoformat()

    except ValueError:
        return None


def league_key(label):
    s = clean(label).casefold()

    rules = [
        ("UNL", r"nations league|uluslar ligi"),
        ("UCL", r"champions league|şampiyonlar ligi"),
        ("UEL", r"europa league|avrupa ligi"),
        ("UECL", r"conference league|konferans ligi"),
        ("AFCON", r"africa cup of nations|afrika uluslar kupası"),
        ("UEFA_FRIENDLIES", r"international friendly|friendly|hazırlık maçı|dostluk maçı"),
        ("TR1", r"süper lig|super lig"),
        ("TR2", r"tff 1\. lig|1\. lig"),
        ("EN1", r"premier league"),
        ("EN2", r"championship"),
        ("ES1", r"la liga"),
        ("DE1", r"bundesliga"),
        ("IT1", r"serie a"),
        ("IT2", r"serie b"),
        ("FR1", r"ligue 1"),
        ("FR2", r"ligue 2"),
        ("NL1", r"eredivisie"),
        ("PT1", r"primeira liga|liga portugal"),
        ("BE1", r"pro league"),
        ("GR1", r"greek super league"),
    ]

    for key, pattern in rules:
        if re.search(pattern, s):
            return key

    return "OTHER"


def valid_team(name):
    name = clean(name)

    if len(name) < 2 or len(name) > 55:
        return False

    low = name.casefold()

    if any(word in low for word in BAD_WORDS):
        return False

    if re.fullmatch(r"[\d\s:./-]+", name):
        return False

    if len(re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]", name)) < 2:
        return False

    return True


def parse_text(text, source):
    lines = [clean(x) for x in text.splitlines() if clean(x)]

    found = []
    current_league = "OTHER"
    current_date = datetime.now().date().isoformat()
    pending_time = None

    for line in lines:

        # Tarih kontrolü
        parsed_date = parse_date(line)

        if parsed_date:
            current_date = parsed_date
            pending_time = None
            continue

        # Saat bilgisi
        time_match = TIME_RE.search(line)
        match_time = None
        pair_text = line

        if time_match:
            match_time = time_match.group(0)
            pair_text = (
                line[:time_match.start()] +
                line[time_match.end():]
            ).strip()

        elif TIME_RE.fullmatch(line):
            pending_time = line
            continue

        # Lig başlıkları
        if (
            not TEAM_SEP.search(pair_text)
            and not match_time
            and len(line) < 90
        ):
            detected = league_key(line)

            if detected != "OTHER":
                current_league = detected

            continue

        # Gerçek maç için saat zorunlu
        if not match_time:
            match_time = pending_time

        if not match_time:
            continue

        # Ev sahibi - deplasman ayrıştırma
        parts = TEAM_SEP.split(pair_text, maxsplit=1)

        if len(parts) != 2:
            pending_time = None
            continue

        home = clean(parts[0])
        away = clean(parts[1])

        if not valid_team(home) or not valid_team(away):
            pending_time = None
            continue

        if home.casefold() == away.casefold():
            pending_time = None
            continue

        if current_league == "OTHER":
            pending_time = None
            continue

        found.append({
            "league": current_league,
            "date": current_date,
            "time": match_time,
            "homeRaw": home,
            "awayRaw": away,
            "ft": None,
            "ht": None,
            "stats": None,
            "status": None,
            "live": None,
            "src": "SCRAPER_" + source,
            "sourcePage": source
        })

        pending_time = None

    return found


async def scrape_one(browser, name, url):

    page = await browser.new_page(
        locale="tr-TR",
        timezone_id="Europe/Istanbul"
    )

    result = {
        "source": name,
        "url": url,
        "ok": False,
        "pageLoaded": False,
        "httpStatus": None,
        "matches": 0,
        "error": None
    }

    matches = []

    try:
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        result["httpStatus"] = response.status if response else None

        await page.wait_for_timeout(9000)

        result["pageLoaded"] = bool(response and response.ok)

        # Görünen tablo satırlarını oku
        rows = await page.locator("tr").all_inner_texts()

        for row in rows:
            matches.extend(parse_text(row, name))

        # Tablo bulunamazsa sayfanın görünen metnini oku
        if not matches:
            body = await page.locator("body").inner_text(
                timeout=15000
            )

            matches = parse_text(body, name)

        # Tekrarlanan maçları temizle
        unique = {}

        for match in matches:
            key = (
                match["date"],
                match["time"],
                match["homeRaw"].casefold(),
                match["awayRaw"].casefold()
            )

            unique[key] = match

        matches = list(unique.values())

        result["matches"] = len(matches)

        if result["pageLoaded"] and len(matches) > 0:
            result["ok"] = True
        elif not result["pageLoaded"]:
            result["error"] = "Sayfa açılamadı veya HTTP hatası."
        else:
            result["error"] = (
                "Sayfa açıldı ancak doğrulanabilir maç bulunamadı."
            )

    except Exception as exc:
        result["error"] = str(exc)[:500]

    finally:
        await page.close()

    return result, matches


async def main():

    generated = datetime.now(timezone.utc).isoformat()

    status = {
        "generatedAt": generated,
        "collector": "Playwright public-page fixture collector",
        "sources": [],
        "warning": (
            "Yalnızca saat ve takım bilgisi doğrulanabilen "
            "maçlar kaydedilir. Boş veri maç olmadığı anlamına gelmez."
        )
    }

    all_matches = []

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=True)

        for name, url in SITES:

            result, matches = await scrape_one(
                browser,
                name,
                url
            )

            status["sources"].append(result)
            all_matches.extend(matches)

            await asyncio.sleep(2)

        await browser.close()

    # Kaynaklar arasındaki tekrarları temizle
    merged = {}

    for match in all_matches:

        key = (
            match["date"],
            match["time"],
            match["homeRaw"].casefold(),
            match["awayRaw"].casefold()
        )

        if key not in merged:
            merged[key] = match

        else:
            old = merged[key]
            old["src"] = "SCRAPER_MULTI"

            if match["sourcePage"] not in old["sourcePage"]:
                old["sourcePage"] += "+" + match["sourcePage"]

    matches = list(merged.values())

    # Son güvenlik kontrolü
    valid_matches = []

    for match in matches:

        if not parse_date(match["date"]):
            continue

        if not TIME_RE.fullmatch(match["time"]):
            continue

        if not valid_team(match["homeRaw"]):
            continue

        if not valid_team(match["awayRaw"]):
            continue

        if match["league"] == "OTHER":
            continue

        valid_matches.append(match)

    payload = {
        "generatedAt": generated,
        "matches": valid_matches,
        "sourceStatus": status["sources"],
        "schemaVersion": 1
    }

    (OUT / "external-matches.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    (OUT / "scrape-status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
