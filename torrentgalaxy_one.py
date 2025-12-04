# -*- coding: utf-8 -*-
#VERSION: 3.5
#
# qBittorrent Search Plugin for TorrentGalaxy
#
# License: GPL v3
# Description: Search plugin for TorrentGalaxy.one.
#              Features exact-match filtering, magnet link fetching, and tunable configuration.
#

import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Configuration ---
# Number of pages to scrape for specific categories
PAGES_MOVIES = 2
PAGES_TV = 2
PAGES_DEFAULT = 1

# Max number of parallel threads for fetching magnet links
# Lower this if you experience timeouts or bans.
MAX_WORKERS = 5

# Maximum number of torrents with 0 seeders to include in results.
# Set to -1 for unlimited.
MAX_NO_SEED_RESULTS = 5
# ---------------------

try:
    from novaprinter import prettyPrinter
    from helpers import retrieve_url
except ImportError:
    import urllib.request
    def prettyPrinter(dict):
        print(f"Name: {dict['name']} | Size: {dict['size']} | S/L: {dict['seeds']}/{dict['leech']}")
    def retrieve_url(url):
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0'}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode('utf-8')
        except: return ""

try:
    from bs4 import BeautifulSoup, NavigableString
except ImportError:
    pass

class torrentgalaxy_one(object):
    url = 'https://torrentgalaxy.one'
    name = 'TorrentGalaxy'

    supported_categories = {
        'all': 'all', 'movies': 'Movies', 'tv': 'TV', 'music': 'Music',
        'games': 'Games', 'software': 'Apps', 'anime': 'Anime', 'books': 'Books', 'other': 'Other'
    }

    def _clean_query_strict(self, query):
        """Sanitizes the query by removing special characters and excess whitespace."""
        cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', query)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    def _verify_match(self, user_query, result_title):
        """Strict matching: ensures exact word presence."""
        try:
            q_clean = self._clean_query_strict(user_query).lower()
            t_clean = self._clean_query_strict(result_title).lower()
            pattern = r'\b' + re.escape(q_clean) + r'\b'
            if re.search(pattern, t_clean):
                return True
            return False
        except:
            return user_query.lower() in result_title.lower()

    def _extract_size(self, row):
        """Iterates through spans to find the file size badge."""
        try:
            spans = row.find_all('span', class_='badge badge-secondary txlight')
            for span in spans:
                text = span.text.strip().replace('&nbsp;', ' ').replace('\xa0', ' ')
                if any(unit in text.upper() for unit in ['GB', 'MB', 'KB', 'TB']):
                    return text
            return '0 MB'
        except: return '0 MB'

    def _extract_seeds_leech(self, cell):
        """Parses the seeders/leechers from color-coded HTML elements."""
        try:
            text = str(cell)
            seeds_match = re.search(r'color="green"[^>]*>.*?<b>(\d+)</b>', text, re.IGNORECASE)
            leech_match = re.search(r'color="#ff0000"[^>]*>.*?<b>(\d+)</b>', text, re.IGNORECASE)
            seeds = seeds_match.group(1) if seeds_match else '0'
            leech = leech_match.group(1) if leech_match else '0'
            return seeds, leech
        except: return '0', '0'

    def _parse_date(self, date_str):
        """Converts relative date strings into Epoch timestamps."""
        try:
            clean_str = date_str.lower().replace('&nbsp;', ' ').strip()
            now = time.time()
            if 'today' in clean_str: return int(now)
            if 'yesterday' in clean_str: return int(now - 86400)

            seconds = 0
            matches = re.findall(r'(\d+)\W+(year|month|week|day|hour|min|sec)', clean_str)
            for num, unit in matches:
                n = int(num)
                if 'year' in unit: seconds += n * 31536000
                elif 'month' in unit: seconds += n * 2592000
                elif 'week' in unit: seconds += n * 604800
                elif 'day' in unit: seconds += n * 86400
                elif 'hour' in unit: seconds += n * 3600
                elif 'min' in unit: seconds += n * 60
                elif 'sec' in unit: seconds += n
            return int(now - seconds)
        except: return -1

    def _get_magnet(self, torrent_data):
        """Fetches the details page to retrieve the magnet link."""
        try:
            html = retrieve_url(torrent_data['desc_link'])
            if not html: return None
            soup = BeautifulSoup(html, 'html.parser')
            magnet = soup.find('a', href=re.compile(r'^magnet:\?'))
            if magnet:
                torrent_data['link'] = magnet.get('href')
                return torrent_data
        except: pass
        return None

    def search(self, what, cat='all'):
        query_unquoted = urllib.parse.unquote(what)
        clean_query = self._clean_query_strict(query_unquoted)
        if not clean_query: return

        target_cat_name = self.supported_categories.get(cat, '')

        # Determine page count based on config
        pages_to_scrape = PAGES_DEFAULT
        if cat == 'movies': pages_to_scrape = PAGES_MOVIES
        elif cat == 'tv': pages_to_scrape = PAGES_TV

        encoded_query = urllib.parse.quote(clean_query)
        base_url = f"{self.url}/get-posts/keywords:{encoded_query}"

        if not target_cat_name or target_cat_name == 'all':
            search_url_root = base_url
        else:
            search_url_root = f"{base_url}:category:{target_cat_name}"

        torrents_to_process = []
        zero_seed_count = 0

        for page in range(1, pages_to_scrape + 1):
            current_url = f"{search_url_root}/?page={page}" if page > 1 else f"{search_url_root}/"

            html = retrieve_url(current_url)
            if not html: continue

            soup = BeautifulSoup(html, 'html.parser')
            rows = soup.find_all('div', class_='tgxtablerow')

            for row in rows:
                try:
                    cells = row.find_all('div', class_='tgxtablecell')
                    if len(cells) < 5: continue

                    # 1. Title Extraction
                    title_cell = None
                    for cell in cells:
                        if cell.find('a', class_='txlight') and ('clickable-row' in cell.get('class', []) or 'click' in cell.get('class', [])):
                            title_cell = cell
                            break
                    if not title_cell: continue

                    title_anchor = title_cell.find('a', class_='txlight')
                    title = title_anchor.get('title', '').strip() or title_anchor.text.strip()

                    # 2. Strict Matching
                    if not self._verify_match(clean_query, title):
                        continue

                    # 3. Stats Extraction (Check seeds before adding)
                    seeds, leech = '0', '0'
                    for cell in cells:
                        if cell.find('span', title='Seeders/Leechers'):
                            seeds, leech = self._extract_seeds_leech(cell)
                            break

                    # Apply Zero Seeder Limit
                    if int(seeds) == 0:
                        if MAX_NO_SEED_RESULTS != -1 and zero_seed_count >= MAX_NO_SEED_RESULTS:
                            continue
                        zero_seed_count += 1

                    # 4. Link Extraction
                    href = title_cell.get('data-href') or title_anchor.get('href', '')
                    if not href: continue
                    desc_link = href if href.startswith('http') else self.url + (href if href.startswith('/') else '/' + href)

                    # 5. Size Extraction
                    size = self._extract_size(row)

                    # 6. Date Extraction
                    pub_date = -1
                    if cells:
                        last_cell = cells[-1]
                        if last_cell.contents:
                            first = last_cell.contents[0]
                            if isinstance(first, NavigableString):
                                pub_date = self._parse_date(str(first))

                    torrents_to_process.append({
                        'name': title,
                        'link': '',
                        'size': size,
                        'seeds': seeds,
                        'leech': leech,
                        'engine_url': self.url,
                        'desc_link': desc_link,
                        'pub_date': pub_date
                    })
                except: continue

        # Parallel Magnet Fetching
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(self._get_magnet, t) for t in torrents_to_process]
            for future in as_completed(futures):
                if res := future.result():
                    if res.get('link'):
                        prettyPrinter(res)
