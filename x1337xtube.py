# VERSION: 2.3
# This script is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License

"""
1337x Torrent Search Engine Plugin for 1337x.tube
"""

from __future__ import print_function
import re
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from urllib.parse import quote_plus, unquote_plus
except ImportError:
    from urllib import quote_plus, unquote_plus

from helpers import retrieve_url, download_file
from novaprinter import prettyPrinter

try:
    from bs4 import BeautifulSoup
except ImportError:
    pass

# --- Configuration ---
MAX_PAGES_TO_FETCH = 2
MAX_MAGNET_WORKERS = 10
LEETX_DOMAIN = "https://1337x.tube"
MAX_ZERO_SEED_RESULTS = 5

class x1337xtube:
    url = LEETX_DOMAIN
    name = "1337x Tube (Intelligent 2.1)"

    supported_categories = {'all': 'All', 'movies': 'Movies', 'tv': 'TV', 'music': 'Music', 'games': 'Games', 'anime': 'Anime', 'software': 'Software', 'books': 'Books'}

    cat_keywords = {
        'movies': ['movies'],
        'tv': ['tv'],
        'music': ['music'],
        'games': ['games'],
        'software': ['app', 'linux', 'windows', 'android', 'apple'],
        'anime': ['anime'],
        'books': ['documentary', 'other']
    }

    time_multipliers = {'min': 60, 'hour': 3600, 'day': 86400, 'week': 604800, 'month': 2592000, 'year': 31536000}

    # Compiled Regex
    RE_MAGNET = re.compile(r'^magnet:')
    RE_TORRENT_LINK = re.compile(r'/torrent/')
    RE_ICON = re.compile(r'flaticon-')
    RE_ORDINAL = re.compile(r'(\d+)(st|nd|rd|th)')
    RE_NON_ALPHANUM = re.compile(r'[^a-z0-9]') # Only lowercase needed due to _clean_string logic

    def __init__(self):
        self.search_term = ""

    def _clean_string(self, text):
        """Standardizes strings: unquote, lowercase, remove symbols, fix spaces."""
        text = unquote_plus(text).lower()
        text = self.RE_NON_ALPHANUM.sub(' ', text)
        return ' '.join(text.split())

    def _parse_date(self, date_str):
        if not date_str: return -1
        date_str = date_str.strip()

        try:
            # Relative Dates
            if 'ago' in date_str.lower():
                num_match = re.search(r'(\d+)', date_str)
                if num_match:
                    num = int(num_match.group(1))
                    for unit, mult in self.time_multipliers.items():
                        if unit in date_str:
                            return int(time.time() - (num * mult))

            # Absolute Dates
            clean_str = self.RE_ORDINAL.sub(r'\1', date_str)
            for fmt in ("%b. %d '%y", "%b %d '%y"):
                try:
                    dt = datetime.strptime(clean_str, fmt)
                    return int(time.mktime(dt.timetuple()))
                except ValueError:
                    continue
        except Exception:
            pass
        return -1

    def _fetch_magnet_link(self, desc_link):
        try:
            if desc_link.startswith('/'): desc_link = self.url + desc_link
            soup = BeautifulSoup(retrieve_url(desc_link), 'html.parser')

            magnet = soup.find('a', href=self.RE_MAGNET) or soup.find('a', id='openPopup')
            if magnet and magnet.get('href'):
                return magnet['href']
        except Exception:
            pass
        return None

    def _fetch_and_parse_page(self, page_num, query):
        url = f"{self.url}/search/?q={quote_plus(query)}&page={page_num}"
        try:
            html = retrieve_url(url)
            soup = BeautifulSoup(html, 'html.parser')
            table = soup.find('table', class_='table-list')
            if not table: return []
        except Exception:
            return []

        results = []
        rows = table.find_all('tr')[1:] if table.find('tr') else []

        for row in rows:
            try:
                # 1. Name & Link
                name_link = row.find_all('a', href=self.RE_TORRENT_LINK)
                if not name_link: continue
                name_link = name_link[-1]

                # 2. Icon Suffix (Category Detection)
                icon_suffix = ''
                icon_tag = row.find('i', class_=self.RE_ICON)
                if icon_tag:
                    for cls in icon_tag.get('class', []):
                        if cls.startswith('flaticon-'):
                            icon_suffix = cls.replace('flaticon-', '')
                            break

                # 3. Cells
                cells = row.find_all('td')
                if len(cells) < 3: continue

                # 4. Immediate Extraction & Conversion
                seeds_str = cells[1].get_text(strip=True) or '0'
                try: seeds_int = int(seeds_str.replace(',', ''))
                except: seeds_int = 0

                results.append({
                    'name': name_link.get_text(strip=True),
                    'link': name_link['href'], # Placeholder
                    'desc_link': name_link['href'],
                    'engine_url': self.url,
                    'seeds': seeds_str,
                    'seeds_int': seeds_int,
                    'leech': cells[2].get_text(strip=True) or '0',
                    'size': cells[4].get_text(strip=True) if len(cells) >= 5 else 'Unknown',
                    'pub_date': self._parse_date(cells[3].get_text(strip=True)) if len(cells) >= 4 else -1,
                    'icon_suffix': icon_suffix
                })
            except Exception:
                continue
        return results

    def search(self, what, cat='all'):
        if 'BeautifulSoup' not in globals(): return

        # 1. Sanitize
        self.search_term = self._clean_string(what)
        query_words = set(self.search_term.split())

        # 2. Fetch
        all_raw = []
        with ThreadPoolExecutor(max_workers=MAX_PAGES_TO_FETCH) as executor:
            futures = [executor.submit(self._fetch_and_parse_page, i, self.search_term)
                      for i in range(1, MAX_PAGES_TO_FETCH + 1)]
            for future in as_completed(futures):
                all_raw.extend(future.result())

        # 3. Filter (Dedup & Exact Match)
        seen_names = set()
        candidates = []

        for res in all_raw:
            if res['name'] in seen_names: continue

            # Check if all query words exist in title
            title_clean = self._clean_string(res['name'])
            if not query_words.issubset(title_clean.split()):
                continue

            seen_names.add(res['name'])
            candidates.append(res)

        if not candidates: return

        # 4. Filter (Soft Category)
        cat_lower = cat.lower()
        if cat_lower != 'all':
            keywords = self.cat_keywords.get(cat_lower)
            if keywords:
                filtered = [r for r in candidates if r['icon_suffix'] in keywords]
                if filtered: candidates = filtered

        # 5. Filter (Sort & Zero Seed Limit)
        candidates.sort(key=lambda t: t['seeds_int'], reverse=True)
        seeded = [t for t in candidates if t['seeds_int'] > 0]
        unseeded = [t for t in candidates if t['seeds_int'] == 0]
        final_list = seeded + unseeded[:MAX_ZERO_SEED_RESULTS]

        if not final_list: return

        # 6. Fetch Magnets
        with ThreadPoolExecutor(max_workers=MAX_MAGNET_WORKERS) as executor:
            future_to_torrent = {
                executor.submit(self._fetch_magnet_link, t['desc_link']): t
                for t in final_list
            }
            for future in as_completed(future_to_torrent):
                t = future_to_torrent[future]
                try:
                    magnet = future.result()
                    if magnet: t['link'] = magnet
                except: pass

        # 7. Output
        for res in final_list:
            prettyPrinter({
                'link': res['link'],
                'name': res['name'],
                'size': res['size'],
                'seeds': res['seeds'],
                'leech': res['leech'],
                'pub_date': res['pub_date'],
                'engine_url': self.url,
                'desc_link': res['desc_link']
            })

    def download_torrent(self, info):
        if info.startswith('magnet:'): print(download_file(info))
        else: print('')
