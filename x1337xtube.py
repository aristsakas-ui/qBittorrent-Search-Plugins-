#
# qBittorrent search plugin for 1337x.tube - The Definitive Intelligent Version
#
# ======================================================================================
# For the First-Time User: A Quick Guide to How This Script Works
# ======================================================================================
#
# Welcome! This script is designed to be a "smart" search tool that can get
# good results from a website with a very simple and fragile search engine.
#
# THE PROBLEM:
# The website's search is unpredictable. A search that works for one movie
# will fail for another.
#  - A search for "Boeing, Boeing (1965)" fails because adding the year
#    makes the search too specific and the site returns nothing.
#  - A search for "B-Movie: Lust & Sound" fails if we remove the hyphen
#    from "B-Movie", because the hyphen is a critical part of its name.
#
# THE SOLUTION - A HIERARCHICAL, MULTI-PASS SEARCH STRATEGY:
# This script mimics how a patient human would search. If the first attempt
# doesn't work well, it tries a different way.
#
#   - PASS 1: The "Conservative" Search (The Smart Approach)
#     The script's first and primary attempt is very careful. It only removes
#     unambiguous "metadata" like a year in parentheses, e.g., (1965). It
#     purposefully leaves symbols like hyphens alone, respecting that they
#     might be part of the title's identity. This is the key to making both
#     "B-Movie" and "Boeing, Boeing" work.
#
#   - PASS 2: The "Aggressive" Search (The Fallback Plan)
#     As a backup, the script tries a more aggressive approach, removing ALL
#     symbols and punctuation. This is a safety net to catch torrents with
#     weirdly formatted names, like "Thelma..&..Louise!!!".
#
# THE INTELLIGENCE - ADVANCED SCORING & SORTING:
# After gathering all possible torrents, the script ranks them logically.
#
#   - The "Completeness Bonus": A torrent gets a massive score (+100) if its
#     title contains EVERY word from your search. This is the #1 priority to
#     ensure perfect matches always appear first.
#
#   The "Term Frequency" Score: After the bonus, a finer score is calculated
#     based on how many times each search word appears.
#
# THE "PERFECTION IS IMPOSSIBLE" SAFETY NET:
# We know no system is perfect. After sorting, the script will show you:
#   1. ALL of the top-scoring "perfect" matches.
#   2. A few of the next-best, lower-scoring results as a safety net, just
#      in case the highest-scoring torrent isn't the one you wanted.
#
# ======================================================================================

import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

# --- User-Configurable Settings ---
MAX_PAGES_TO_FETCH = 2          # How many pages of results to fetch PER SEARCH PASS.
MAX_MAGNET_WORKERS = 10         # Number of parallel threads to fetch magnet links.
SAFETY_NET_RESULTS_COUNT = 5    # How many lower-scoring results to show as a safety net.

# --- qBittorrent Environment Imports ---
try:
    from novaprinter import prettyPrinter
    from helpers import retrieve_url
except ImportError:
    pass

# --- Required Library: BeautifulSoup ---
try:
    from bs4 import BeautifulSoup
except ImportError:
    pass

