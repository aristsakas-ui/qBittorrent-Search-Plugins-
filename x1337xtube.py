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

# Filtering Configuration
MAX_DEAD_RESULTS = 5         # Maximum number of "Dead" torrents to show
MIN_LEECHERS_THRESHOLD = 3   # If 0 Seeds, result must have at least this many leechers to be considered "Active"

# --- Constants & Regex (Global) ---
RE_MAGNET = re.compile(r'^magnet:')
RE_TORRENT_LINK = re.compile(r'/torrent/')
RE_ICON = re.compile(r'flaticon-')
RE_ORDINAL = re.compile(r'(\d+)(st|nd|rd|th)')
RE_NON_ALPHANUM = re.compile(r'[^a-z0-9]')

CAT_KEYWORDS = {
    'movies': ['movies'],
    'tv': ['tv'],
    'music': ['music'],
    'games': ['games'],
    'software': ['app', 'linux', 'windows', 'android', 'apple'],
    'anime': ['anime'],
    'books': ['documentary', 'other']
}

TIME_MULTIPLIERS = {
    'min': 60,
    'hour': 3600,
    'day': 86400,
    'week': 604800,
    'month': 2592000,
    'year': 31536000
}

class x1337xtube(object):
    url = LEETX_DOMAIN
    name = "1337x Tube (Intelligent 2.3)"
    supported_categories = {'all': 'All', 'movies': 'Movies', 'tv': 'TV', 'music': 'Music', 'games': 'Games', 'anime': 'Anime', 'software': 'Software', 'books': 'Books'}

    def __init__(self):
        self.search_term = ""

    def _clean_string(self, text):
        """Standardizes strings: unquote, lowercase, remove symbols, fix spaces."""
        text = unquote_plus(text).lower()
        text = RE_NON_ALPHANUM.sub(' ', text)
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
                    for unit, mult in TIME_MULTIPLIERS.items():
                        if unit in date_str:
                            return int(time.time() - (num * mult))

            # Absolute Dates
            clean_str = RE_ORDINAL.sub(r'\1', date_str)
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
            if desc_link.startswith('/'):
                desc_link = self.url + desc_link

            html = retrieve_url(desc_link)
            soup = BeautifulSoup(html, 'html.parser')

            magnet = soup.find('a', href=RE_MAGNET)
            if not magnet:
                magnet = soup.find('a', id='openPopup')

            if magnet and magnet.get('href'):
                return magnet['href']
        except Exception:
            pass
        return None

    def _fetch_and_parse_page(self, page_num, query):
        # Using .format() instead of f-string for compatibility
        url = "{}/search/?q={}&page={}".format(self.url, quote_plus(query), page_num)

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
                name_link = row.find_all('a', href=RE_TORRENT_LINK)
                if not name_link: continue
                name_link = name_link[-1]

                # 2. Icon Suffix (Category Detection)
                icon_suffix = ''
                icon_tag = row.find('i', class_=RE_ICON)
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
                leech_str = cells[2].get_text(strip=True) or '0'

                try: seeds_int = int(seeds_str.replace(',', ''))
                except: seeds_int = 0

                try: leech_int = int(leech_str.replace(',', ''))
                except: leech_int = 0

                date_txt = cells[3].get_text(strip=True) if len(cells) >= 4 else ''
                size_txt = cells[4].get_text(strip=True) if len(cells) >= 5 else 'Unknown'

                results.append({
                    'name': name_link.get_text(strip=True),
                    'link': name_link['href'],
                    'desc_link': name_link['href'],
                    'engine_url': self.url,
                    'seeds': seeds_str,
                    'seeds_int': seeds_int,
                    'leech': leech_str,
                    'leech_int': leech_int,
                    'size': size_txt,
                    'pub_date': self._parse_date(date_txt),
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
            keywords = CAT_KEYWORDS.get(cat_lower)
            if keywords:
                filtered = [r for r in candidates if r['icon_suffix'] in keywords]
                if filtered: candidates = filtered

        # 5. Filter (Sort, Min Leechers, & Dead Limit)
        candidates.sort(key=lambda t: t['seeds_int'], reverse=True)

        active_results = []
        dead_results = []

        for t in candidates:
            # Active if Seeds > 0 OR Leechers >= Threshold
            if t['seeds_int'] > 0:
                active_results.append(t)
            elif t['leech_int'] >= MIN_LEECHERS_THRESHOLD:
                active_results.append(t)
            else:
                dead_results.append(t)

        final_list = active_results + dead_results[:MAX_DEAD_RESULTS]

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
        if info.startswith('magnet:'):
            print(download_file(info))
        else:
            print('')
