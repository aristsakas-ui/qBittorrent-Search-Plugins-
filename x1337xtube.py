# VERSION: 1.1
# This script is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License

"""
1337x Torrent Search Engine Plugin for 1337x.tube
"""

from __future__ import print_function
import re
import urllib.parse
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
SAFETY_NET_RESULTS_COUNT = 5

class x1337xtube(object):
    url = LEETX_DOMAIN
    name = "1337x Tube (Intelligent 1.1)"
    supported_categories = { 'all': 'All', 'movies': 'Movies', 'tv': 'TV', 'music': 'Music', 'games': 'Games', 'anime': 'Anime', 'software': 'Apps' }

    def __init__(self):
        self.search_term = ""
        self.search_url = ""

    def _get_search_words(self, query):
        """Normalize and clean search query into word list for matching"""
        query = query.replace('&', ' and ')
        query = re.sub(r'[^a-zA-Z0-9\s]', ' ', query)
        query = re.sub(r'\s+', ' ', query).strip().lower()
        return query.split()

    def _calculate_advanced_score(self, torrent_title, search_words):
        """Score torrents based on exact phrase match position in title"""
        cleaned_title_words = self._get_search_words(torrent_title)

        try:
            for i in range(len(cleaned_title_words) - len(search_words) + 1):
                if cleaned_title_words[i : i + len(search_words)] == search_words:
                    if i == 0:
                        return 800
                    else:
                        return 600
        except (ValueError, IndexError):
            return 0

        return 0

    def _filter_relevant_results(self, results):
        """Filter and select torrents including safety net results"""
        if not results:
            return []

        results.sort(key=lambda t: (t['score'], t['seeds_int']), reverse=True)

        max_score = results[0]['score']
        top_tier = [t for t in results if t['score'] == max_score]
        lower_tier = [t for t in results if t['score'] < max_score]
        safety_net = lower_tier[:SAFETY_NET_RESULTS_COUNT]

        return top_tier + safety_net

    def _build_search_url(self, query, cat, page=1):
        """Construct the search URL for 1337x.tube"""
        encoded_query = quote_plus(query)
        return f"{self.url}/search/?q={encoded_query}&page={page}"

    def _fetch_magnet_link(self, desc_link):
        """Fetch magnet link from individual torrent description page"""
        try:
            if desc_link.startswith('/'):
                desc_link = self.url + desc_link

            page_html = retrieve_url(desc_link)
            soup = BeautifulSoup(page_html, 'html.parser')

            magnet_link = soup.find('a', href=re.compile(r'^magnet:'))
            if not magnet_link:
                magnet_link = soup.find('a', id='openPopup')

            if magnet_link and magnet_link.get('href'):
                return magnet_link['href']
        except Exception:
            pass
        return None

    def _fetch_and_parse_page(self, page_num, search_url_template, cat):
        """Fetch and parse a single search results page for 1337x.tube"""
        page_url = search_url_template.format(page_num=page_num)
        try:
            page_html = retrieve_url(page_url)
            soup = BeautifulSoup(page_html, 'html.parser')
            table = soup.find('table', class_='table-list')
            if not table:
                return []
        except Exception:
            return []

        page_torrents = []
        rows = table.find_all('tr')[1:] if table.find('tr') else []

        for row in rows:
            try:
                result = {'engine_url': self.url, 'leech': '0', 'leeches': '0'}

                name_links = row.find_all('a', href=re.compile(r'/torrent/'))
                if not name_links:
                    continue

                name_link = name_links[-1]
                result['name'] = name_link.get_text(strip=True)

                desc_link = name_link['href']
                if desc_link.startswith('/'):
                    desc_link = self.url + desc_link
                result['desc_link'] = desc_link
                result['link'] = desc_link

                cells = row.find_all('td')
                if len(cells) >= 3:
                    result['seeds'] = cells[1].get_text(strip=True) or '0'
                    result['leeches'] = result['leech'] = cells[2].get_text(strip=True) or '0'

                if len(cells) >= 5:
                    size_cell = cells[4]
                    if size_cell:
                        result['size'] = size_cell.get_text(strip=True)

                if not result.get('size'):
                    result['size'] = 'Unknown'

                if result.get('name') and result.get('seeds'):
                    page_torrents.append(result)
            except Exception:
                continue

        return page_torrents

    def _deduplicate_results(self, results):
        """Remove duplicate torrents based on exact name matching"""
        seen_names = set()
        unique_results = []

        for result in results:
            if result['name'] not in seen_names:
                unique_results.append(result)
                seen_names.add(result['name'])

        return unique_results

    def download_torrent(self, info):
        """Handle torrent download"""
        if info.startswith('magnet:'):
            print(download_file(info))
        else:
            print('')

    def search(self, what, cat='all'):
        """Main search function"""
        if 'BeautifulSoup' not in globals():
            return

        self.search_term = unquote_plus(what)
        search_words = self._get_search_words(self.search_term)
        self.search_url = self._build_search_url(self.search_term, cat, 1)

        # Step 1: Fetch search results
        all_torrents = []
        url_template = self._build_search_url(self.search_term, cat, "{page_num}")

        with ThreadPoolExecutor(max_workers=MAX_PAGES_TO_FETCH) as executor:
            futures = [executor.submit(self._fetch_and_parse_page, i, url_template, cat)
                      for i in range(1, MAX_PAGES_TO_FETCH + 1)]
            for future in as_completed(futures):
                all_torrents.extend(future.result())

        # Step 2: Remove duplicates
        unique_torrents = self._deduplicate_results(all_torrents)

        if not unique_torrents:
            return

        # Step 3: Fetch magnet links
        with ThreadPoolExecutor(max_workers=MAX_MAGNET_WORKERS) as executor:
            future_to_torrent = {
                executor.submit(self._fetch_magnet_link, torrent['desc_link']): torrent
                for torrent in unique_torrents
            }

            for future in as_completed(future_to_torrent):
                torrent = future_to_torrent[future]
                try:
                    magnet_link = future.result()
                    if magnet_link:
                        torrent['link'] = magnet_link
                except Exception:
                    pass

        # Step 4: Score torrents
        for torrent in unique_torrents:
            torrent['score'] = self._calculate_advanced_score(torrent['name'], search_words)
            try:
                torrent['seeds_int'] = int(torrent['seeds'].replace(',', ''))
            except (ValueError, KeyError):
                torrent['seeds_int'] = 0

        # Step 5: Filter with safety net
        relevant_torrents = self._filter_relevant_results(unique_torrents)

        if not relevant_torrents:
            return

        # Step 6: Output results
        for result in relevant_torrents:
            prettyPrinter({
                'link': result['link'],
                'name': result['name'],
                'size': result.get('size', ''),
                'seeds': result.get('seeds', '0'),
                'leech': result.get('leech', '0'),
                'engine_url': self.url,
                'desc_link': result.get('desc_link', '')
            })
