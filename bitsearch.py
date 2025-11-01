#
# qBittorrent search plugin for Bitsearch 

import re
import urllib.parse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

# --- User-Configurable Settings ---
MAX_PAGES_TO_FETCH = 3
MAX_MAGNET_WORKERS = 10
SAFETY_NET_RESULTS_COUNT = 8
ENABLE_CONSOLE_TEST = True  # Set to True for testing

# --- qBittorrent Environment Imports ---
try:
    from novaprinter import prettyPrinter
    from helpers import retrieve_url
    IN_QBITTORRENT = True
except ImportError:
    IN_QBITTORRENT = False
    # Mock for testing
    class MockPrettyPrinter:
        @staticmethod
        def prettyPrinter(result):
            print(f"RESULT: {result['name'][:50]}... | Seeds: {result['seeds']} | Leech: {result['leech']} | Size: {result['size']}")

    prettyPrinter = MockPrettyPrinter.prettyPrinter

    class MockRetrieveUrl:
        @staticmethod
        def retrieve_url(url):
            import urllib.request
            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    return response.read().decode('utf-8')
            except Exception as e:
                print(f"ERROR retrieving {url}: {e}")
                return ""

    retrieve_url = MockRetrieveUrl.retrieve_url

# --- Required Library: BeautifulSoup ---
try:
    from bs4 import BeautifulSoup
    BEAUTIFULSOUP_AVAILABLE = True
except ImportError:
    BEAUTIFULSOUP_AVAILABLE = False
    print("ERROR: BeautifulSoup not available")

