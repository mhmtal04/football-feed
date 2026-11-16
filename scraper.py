#!/usr/bin/env python3
"""Best-effort public-page fixture collector. No private endpoints or login."""
import asyncio, json, re, os
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path('public'); OUT.mkdir(exist_ok=True)
SITES = [
    ('NESINE', 'https://www.nesine.com/iddaa/futbol'),
    ('MACKOLIK', 'https://www.mackolik.com/canli-sonuclar'),
]
TIME_RE = re.compile(r'^(?:[01]?\d|2[0-3]):[0-5]\d$')
DATE_RE = re.compile(r'^(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?$')
TEAM_SEP = re.compile(r'\s+(?:-|–|—|vs\.?|v)\s+', re.I)

# League labels are mapped to keys understood by the existing app.
def league_key(label):
    s = label.casefold()
    rules = [
        ('UEFA_FRIENDLIES', r'friendly|hazırlık|dostluk'), ('UNL', r'nations league|uluslar ligi'),
        ('AFCON', r'africa cup of nations|afrika uluslar kupası'), ('UCL', r'champions league|şampiyonlar ligi'),
        ('UEL', r'europa league|avrupa ligi'), ('UECL', r'conference league|konferans ligi'),
        ('TR1', r'süper lig|super lig'), ('TR2', r'tff 1|1\. lig'), ('EN1', r'premier league'),
        ('EN2', r'championship'), ('ES1', r'la liga'), ('DE1', r'bundesliga'), ('IT1', r'serie a'),
        ('IT2', r'serie b'), ('FR1', r'ligue 1'), ('FR2', r'ligue 2'), ('NL1', r'eredivisie'),
        ('PT1', r'primeira liga|liga portugal'), ('BE1', r'pro league'), ('GR1', r'super league'),
    ]
    for key, pattern in rules:
        if re.search(pattern, s): return key
    return 'OTHER'

def clean(s):
    return re.sub(r'\s+', ' ', (s or '')).strip()

def parse_text(text, source):
    # Conservative line-based fallback for rendered public pages. Only accepts clear time + home-away rows.
    lines = [clean(x) for x in text.splitlines() if clean(x)]
    found, league, current_date = [], 'OTHER', datetime.now().date().isoformat()
    for i, line in enumerate(lines):
        if len(line) < 3: continue
        dm = DATE_RE.match(line)
        if dm:
            d, m, y = dm.groups(); y = int(y or datetime.now().year); y += 2000 if y < 100 else 0
            try: current_date = f'{y:04d}-{int(m):02d}-{int(d):02d}'
            except ValueError: pass
            continue
        # Most fixture pages place competition headings before a group of timed events.
        if not TIME_RE.match(line) and not TEAM_SEP.search(line) and len(line) < 65:
            k = league_key(line)
            if k != 'OTHER': league = k
        if TEAM_SEP.search(line):
            tm = TIME_RE.match(line)
            time = tm.group(0) if tm else None
            pair = line[tm.end():].strip() if tm else line
            parts = TEAM_SEP.split(pair, maxsplit=1)
            if len(parts) != 2: continue
            home, away = map(clean, parts)
            # Reject navigation labels, odds, scores, very short fragments.
            if len(home) < 2 or len(away) < 2 or len(home) > 70 or len(away) > 70: continue
            if any(x in (home + away).casefold() for x in ['hemen oyna', 'kupon', 'oran', 'canlı maç']): continue
            found.append({'league': league, 'date': current_date, 'time': time, 'homeRaw': home, 'awayRaw': away,
                          'ft': None, 'ht': None, 'stats': None, 'status': None, 'live': None,
                          'src': 'SCRAPER_' + source, 'sourcePage': source})
    return found

async def scrape_one(browser, name, url):
    page = await browser.new_page(locale='tr-TR', timezone_id='Europe/Istanbul')
    result = {'source': name, 'url': url, 'ok': False, 'httpStatus': None, 'matches': 0, 'error': None}
    matches = []
    try:
        response = await page.goto(url, wait_until='domcontentloaded', timeout=60000)
        result['httpStatus'] = response.status if response else None
        await page.wait_for_timeout(9000)
        # Try semantic table rows first, then visible body text.
        rows = await page.locator('tr').all_inner_texts()
        for row in rows:
            parsed = parse_text(row, name)
            matches.extend(parsed)
        if not matches:
            body = await page.locator('body').inner_text(timeout=15000)
            matches = parse_text(body, name)
        result['ok'] = bool(response and response.ok)
        if not result['ok']:
            result['error'] = f'HTTP {result["httpStatus"]}'
    except Exception as exc:
        result['error'] = str(exc)[:500]
    finally:
        await page.close()
    # Remove obvious duplicates from same rendered page.
    unique = {}
    for m in matches:
        key = (m['date'], (m['time'] or ''), m['homeRaw'].casefold(), m['awayRaw'].casefold())
        unique[key] = m
    result['matches'] = len(unique)
    return result, list(unique.values())

async def main():
    status = {'generatedAt': datetime.now(timezone.utc).isoformat(), 'collector': 'Playwright public-page best effort', 'sources': [], 'warning': 'Sayfa yapısı veya erişim koruması değişirse kaynak boş dönebilir. Boş veri, o tarihte maç olmadığı anlamına gelmez.'}
    all_matches = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for name, url in SITES:
            res, matches = await scrape_one(browser, name, url)
            status['sources'].append(res); all_matches.extend(matches)
            await asyncio.sleep(2)
        await browser.close()
    # Merge duplicates across sites; keep source list for traceability.
    merged = {}
    for m in all_matches:
        key = (m['date'], (m.get('time') or ''), m['homeRaw'].casefold(), m['awayRaw'].casefold())
        if key not in merged: merged[key] = m
        else:
            old = merged[key]
            old['src'] = 'SCRAPER_MULTI'
            old['sourcePage'] = old.get('sourcePage', '') + '+' + m.get('sourcePage', '')
            if old['league'] == 'OTHER' and m['league'] != 'OTHER': old['league'] = m['league']
    matches = [m for m in merged.values() if m['league'] != 'OTHER']
    payload = {'generatedAt': status['generatedAt'], 'matches': matches, 'sourceStatus': status['sources'], 'schemaVersion': 1}
    (OUT / 'external-matches.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'scrape-status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(status, ensure_ascii=False, indent=2))

if __name__ == '__main__': asyncio.run(main())
