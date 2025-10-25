from __future__ import print_function
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

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

# --- User-Configurable Settings ---
MAX_PAGES_TO_FETCH = 2
MAX_MAGNET_WORKERS = 10
SAFETY_NET_RESULTS_COUNT = 5

LEETX_DOMAIN = "https://1337x.to"


class leetx(object):
    url = LEETX_DOMAIN
    name = "1337x (Intelligent)"

    supported_categories = {
        'all': 'All',
        'movies': 'Movies',
        'tv': 'TV',
        'music': 'Music',
        'games': 'Games',
        'anime': 'Anime',
        'software': 'Apps'
    }

    # --- Intelligent Search Methods from Second Script ---

    def _get_conservative_query(self, query):
        """
        PASS 1: The smart, conservative cleaning method.
        Only removes unambiguous metadata (like years in parentheses) and preserves important symbols.
        """
        # Remove year in parentheses, e.g., (1965) or [2022]
        query = re.sub(r'[\(\[]\d{4}[\)\]]', '', query)
        # Clean up multiple spaces
        query = re.sub(r'\s+', ' ', query)
        return query.strip()

    def _get_aggressive_query(self, query):
        """
        PASS 2: The aggressive, fallback cleaning method.
        Removes ALL symbols for titles with junk punctuation.
        """
        query = re.sub(r'[^a-zA-Z0-9\s]', ' ', query)
        query = re.sub(r'\s+', ' ', query)
        return query.strip()

    def _get_keywords_for_scoring(self, query):
        """Cleans a string to generate keywords for scoring."""
        query = re.sub(r'[^a-zA-Z0-9]', ' ', query)
        query = re.sub(r'\s+', ' ', query)
        # Exclude single-letter words as poor keywords
        return [word for word in query.strip().lower().split() if len(word) > 1]

    def _calculate_advanced_score(self, torrent_title, search_keywords):
        """Calculates score using two-part system: completeness bonus + term frequency."""
        title_lower = torrent_title.lower()
        title_keywords = self._get_keywords_for_scoring(title_lower)
        title_word_counts = Counter(title_keywords)
        search_word_counts = Counter(search_keywords)
        unique_search_words = set(search_keywords)

        # Completeness bonus: +100 if title contains ALL search words
        bonus_score = 0
        if unique_search_words and all(word in title_word_counts for word in unique_search_words):
            bonus_score = 100

        # Term frequency score
        base_score = 0
        for word, count_in_search in search_word_counts.items():
            count_in_title = title_word_counts.get(word, 0)
            base_score += min(count_in_search, count_in_title)

        return bonus_score + base_score

    def _execute_search_pass(self, query, cat):
        """Executes one full search pass with the given query."""
        if not query:
            return []

        # Build search URL based on category
        search_page = "search" if cat == 'all' else 'category-search'
        encoded_query = quote_plus(query)

        search_url = f"{self.url}/{search_page}/{encoded_query}/"
        if cat != 'all' and cat in self.supported_categories:
            search_url += self.supported_categories[cat] + "/"

        url_template = search_url + "{page_num}/"

        # Fetch multiple pages in parallel
        pass_torrents = []
        with ThreadPoolExecutor(max_workers=MAX_PAGES_TO_FETCH) as executor:
            futures = [
                executor.submit(self._fetch_and_parse_page, i, url_template, cat)
                for i in range(1, MAX_PAGES_TO_FETCH + 1)
            ]
            for future in as_completed(futures):
                pass_torrents.extend(future.result())

        return pass_torrents

    def _fetch_and_parse_page(self, page_num, url_template, cat):
        """Fetches and parses a single page using BeautifulSoup."""
        page_url = url_template.format(page_num=page_num)
        try:
            page_html = retrieve_url(page_url)
            soup = BeautifulSoup(page_html, 'html.parser')

            # Find the results table
            table = soup.find('table', class_='table-list')
            if not table:
                return []

        except Exception:
            return []

        page_torrents = []

        # Find all torrent rows (skip header if present)
        rows = table.find_all('tr')[1:] if table.find('tr') else []

        for row in rows:
            try:
                result = {
                    'engine_url': self.url,
                    'leech': '0',
                    'leeches': '0'
                }

                # Extract torrent name and link
                name_link = row.find('a', href=re.compile(r'/torrent/'))
                if name_link:
                    result['name'] = name_link.get_text(strip=True)
                    result['desc_link'] = self.url + name_link['href']
                    result['link'] = self.url + name_link['href']  # Will be replaced with magnet

                # Extract seeds, leeches, size from table cells
                cells = row.find_all('td')
                for i, cell in enumerate(cells):
                    cell_text = cell.get_text(strip=True)
                    cell_class = cell.get('class', [])

                    # Use class-based detection first
                    if 'seeds' in str(cell_class):
                        result['seeds'] = cell_text
                    elif 'leeches' in str(cell_class):
                        result['leeches'] = cell_text
                        result['leech'] = cell_text
                    elif 'size' in str(cell_class):
                        result['size'] = cell_text.split('\n')[0].strip()  # Clean size

                    # Fallback: use position-based detection
                    elif i == 1 and 'seeds' not in result:
                        result['seeds'] = cell_text
                    elif i == 2 and 'leeches' not in result:
                        result['leeches'] = cell_text
                        result['leech'] = cell_text
                    elif i == 3 and 'size' not in result:
                        result['size'] = cell_text

                # Ensure we have all required fields
                if result.get('name') and result.get('seeds'):
                    page_torrents.append(result)

            except (IndexError, AttributeError, KeyError):
                continue

        return page_torrents

    def _fetch_magnet_link(self, torrent):
        """Fetches magnet link from torrent detail page."""
        try:
            details_page = retrieve_url(torrent['desc_link'])
            soup = BeautifulSoup(details_page, 'html.parser')

            # Look for magnet link - multiple strategies
            magnet_link = None

            # Strategy 1: Look for magnet link by href pattern
            magnet_anchors = soup.find_all('a', href=re.compile(r'^magnet:'))
            if magnet_anchors:
                magnet_link = magnet_anchors[0]['href']

            # Strategy 2: Look for download buttons
            if not magnet_link:
                download_btns = soup.find_all('a', class_=re.compile(r'download|magnet'))
                for btn in download_btns:
                    href = btn.get('href', '')
                    if href.startswith('magnet:'):
                        magnet_link = href
                        break

            # Strategy 3: Look for itorrents mirror
            if not magnet_link:
                itorrents_btn = soup.find('a', string=re.compile(r'ITORRENTS', re.I))
                if itorrents_btn and itorrents_btn.get('href'):
                    magnet_link = itorrents_btn['href']

            if magnet_link:
                torrent['link'] = magnet_link
                return torrent

        except Exception:
            pass

        return None

    def download_torrent(self, info):
        """Download torrent file - uses magnet links primarily."""
        # Since we now use magnet links, we can simply call download_file
        # But we need to ensure it's a magnet link
        if info.startswith('magnet:'):
            print(download_file(info))
        else:
            # Fallback to torrent file download
            try:
                page_html = retrieve_url(info)
                soup = BeautifulSoup(page_html, 'html.parser')

                # Look for direct torrent download
                torrent_links = soup.find_all('a', href=re.compile(r'\.torrent$'))
                if torrent_links:
                    torrent_file = torrent_links[0]['href']
                    if torrent_file.startswith('//'):
                        torrent_file = 'https:' + torrent_file
                    elif torrent_file.startswith('/'):
                        torrent_file = self.url + torrent_file

                    print(download_file(torrent_file))
                    return

                # Fallback to magnet link
                magnet_links = soup.find_all('a', href=re.compile(r'^magnet:'))
                if magnet_links:
                    print(download_file(magnet_links[0]['href']))
                    return

                print('')
            except Exception:
                print('')

    def search(self, what, cat='all'):
        """Main search function with intelligent multi-pass strategy."""
        if 'BeautifulSoup' not in globals():
            return

        # Decode the search query
        decoded_what = unquote_plus(what)
        search_keywords = self._get_keywords_for_scoring(decoded_what)

        # --- Multi-Pass Search Execution ---
        # PASS 1: Conservative approach (preserves important symbols)
        pass1_query = self._get_conservative_query(decoded_what)
        pass1_results = self._execute_search_pass(pass1_query, cat)

        # PASS 2: Aggressive approach (removes all symbols)
        pass2_query = self._get_aggressive_query(decoded_what)
        pass2_results = []
        if pass2_query.lower() != pass1_query.lower():
            pass2_results = self._execute_search_pass(pass2_query, cat)

        # --- De-duplication and Scoring ---
        all_torrents = {t['desc_link']: t for t in pass1_results + pass2_results}
        final_candidates = list(all_torrents.values())

        if not final_candidates:
            return

        # Apply advanced scoring
        for torrent in final_candidates:
            torrent['score'] = self._calculate_advanced_score(torrent['name'], search_keywords)
            try:
                torrent['seeds_int'] = int(torrent['seeds'])
            except (ValueError, KeyError):
                torrent['seeds_int'] = 0

        # Sort by score (primary) and seeds (secondary)
        final_candidates.sort(key=lambda t: (t['score'], t['seeds_int']), reverse=True)

        # --- Select Results: Top Tier + Safety Net ---
        torrents_to_fetch = []
        if final_candidates:
            max_score = final_candidates[0]['score']

            # Add all top-scoring torrents
            top_tier = [t for t in final_candidates if t['score'] == max_score]
            torrents_to_fetch.extend(top_tier)

            # Add safety net of lower-scoring results
            lower_tier = [t for t in final_candidates if t['score'] < max_score]
            torrents_to_fetch.extend(lower_tier[:SAFETY_NET_RESULTS_COUNT])

        # --- Fetch Magnet Links in Parallel ---
        with ThreadPoolExecutor(max_workers=MAX_MAGNET_WORKERS) as executor:
            futures = [executor.submit(self._fetch_magnet_link, t) for t in torrents_to_fetch]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    # Clean filename for printing
                    safe_name = re.sub(r'[\\/*?:"<>|]', '', result['name'])

                    prettyPrinter({
                        'link': result['link'],
                        'name': safe_name,
                        'size': result.get('size', ''),
                        'seeds': result.get('seeds', '0'),
                        'leech': result.get('leech', '0'),
                        'engine_url': self.url,
                        'desc_link': result['desc_link']
                    })
