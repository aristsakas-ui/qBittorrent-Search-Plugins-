#
# qBittorrent Search Plugin for TorrentGalaxy
# Intelligent multi-pass search with advanced scoring
#
# License: GPL v3
# Description: Advanced search plugin for TorrentGalaxy with smart query processing
#              and result ranking. Features multi-pass searching and parallel processing.
#

import re
import urllib.parse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

# Configuration
MOVIES_PAGES = 3
TV_PAGES = 4
DEFAULT_PAGES = 2
MAX_MAGNET_WORKERS = 10
SAFETY_NET_RESULTS_COUNT = 5

# Environment detection
try:
    from novaprinter import prettyPrinter
    from helpers import retrieve_url
    QBITTORRENT_ENV = True
except ImportError:
    QBITTORRENT_ENV = False
    def prettyPrinter(dict):
        print(f"PRETTYPRINTER: {dict}")
    def retrieve_url(url):
        import urllib.request
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return response.read().decode('utf-8')
        except Exception as e:
            return ""

# BeautifulSoup import
try:
    from bs4 import BeautifulSoup
    BEAUTIFULSOUP_AVAILABLE = True
except ImportError:
    BEAUTIFULSOUP_AVAILABLE = False
    print("ERROR: Install beautifulsoup4: pip install beautifulsoup4")