# --- Main Plugin Class ---
class x1337xtube(object):
    url = 'https://1337x.tube'
    name = '1337x Tube (Intelligent)'

    supported_categories = {
        'all': 'all',
        'anime': 'anime',
        'software': 'apps',
        'games': 'games',
        'movies': 'movies',
        'music': 'music',
        'tv': 'tv'
    }

    # --- Helper methods for cleaning, scoring, and searching ---

    def _get_conservative_query(self, query):
        """
        PASS 1: The smart, conservative cleaning method.
        It ONLY removes unambiguous metadata (like a year in parentheses) and
        cleans up extra spaces. It preserves important symbols like hyphens.
        """
        # Remove year in parentheses, e.g., (1965) or [2022], but nothing else.
        query = re.sub(r'[\(\[]\d{4}[\)\]]', '', query)
        # Clean up multiple spaces that might result from the removal.
        query = re.sub(r'\s+', ' ', query)
        return query.strip()

    def _get_aggressive_query(self, query):
        """
        PASS 2: The aggressive, fallback cleaning method.
        It removes ALL symbols, which is useful for titles with junk punctuation.
        """
        query = re.sub(r'[^a-zA-Z0-9\s]', ' ', query)
        query = re.sub(r'\s+', ' ', query)
        return query.strip()

    def _get_keywords_for_scoring(self, query):
        """ Cleans a string to generate a list of keywords for the scoring engine. """
        query = re.sub(r'[^a-zA-Z0-9]', ' ', query)
        query = re.sub(r'\s+', ' ', query)
        # We don't include single-letter words as they are poor keywords.
        return [word for word in query.strip().lower().split() if len(word) > 1]

    def _calculate_advanced_score(self, torrent_title, search_keywords):
        """ Calculates a score based on our two-part system. """
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

    def _execute_search_pass(self, query, cat):
        """ Executes one full search pass: fetches and parses results. """
        if not query: return []
        encoded_query = urllib.parse.quote_plus(query)
        url_template = f"{self.url}/search/?q={encoded_query}&page={{page_num}}"
        pass_torrents = []
        with ThreadPoolExecutor(max_workers=MAX_PAGES_TO_FETCH) as executor:
            futures = [executor.submit(self._fetch_and_parse_page, i, url_template, cat) for i in range(1, MAX_PAGES_TO_FETCH + 1)]
            for future in as_completed(futures):
                pass_torrents.extend(future.result())
        return pass_torrents

    def _fetch_and_parse_page(self, page_num, url_template, cat):
        """ Fetches and parses a single page of torrent results. """
        page_url = url_template.format(page_num=page_num)
        try:
            page_html = retrieve_url(page_url)
            soup = BeautifulSoup(page_html, 'html.parser')
            results_table = soup.find('table', class_='table-list')
            if not results_table: return []
        except Exception: return []

        page_torrents = []
        site_category_value = self.supported_categories.get(cat, 'all')

        for row in results_table.find('tbody').find_all('tr'):
            try:
                icon_tag = row.find('i', class_=re.compile(r'flaticon-'))
                if not icon_tag: continue
                torrent_category = icon_tag['class'][0].replace('flaticon-', '')

                if cat != 'all' and torrent_category != site_category_value:
                    continue

                cols = row.find_all('td')
                name_anchor = cols[0].find_all('a')[-1]
                page_torrents.append({
                    'name': name_anchor.text.strip(),
                    'desc_link': name_anchor['href'],
                    'seeds': cols[1].text.strip(), 'leech': cols[2].text.strip(), 'size': cols[4].text.strip(),
                })
            except (IndexError, AttributeError): continue
        return page_torrents

    def _fetch_magnet_link(self, torrent):
        """ Visits a torrent's detail page to retrieve its magnet link. """
        try:
            details_soup = BeautifulSoup(retrieve_url(torrent['desc_link']), 'html.parser')
            magnet_anchor = details_soup.find('a', id='openPopup')
            if magnet_anchor and 'href' in magnet_anchor.attrs:
                torrent['link'] = magnet_anchor['href']
                return torrent
        except Exception: return None

    def search(self, what, cat='all'):
        """ The main search function called by qBittorrent. """
        if 'BeautifulSoup' not in globals():
            return

        decoded_what = urllib.parse.unquote_plus(what)
        search_keywords = self._get_keywords_for_scoring(decoded_what)

        # --- Multi-Pass Search Execution ---
        pass1_query = self._get_conservative_query(decoded_what)
        pass1_results = self._execute_search_pass(pass1_query, cat)

        pass2_query = self._get_aggressive_query(decoded_what)
        pass2_results = []
        if pass2_query.lower() != pass1_query.lower():
            pass2_results = self._execute_search_pass(pass2_query, cat)

        # --- De-duplication of Results ---
        all_torrents = {t['desc_link']: t for t in pass1_results + pass2_results}
        final_candidates = list(all_torrents.values())
        if not final_candidates:
            return

        # --- Advanced Scoring and Sorting ---
        for torrent in final_candidates:
            torrent['score'] = self._calculate_advanced_score(torrent['name'], search_keywords)
            try: torrent['seeds_int'] = int(torrent['seeds'])
            except ValueError: torrent['seeds_int'] = 0
        final_candidates.sort(key=lambda t: (t['score'], t['seeds_int']), reverse=True)

        # --- Select Torrents to Fetch (Top Tier + Safety Net) ---
        torrents_to_fetch = []
        if final_candidates:
            max_score = final_candidates[0]['score']
            # Add all top-scoring torrents
            top_tier = [t for t in final_candidates if t['score'] == max_score]
            torrents_to_fetch.extend(top_tier)
            # Add a few lower-scoring ones as a safety net
            lower_tier = [t for t in final_candidates if t['score'] < max_score]
            torrents_to_fetch.extend(lower_tier[:SAFETY_NET_RESULTS_COUNT])

        # --- Fetch Magnet Links and Print Results ---
        with ThreadPoolExecutor(max_workers=MAX_MAGNET_WORKERS) as executor:
            futures = [executor.submit(self._fetch_magnet_link, t) for t in torrents_to_fetch]
            for future in as_completed(futures):
                if result := future.result():
                    safe_name = re.sub(r'[\\/*?:"<>|]', '', result['name'])
                    prettyPrinter({'link': result['link'], 'name': safe_name, 'size': result['size'],
                                   'seeds': result['seeds'], 'leech': result['leech'],
                                   'engine_url': self.url, 'desc_link': result['desc_link']})
