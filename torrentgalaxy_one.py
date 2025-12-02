# -*- coding: utf-8 -*-
#VERSION: 3.2
#AUTHORS: Me
#
# qBittorrent Search Plugin for TorrentGalaxy
#
# License: GPL v3
# Description: Search plugin for TorrentGalaxy.one.
#              Features exact-match filtering (removes wildcard results like 'Ramona' for 'Rambo'),
#              multi-page scraping for Movies/TV (tunable), and robust date/size extraction.
#              Cleans search queries to ensure compatibility with the search engine.
#

import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Configuration ---
# Number of pages to scrape for specific categories
MOVIES_PAGES = 2
TV_PAGES = 2
DEFAULT_PAGES = 1
# ---------------------

# Environment detection for qBittorrent
try:
    from novaprinter import prettyPrinter
    from helpers import retrieve_url
    QBITTORRENT_ENV = True
except ImportError:
    QBITTORRENT_ENV = False
    import urllib.request
    def prettyPrinter(dict):
        print(f"RESULT: {dict.get('name')} | Size: {dict.get('size')} | Date: {dict.get('pub_date')}")
    def retrieve_url(url):
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            parsed = urllib.parse.urlsplit(url)
            parsed = parsed._replace(path=urllib.parse.quote(parsed.path))
            req = urllib.request.Request(parsed.geturl(), headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode('utf-8')
        except: return ""

try:
    from bs4 import BeautifulSoup, NavigableString
    BEAUTIFULSOUP_AVAILABLE = True
except ImportError:
    BEAUTIFULSOUP_AVAILABLE = False
    if not QBITTORRENT_ENV:
        print("ERROR: Install beautifulsoup4: pip install beautifulsoup4")

class torrentgalaxy_one(object):
    """
    Main plugin class for TorrentGalaxy search.
    """
    url = 'https://torrentgalaxy.one'
    name = 'TorrentGalaxy'

    supported_categories = {
        'all': 'all', 'movies': 'Movies', 'tv': 'TV', 'music': 'Music',
        'games': 'Games', 'software': 'Apps', 'anime': 'Anime', 'books': 'Books', 'other': 'Other'
    }

    def _clean_query_strict(self, query):
        """
        Sanitizes the query by removing special characters and excess whitespace.
        """
        cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', query)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    def _verify_match(self, user_query, result_title):
        """
        Ensures the result contains the exact word/phrase requested.
        """
        try:
            q_clean = self._clean_query_strict(user_query).lower()
            t_clean = self._clean_query_strict(result_title).lower()
            # Regex boundary check for exact word matching
            pattern = r'\b' + re.escape(q_clean) + r'\b'
            if re.search(pattern, t_clean):
                return True
            return False
        except:
            return user_query.lower() in result_title.lower()

    def _extract_size_from_row(self, row):
        """
        Iterates through spans to find the file size badge.
        """
        try:
            size_spans = row.find_all('span', class_='badge badge-secondary txlight', style='border-radius:4px;')
            for span in size_spans:
                size_text = span.text.strip().replace('&nbsp;', ' ').replace('\xa0', ' ')
                if any(unit in size_text.upper() for unit in ['GB', 'MB', 'KB', 'TB']):
                    return size_text
            return '0 MB'
        except:
            return '0 MB'

    def _extract_seeds_leech(self, cell):
        """
        Parses the seeders/leechers from color-coded HTML elements.
        """
        try:
            text = str(cell)
            seeds_match = re.search(r'color="green"[^>]*>.*?<b>(\d+)</b>', text, re.IGNORECASE)
            leech_match = re.search(r'color="#ff0000"[^>]*>.*?<b>(\d+)</b>', text, re.IGNORECASE)
            seeds = seeds_match.group(1) if seeds_match else '0'
            leech = leech_match.group(1) if leech_match else '0'
            return seeds, leech
        except:
            return '0', '0'

    def _parse_date(self, date_str):
        """
        Converts relative date strings into Epoch timestamps.
        """
        try:
            clean_str = date_str.lower().replace('&nbsp;', ' ').replace('\xa0', ' ').strip()
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
        except:
            return -1

    def _fetch_magnet_link(self, torrent):
        """
        Fetches the details page to retrieve the magnet link.
        """
        try:
            details_html = retrieve_url(torrent['desc_link'])
            if not details_html: return None

            soup = BeautifulSoup(details_html, 'html.parser')
            magnet_anchor = soup.find('a', href=re.compile(r'^magnet:\?'))

            if magnet_anchor:
                torrent['link'] = magnet_anchor.get('href')
                return torrent
        except: pass
        return None

    def search(self, what, cat='all'):
        """
        Main search execution method.
        """
        if not BEAUTIFULSOUP_AVAILABLE: return

        query_unquoted = urllib.parse.unquote(what)
        clean_query = self._clean_query_strict(query_unquoted)
        if not clean_query: return

        target_cat_name = self.supported_categories.get(cat, '')
        use_python_filtering = False

        # Configure pagination and filtering
        pages_to_scrape = DEFAULT_PAGES
        if cat == 'movies':
            pages_to_scrape = MOVIES_PAGES
            use_python_filtering = True
        elif cat == 'tv':
            pages_to_scrape = TV_PAGES
            use_python_filtering = True

        encoded_query = urllib.parse.quote(clean_query)
        base_url = f"{self.url}/get-posts/keywords:{encoded_query}"

        if use_python_filtering or not target_cat_name or target_cat_name == 'all':
            search_url_root = f"{base_url}"
        else:
            search_url_root = f"{base_url}:category:{target_cat_name}"

        all_torrents = []

        # Multi-page Loop
        for page in range(1, pages_to_scrape + 1):
            if page > 1:
                current_url = f"{search_url_root}/?page={page}"
            else:
                current_url = f"{search_url_root}/"

            html = retrieve_url(current_url)
            if not html: continue

            soup = BeautifulSoup(html, 'html.parser')
            rows = soup.find_all('div', class_='tgxtablerow')

            for row in rows:
                try:
                    cells = row.find_all('div', class_='tgxtablecell')
                    if len(cells) < 5: continue

                    # 1. Category Filter
                    if use_python_filtering:
                        category_elem = cells[0].find('small')
                        if category_elem and category_elem.text.strip() != target_cat_name:
                            continue
                        elif not category_elem: continue

                    # 2. Extract Title
                    title_cell = None
                    for cell in cells:
                        cell_classes = cell.get('class', [])
                        if ('clickable-row' in cell_classes or 'click' in cell_classes) and cell.find('a', class_='txlight'):
                            title_cell = cell
                            break
                    if not title_cell: continue

                    title_anchor = title_cell.find('a', class_='txlight')
                    title = title_anchor.get('title', '').strip() or title_anchor.text.strip()

                    # 3. Exact Match Check
                    if not self._verify_match(clean_query, title):
                        continue

                    # 4. Extract Link
                    href = title_cell.get('data-href') or title_anchor.get('href', '')
                    if not href: continue
                    desc_link = href if href.startswith('http') else self.url + (href if href.startswith('/') else '/' + href)

                    # 5. Extract Stats
                    size = self._extract_size_from_row(row)
                    seeds, leech = '0', '0'
                    for cell in cells:
                        if cell.find('span', title='Seeders/Leechers'):
                            seeds, leech = self._extract_seeds_leech(cell)
                            break

                    # 6. Extract Date
                    pub_date = -1
                    if cells:
                        last_cell = cells[-1]
                        if last_cell.contents:
                            first_content = last_cell.contents[0]
                            if isinstance(first_content, NavigableString):
                                pub_date = self._parse_date(str(first_content))

                    all_torrents.append({
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

        # Retrieve Magnets
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(self._fetch_magnet_link, t) for t in all_torrents]
            for future in as_completed(futures):
                if result := future.result():
                    if result.get('link'):
                        prettyPrinter(result)