class torrentgalaxy_one(object):
    """
    TorrentGalaxy search plugin for qBittorrent
    Features intelligent query processing and result ranking
    """

    url = 'https://torrentgalaxy.one'
    name = 'TorrentGalaxy (Intelligent)'

    supported_categories = {
        'all': 'all',
        'movies': 'Movies',
        'tv': 'TV',
        'music': 'Music',
        'games': 'Games',
        'software': 'Apps',
        'anime': 'Anime',
        'books': 'Books',
        'other': 'Other'
    }

    def _clean_query_conservative(self, query):
        """Clean query while preserving important symbols like hyphens and episode patterns"""
        query = re.sub(r'[\(\[]\d{4}[\)\]]', '', query)
        return re.sub(r'\s+', ' ', query).strip()

    def _clean_query_aggressive(self, query):
        """Aggressive cleaning - remove all symbols for fallback search"""
        query = re.sub(r'[^a-zA-Z0-9\s]', ' ', query)
        return re.sub(r'\s+', ' ', query).strip()

    def _get_search_keywords(self, query):
        """Extract keywords for scoring engine"""
        query = re.sub(r'[^a-zA-Z0-9]', ' ', query)
        return [word for word in re.sub(r'\s+', ' ', query).strip().lower().split() if len(word) > 1]

    def _calculate_relevance_score(self, torrent_title, search_keywords):
        """Advanced scoring based on keyword matching and completeness"""
        title_lower = torrent_title.lower()
        title_keywords = self._get_search_keywords(title_lower)
        title_counts = Counter(title_keywords)
        search_counts = Counter(search_keywords)

        # Bonus for containing all search words
        bonus = 100 if all(word in title_counts for word in search_keywords) else 0

        # Base score from term frequency
        base_score = sum(min(search_counts[word], title_counts.get(word, 0)) for word in search_counts)

        return bonus + base_score

    def _get_pages_for_category(self, category):
        """Determine pages to fetch based on category"""
        return {
            'movies': MOVIES_PAGES,
            'tv': TV_PAGES
        }.get(category, DEFAULT_PAGES)

    def _extract_size_from_row(self, row):
        """Extract file size from torrent row"""
        try:
            size_spans = row.find_all('span', class_='badge badge-secondary txlight',
                                    style='border-radius:4px;')
            for span in size_spans:
                size_text = span.text.strip().replace('&nbsp;', ' ').replace('\xa0', ' ')
                if any(unit in size_text.upper() for unit in ['GB', 'MB', 'KB', 'TB']):
                    return size_text
            return '0 MB'
        except:
            return '0 MB'

    def _extract_seeds_leech(self, cell):
        """Extract seeders and leechers count"""
        try:
            text = str(cell)
            seeds_match = re.search(r'color="green"[^>]*>.*?<b>(\d+)</b>', text, re.IGNORECASE)
            leech_match = re.search(r'color="#ff0000"[^>]*>.*?<b>(\d+)</b>', text, re.IGNORECASE)
            seeds = seeds_match.group(1) if seeds_match else '0'
            leech = leech_match.group(1) if leech_match else '0'
            return seeds, leech
        except:
            return '0', '0'

    def _parse_torrent_row(self, row, target_category):
        """Parse a single torrent result row"""
        try:
            cells = row.find_all('div', class_='tgxtablecell')
            if len(cells) < 5:
                return None

            # Extract category
            category_elem = cells[0].find('small')
            if not category_elem:
                return None
            torrent_category = category_elem.text.strip()

            # Category filtering
            if target_category != 'all':
                expected = self.supported_categories.get(target_category)
                if expected and torrent_category != expected:
                    return None

            # FIXED: Find title cell - look for cells with EITHER 'clickable-row' OR 'click' classes
            title_cell = None
            for cell in cells:
                cell_classes = cell.get('class', [])
                # Check if EITHER class is present in the cell
                if 'clickable-row' in cell_classes or 'click' in cell_classes:
                    # Also check if this cell contains a title link
                    title_anchor = cell.find('a', class_='txlight')
                    if title_anchor:
                        title_cell = cell
                        break

            if not title_cell:
                return None

            # Extract title and link
            title_anchor = title_cell.find('a', class_='txlight')
            if not title_anchor:
                return None

            title = title_anchor.get('title', '').strip() or title_anchor.text.strip()

            # Get detail link from data-href attribute of the title cell
            detail_path = title_cell.get('data-href', '')
            if detail_path:
                if not detail_path.startswith('/'):
                    detail_path = '/' + detail_path
                desc_link = f"{self.url}{detail_path}"
            else:
                # Fallback to anchor href
                desc_link = title_anchor.get('href', '')
                if desc_link and not desc_link.startswith('http'):
                    desc_link = f"{self.url}{desc_link}"

            # Extract seeds/leechers
            seeds, leech = '0', '0'
            for cell in cells:
                health_span = cell.find('span', title='Seeders/Leechers')
                if health_span:
                    seeds, leech = self._extract_seeds_leech(cell)
                    break

            # Extract size
            size = self._extract_size_from_row(row)

            return {
                'name': title,
                'desc_link': desc_link,
                'seeds': seeds,
                'leech': leech,
                'size': size,
                'category': torrent_category
            }

        except Exception as e:
            return None

    def _fetch_search_page(self, page_num, base_url, category):
        """Fetch and parse a single search results page"""
        page_url = f"{base_url}?page={page_num}" if page_num > 1 else base_url
        try:
            html_content = retrieve_url(page_url)
            if not html_content:
                return []

            soup = BeautifulSoup(html_content, 'html.parser')
            results = []

            for row in soup.find_all('div', class_='tgxtablerow'):
                torrent = self._parse_torrent_row(row, category)
                if torrent:
                    results.append(torrent)

            return results
        except Exception:
            return []

    def _execute_search_pass(self, query, category):
        """Execute a complete search pass with multiple pages"""
        if not query:
            return []

        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"{self.url}/get-posts/keywords:{encoded_query}/"
        max_pages = self._get_pages_for_category(category)

        all_results = []
        with ThreadPoolExecutor(max_workers=max_pages) as executor:
            futures = [executor.submit(self._fetch_search_page, i, search_url, category)
                      for i in range(1, max_pages + 1)]
            for future in as_completed(futures):
                all_results.extend(future.result())

        return all_results

    def _fetch_magnet_link(self, torrent):
        """Fetch magnet link from torrent detail page"""
        try:
            details_html = retrieve_url(torrent['desc_link'])
            if not details_html:
                return None

            soup = BeautifulSoup(details_html, 'html.parser')
            magnet_anchor = soup.find('a', href=lambda x: x and x.startswith('magnet:'))

            if magnet_anchor and magnet_anchor.get('href'):
                torrent['link'] = magnet_anchor['href']
                return torrent
        except Exception:
            pass
        return None

    def search(self, what, cat='all'):
        """Main search function called by qBittorrent"""
        if not BEAUTIFULSOUP_AVAILABLE:
            return

        decoded_query = urllib.parse.unquote_plus(what)
        search_keywords = self._get_search_keywords(decoded_query)

        # Multi-pass search strategy
        pass1_query = self._clean_query_conservative(decoded_query)
        pass1_results = self._execute_search_pass(pass1_query, cat)

        pass2_query = self._clean_query_aggressive(decoded_query)
        pass2_results = []
        if pass2_query.lower() != pass1_query.lower():
            pass2_results = self._execute_search_pass(pass2_query, cat)

        # Combine and deduplicate results
        all_torrents = {t['desc_link']: t for t in pass1_results + pass2_results}
        candidates = list(all_torrents.values())

        if not candidates:
            return

        # Score and sort results
        for torrent in candidates:
            torrent['score'] = self._calculate_relevance_score(torrent['name'], search_keywords)
            torrent['seeds_int'] = int(torrent['seeds']) if torrent['seeds'].isdigit() else 0

        candidates.sort(key=lambda t: (t['score'], t['seeds_int']), reverse=True)

        # Select top results with safety net
        torrents_to_fetch = []
        if candidates:
            max_score = candidates[0]['score']
            top_tier = [t for t in candidates if t['score'] == max_score]
            lower_tier = [t for t in candidates if t['score'] < max_score]

            torrents_to_fetch.extend(top_tier)
            torrents_to_fetch.extend(lower_tier[:SAFETY_NET_RESULTS_COUNT])

        # Fetch magnet links and output results
        with ThreadPoolExecutor(max_workers=MAX_MAGNET_WORKERS) as executor:
            futures = [executor.submit(self._fetch_magnet_link, t) for t in torrents_to_fetch]
            for future in as_completed(futures):
                if result := future.result():
                    safe_name = re.sub(r'[\\/*?:"<>|]', '', result['name'])
                    prettyPrinter({
                        'link': result['link'],
                        'name': safe_name,
                        'size': result['size'],
                        'seeds': result['seeds'],
                        'leech': result['leech'],
                        'engine_url': self.url,
                        'desc_link': result['desc_link']
                    })


# Test mode
if __name__ == "__main__" and not QBITTORRENT_ENV:
    plugin = torrentgalaxy_one()

    # Simple test
    print("TorrentGalaxy Plugin - Basic Test")
    test_query = input("Enter test search: ").strip()
    if test_query:
        print(f"Searching for: {test_query}")
        plugin.search(test_query)