# --- Main Plugin Class ---
class bitsearch(object):
    url = 'https://bitsearch.to'
    name = 'Bitsearch (Fixed Categories)'

    supported_categories = {
        'all': 'all',
        'movies': 'movies',
        'tv': 'tv',
        'games': 'games',
        'music': 'music',
        'software': 'software',
        'anime': 'anime'
    }

    def __init__(self):
        self.test_results = {
            'search_passes': 0,
            'parsed_torrents': 0,
            'magnet_success': 0,
            'category_matches': 0,
            'errors': []
        }

    def _log_test(self, message, is_error=False):
        """Log test messages when console testing is enabled"""
        if ENABLE_CONSOLE_TEST and not IN_QBITTORRENT:
            if is_error:
                print(f"TEST ERROR: {message}")
                self.test_results['errors'].append(message)
            else:
                print(f"TEST: {message}")

    def _get_conservative_query(self, query):
        """PASS 1: Smart cleaning - only removes years, preserves important symbols."""
        query = re.sub(r'[\(\[]\d{4}[\)\]]', '', query)
        query = re.sub(r'\s+', ' ', query)
        return query.strip()

    def _get_aggressive_query(self, query):
        """PASS 2: Aggressive cleaning - removes all symbols for fallback."""
        query = re.sub(r'[^a-zA-Z0-9\s]', ' ', query)
        query = re.sub(r'\s+', ' ', query)
        return query.strip()

    def _get_keywords_for_scoring(self, query):
        """Cleans a string to generate keywords for scoring."""
        query = re.sub(r'[^a-zA-Z0-9]', ' ', query)
        query = re.sub(r'\s+', ' ', query)
        return [word for word in query.strip().lower().split() if len(word) > 1]

    def _calculate_advanced_score(self, torrent_title, search_keywords):
        """Calculates score using completeness bonus + term frequency."""
        title_lower = torrent_title.lower()
        title_keywords = self._get_keywords_for_scoring(title_lower)
        title_word_counts = Counter(title_keywords)
        search_word_counts = Counter(search_keywords)
        unique_search_words = set(search_keywords)

        bonus_score = 0
        if unique_search_words and all(word in title_word_counts for word in unique_search_words):
            bonus_score = 100

        base_score = 0
        for word, count_in_search in search_word_counts.items():
            count_in_title = title_word_counts.get(word, 0)
            base_score += min(count_in_search, count_in_title)

        return bonus_score + base_score

    def _execute_search_pass(self, query, cat='all'):
        """Executes one search pass using multiple parsing strategies."""
        if not query:
            return []

        self._log_test(f"Starting search pass for: '{query}' (category: {cat})")

        encoded_query = urllib.parse.quote_plus(query)

        # Add category to URL if not 'all'
        if cat != 'all':
            category_param = self._get_category_param(cat)
            base_url = f"{self.url}/search?q={encoded_query}&category={category_param}&sort=seeders"
        else:
            base_url = f"{self.url}/search?q={encoded_query}&sort=seeders"

        pass_torrents = []

        # Try multiple page parsing strategies
        for page_num in range(1, MAX_PAGES_TO_FETCH + 1):
            page_url = f"{base_url}&page={page_num}" if page_num > 1 else base_url

            try:
                self._log_test(f"Fetching page {page_num}: {page_url}")
                page_html = retrieve_url(page_url)

                if not page_html:
                    self._log_test(f"Empty response for page {page_num}", True)
                    continue

                soup = BeautifulSoup(page_html, 'html.parser')

                # Use the most reliable parsing strategy from our tests
                torrents = self._parse_search_results_v2(soup, cat, page_num)
                if torrents:
                    pass_torrents.extend(torrents)
                    self._log_test(f"Page {page_num} found {len(torrents)} torrents")

            except Exception as e:
                self._log_test(f"Error processing page {page_num}: {str(e)}", True)
                continue

        self.test_results['search_passes'] += 1
        self.test_results['parsed_torrents'] += len(pass_torrents)
        self._log_test(f"Search pass completed: {len(pass_torrents)} torrents found")

        return pass_torrents

    def _get_category_param(self, cat):
        """Convert category name to bitsearch URL parameter."""
        category_map = {
            'movies': '1',
            'tv': '2',
            'games': '3',
            'music': '4',
            'software': '5',
            'anime': '6'
        }
        return category_map.get(cat, '0')  # 0 = all

    def _parse_search_results_v2(self, soup, cat, page_num):
        """Improved parsing based on test results - uses actual site structure."""
        torrents = []

        # Find all result items - use the pattern that worked in tests
        result_items = soup.find_all('li', class_='search-result')
        if not result_items:
            result_items = soup.find_all('div', class_=re.compile(r'search-result|result-item|item|card'))

        self._log_test(f"Page {page_num}: Found {len(result_items)} result items")

        for item in result_items:
            try:
                torrent = self._parse_torrent_item_v2(item, cat)
                if torrent:
                    torrents.append(torrent)

            except Exception as e:
                self._log_test(f"Error parsing item: {str(e)}", True)
                continue

        return torrents

    def _parse_torrent_item_v2(self, item, cat):
        """Parse individual torrent item with improved category detection."""
        # Get all text content for analysis
        item_text = item.get_text().lower()
        item_html = str(item)

        # Extract name from title link (most reliable method)
        name_link = item.find('a', href=re.compile(r'/torrent/'))
        if not name_link:
            return None

        name = name_link.get_text(strip=True)
        desc_link = name_link.get('href')
        if desc_link and not desc_link.startswith('http'):
            desc_link = self.url + desc_link

        # Extract stats using regex (most reliable method)
        seeds, leech, size = self._extract_stats_with_regex(item_text)

        # IMPROVED CATEGORY DETECTION
        detected_category = self._detect_torrent_category_v2(name, item_text, item_html)

        # Apply category filter
        if cat != 'all' and detected_category != cat:
            return None

        self.test_results['category_matches'] += 1

        return {
            'name': name,
            'desc_link': desc_link,
            'seeds': seeds,
            'leech': leech,
            'size': size,
            'detected_category': detected_category
        }

    def _detect_torrent_category_v2(self, name, item_text, item_html):
        """Improved category detection using multiple signals."""
        name_lower = name.lower()
        text_lower = item_text.lower()

        # Music detection - look for music-specific patterns
        music_patterns = [
            r'\b(mp3|flac|aac|wav|ogg|album|track|song|music|artist|band|320kbps|lossless)\b',
            r'\.(mp3|flac|aac|wav|ogg)\b',
            r'\[(mp3|flac|320kbps)\]',
        ]

        for pattern in music_patterns:
            if re.search(pattern, name_lower) or re.search(pattern, text_lower):
                return 'music'

        # Movie detection
        movie_patterns = [
            r'\b(bluray|dvdrip|webdl|web-dl|hdcam|bdrip|brrip|x264|x265|hevc)\b',
            r'\.(mkv|mp4|avi|mov|wmv)\b',
            r'\d{4}\.?(p|i)',
            r'(season|s\d+)|(episode|e\d+)',
        ]

        for pattern in movie_patterns[:3]:  # First 3 patterns for movies
            if re.search(pattern, name_lower):
                return 'movies'

        # TV detection
        tv_patterns = [
            r'(s\d+\s*e\d+|season\s*\d+\s*episode\s*\d+)',
            r'\b(tv|series|episode|season)\b',
        ]

        for pattern in tv_patterns:
            if re.search(pattern, name_lower):
                return 'tv'

        # Software detection
        software_patterns = [
            r'\b(software|app|application|windows|macos|linux|crack|keygen|patch|installer)\b',
            r'\.(exe|msi|dmg|pkg|deb|rpm)\b',
        ]

        for pattern in software_patterns:
            if re.search(pattern, name_lower):
                return 'software'

        # Games detection
        game_patterns = [
            r'\b(game|pc|steam|repack|fitgirl|gog|iso)\b',
            r'\.(iso|rar|zip)\b',
        ]

        for pattern in game_patterns:
            if re.search(pattern, name_lower):
                return 'games'

        # Anime detection
        anime_patterns = [
            r'\b(anime|manga|japanese|subbed|dubbed)\b',
            r'\[(sub|dub)\]',
        ]

        for pattern in anime_patterns:
            if re.search(pattern, name_lower):
                return 'anime'

        # Default to all if no specific category detected
        return 'all'

    def _extract_stats_with_regex(self, text):
        """Extract seeds, leechers, and size using robust regex patterns."""
        # Seeds extraction
        seeds_patterns = [
            r'(\d+)\s*seed',
            r'seeds?:\s*(\d+)',
            r'seeders?:\s*(\d+)',
            r'<[^>]*>(\d+)<[^>]*>\s*seed'
        ]

        leech_patterns = [
            r'(\d+)\s*leech',
            r'leeches?:\s*(\d+)',
            r'leechers?:\s*(\d+)',
            r'<[^>]*>(\d+)<[^>]*>\s*leech'
        ]

        size_patterns = [
            r'(\d+\.?\d*)\s*(GB|MB|KB|TB)',
            r'size:\s*(\d+\.?\d*)\s*(GB|MB|KB|TB)',
            r'(\d+\.?\d*)\s*(g|m|k|t)b',
        ]

        seeds = '0'
        leech = '0'
        size = '0 MB'

        # Find seeds
        for pattern in seeds_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                seeds = match.group(1)
                break

        # Find leechers
        for pattern in leech_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                leech = match.group(1)
                break

        # Find size
        for pattern in size_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                size_value = match.group(1)
                size_unit = match.group(2).upper()
                if len(size_unit) == 1:  # g, m, k, t
                    size_unit = size_unit + 'B'
                size = f"{size_value} {size_unit}"
                break

        return seeds, leech, size

    def _fetch_magnet_link(self, torrent):
        """Fetch magnet link with multiple strategies."""
        if not torrent.get('desc_link'):
            return None

        try:
            self._log_test(f"Fetching magnet for: {torrent['name'][:30]}...")
            details_html = retrieve_url(torrent['desc_link'])

            if not details_html:
                self._log_test(f"Empty response for magnet page", True)
                return None

            details_soup = BeautifulSoup(details_html, 'html.parser')

            # Multiple magnet link patterns
            magnet_patterns = [
                details_soup.find('a', href=re.compile(r'^magnet:')),
                details_soup.find('a', class_=re.compile(r'magnet|download|btn')),
                details_soup.find('button', onclick=re.compile(r'magnet:')),
                details_soup.find('div', class_=re.compile(r'magnet|download'))
            ]

            magnet_link = None

            # Try direct patterns first
            for pattern in magnet_patterns:
                if pattern:
                    if pattern.name == 'a' and pattern.get('href', '').startswith('magnet:'):
                        magnet_link = pattern.get('href')
                        break
                    elif pattern.name == 'button' and pattern.get('onclick'):
                        magnet_match = re.search(r"magnet:[^\']+", pattern.get('onclick'))
                        if magnet_match:
                            magnet_link = magnet_match.group(0)
                            break
                    elif pattern.name == 'div':
                        magnet_a = pattern.find('a', href=re.compile(r'^magnet:'))
                        if magnet_a:
                            magnet_link = magnet_a.get('href')
                            break

            # Fallback: Search all links
            if not magnet_link:
                all_links = details_soup.find_all('a', href=True)
                for link in all_links:
                    if link.get('href', '').startswith('magnet:'):
                        magnet_link = link.get('href')
                        break

            if magnet_link:
                torrent['link'] = magnet_link
                self.test_results['magnet_success'] += 1
                self._log_test(f"Magnet found successfully")
                return torrent
            else:
                self._log_test(f"No magnet link found", True)

        except Exception as e:
            self._log_test(f"Error fetching magnet: {str(e)}", True)

        return None

    def search(self, what, cat='all'):
        """Main search function called by qBittorrent."""
        if not BEAUTIFULSOUP_AVAILABLE:
            self._log_test("BeautifulSoup not available - cannot search", True)
            return

        # Reset test results for this search
        self.test_results = {
            'search_passes': 0,
            'parsed_torrents': 0,
            'magnet_success': 0,
            'category_matches': 0,
            'errors': []
        }

        decoded_what = urllib.parse.unquote_plus(what)
        search_keywords = self._get_keywords_for_scoring(decoded_what)

        self._log_test(f"Starting search for: '{decoded_what}' in category: '{cat}'")

        # --- Multi-Pass Search Execution ---
        pass1_query = self._get_conservative_query(decoded_what)
        pass1_results = self._execute_search_pass(pass1_query, cat)

        pass2_query = self._get_aggressive_query(decoded_what)
        pass2_results = []
        if pass2_query.lower() != pass1_query.lower():
            pass2_results = self._execute_search_pass(pass2_query, cat)

        # --- Improved De-duplication ---
        all_torrents = {}
        for torrent in pass1_results + pass2_results:
            # Use name + size as key for better deduplication
            key = f"{torrent['name']}_{torrent['size']}"
            if key not in all_torrents:
                all_torrents[key] = torrent

        final_candidates = list(all_torrents.values())

        self._log_test(f"After deduplication: {len(final_candidates)} unique torrents")
        self._log_test(f"Categories found: {set(t.get('detected_category', 'unknown') for t in final_candidates)}")

        if not final_candidates:
            self._print_test_summary()
            return

        # Advanced scoring and sorting
        for torrent in final_candidates:
            torrent['score'] = self._calculate_advanced_score(torrent['name'], search_keywords)
            try:
                torrent['seeds_int'] = int(re.sub(r'[^\d]', '', torrent['seeds']))
            except ValueError:
                torrent['seeds_int'] = 0

        final_candidates.sort(key=lambda t: (t['score'], t['seeds_int']), reverse=True)

        # --- Select Results (Top Tier + Safety Net) ---
        torrents_to_fetch = []
        if final_candidates:
            max_score = final_candidates[0]['score']
            top_tier = [t for t in final_candidates if t['score'] == max_score]
            torrents_to_fetch.extend(top_tier)

            lower_tier = [t for t in final_candidates if t['score'] < max_score]
            torrents_to_fetch.extend(lower_tier[:SAFETY_NET_RESULTS_COUNT])

        self._log_test(f"Selected {len(torrents_to_fetch)} torrents for magnet fetching")

        # --- Fetch Magnet Links and Output ---
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

        self._print_test_summary()

    def _print_test_summary(self):
        """Print test results summary when console testing is enabled"""
        if ENABLE_CONSOLE_TEST and not IN_QBITTORRENT:
            print("\n" + "="*50)
            print("TEST SUMMARY:")
            print(f"Search passes completed: {self.test_results['search_passes']}")
            print(f"Torrents parsed: {self.test_results['parsed_torrents']}")
            print(f"Category matches: {self.test_results['category_matches']}")
            print(f"Magnet links fetched: {self.test_results['magnet_success']}")
            print(f"Errors encountered: {len(self.test_results['errors'])}")

            if self.test_results['errors']:
                print("\nERRORS:")
                for error in self.test_results['errors'][:5]:  # Show first 5 errors
                    print(f"  - {error}")
            print("="*50)

# --- Console Testing Function ---
def run_console_test():
    """Run comprehensive tests from console"""
    global ENABLE_CONSOLE_TEST
    ENABLE_CONSOLE_TEST = True

    print("Starting Bitsearch Plugin Console Test...")

    # Test cases - focus on music to verify category filtering
    test_cases = [
        ("Limitless", "music"),
        ("Ulla Straus", "music"),
        ("Limitless", "movies"),
        ("Linux", "software"),
    ]

    engine = bitsearch()

    for query, category in test_cases:
        print(f"\n{'#'*60}")
        print(f"TESTING: '{query}' in category '{category}'")
        print(f"{'#'*60}")

        engine.search(query, category)

        # Small delay between tests
        import time
        time.sleep(2)

# --- Auto-run test if executed directly ---
if __name__ == "__main__" and not IN_QBITTORRENT:
    run_console_test()
