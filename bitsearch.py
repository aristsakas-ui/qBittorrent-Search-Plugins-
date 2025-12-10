# -*- coding: utf-8 -*-
#
# VERSION: 2.0
# AUTHORS: Me
#
# DESCRIPTION:
#    Search plugin for qBittorrent targeting BitSearch.to.
#    - Strict "Word Boundary" matching (e.g., "Alien" matches "Alien 1979", but not "Aliens").
#    - Advanced filtering for dead torrents vs high-leech 0-seeder torrents.
#    - Always extracts dates.
#
# REQUIREMENTS:
#    - Python 3.x
#    - BeautifulSoup4 (bs4)
#

import re
import sys
import html
from datetime import datetime
from urllib.parse import quote_plus, urljoin, unquote

# qBittorrent plugin helpers
from helpers import retrieve_url, download_file
from novaprinter import prettyPrinter

# Check for BeautifulSoup dependency
try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Error: BeautifulSoup (bs4) is not installed. Please install it to use this plugin.")


class bitsearch:
    """
    Search engine class for BitSearch.to
    """

    url = 'https://bitsearch.to'
    name = 'BitSearch'

    # --- CONFIGURATION ---

    # 1. How many pages to scrape (Default: 2)
    PAGES_TO_SCRAPE = 2

    # 2. Query Cleaning (Default: True)
    # Replaces special symbols with spaces before searching to ensure better matching.
    ENABLE_QUERY_CLEANING = True

    # --- Filtering Configuration ---

    # 3. How many "Dead" torrents (0 Seeds, Low Leechers) to show?
    # Set to 0 to hide them completely.
    MAX_DEAD_RESULTS = 0

    # 4. Threshold for 0-Seed torrents.
    # If a torrent has 0 Seeds, it must have at least this many Leechers to be shown
    # (or it counts towards the MAX_DEAD_RESULTS limit).
    MIN_LEECHERS_THRESHOLD = 3

    # ---------------------

    supported_categories = {
        'all': '',
        'movies': '2',
        'tv': '3',
        'anime': '4',
        'software': '5',
        'games': '6',
        'music': '7'
    }

    def _parse_num(self, num_str):
        """ Helper to convert seed/leech strings (e.g. '1.2k') to int. """
        try:
            s = str(num_str).lower().strip()
            if 'k' in s:
                num = float(re.sub(r'[^\d.]', '', s))
                return int(num * 1000)
            return int(re.sub(r'[^\d]', '', s))
        except:
            return 0

    def search(self, query, cat='all'):
        """ Performs the search operation. """

        cat_id = self.supported_categories.get(cat, '')
        clean_query = unquote(query)

        # 1. Clean the query for the URL and for the Regex generation
        if self.ENABLE_QUERY_CLEANING:
            text_without_symbols = re.sub(r'[^\w\s]', ' ', clean_query)
            clean_query = " ".join(text_without_symbols.split())

        search_term = quote_plus(clean_query)

        # Counter for dead results found so far
        dead_results_count = 0

        for page in range(1, self.PAGES_TO_SCRAPE + 1):
            try:
                target_url = f"{self.url}/search?q={search_term}&category={cat_id}&page={page}"
                data = retrieve_url(target_url)

                if not data:
                    continue

                soup = BeautifulSoup(data, 'html.parser')

                # Find result cards
                candidate_divs = soup.find_all('div', class_=lambda x: x and 'bg-white' in x and 'shadow-sm' in x and 'border' in x)

                if not candidate_divs:
                    break

                for card in candidate_divs:
                    # Basic validation: must have a Title (h3)
                    h3 = card.find('h3')
                    if not h3:
                        continue

                    item = {
                        'engine_url': self.url,
                        'seeds': '-1',
                        'leech': '-1',
                        'size': '-1',
                        'pub_date': -1
                    }

                    # --- NAME EXTRACTION ---
                    title_tag = h3.find('a')
                    if title_tag:
                        item['name'] = title_tag.get_text(strip=True)
                        href = title_tag.get('href')
                        if href:
                            item['desc_link'] = urljoin(self.url, href)

                    if 'name' not in item:
                        continue

                    # --- MATCHING LOGIC (Word Boundary) ---
                    # 1. Normalize the result title: replace dots, underscores, dashes with spaces.
                    #    e.g. "Die.Hard.1988" becomes "Die Hard 1988"
                    normalized_name = re.sub(r'[._\-]', ' ', item['name'])

                    # 2. Build Regex: \b means "Word Boundary".
                    #    Matches the query only if it stands alone or is surrounded by spaces/start/end.
                    #    "alien" matches "alien 1979", but fails on "aliens".
                    pattern = r'\b{}\b'.format(re.escape(clean_query))

                    # 3. Check match
                    if not re.search(pattern, normalized_name, re.IGNORECASE):
                        continue
                    # --------------------------------------

                    # --- MAGNET LINK ---
                    desktop_div = card.find('div', class_=lambda x: x and 'hidden' in x and 'sm:flex' in x)
                    if desktop_div:
                        magnet_node = desktop_div.find('a', href=re.compile(r'^magnet:'))
                        if magnet_node:
                            item['link'] = html.unescape(magnet_node.get('href'))

                    if 'link' not in item:
                        continue

                    # --- SIZE & DATE ---
                    stats_div = card.find('div', class_=lambda x: x and 'text-gray-600' in x)
                    if stats_div:
                        # Size
                        size_icon = stats_div.find('i', class_='fa-download')
                        if size_icon:
                            size_span = size_icon.find_next_sibling('span')
                            if size_span:
                                item['size'] = size_span.get_text(strip=True)

                        # Date (Always fetch)
                        date_icon = stats_div.find('i', class_='fa-calendar')
                        if date_icon:
                            date_span = date_icon.find_next_sibling('span')
                            if date_span:
                                try:
                                    dt = datetime.strptime(date_span.get_text(strip=True), '%m/%d/%Y')
                                    item['pub_date'] = int(dt.timestamp())
                                except ValueError:
                                    pass

                    # --- SEEDS & LEECHERS ---
                    seed_cont = card.find('span', class_=lambda x: x and 'text-green-600' in x)
                    if seed_cont:
                        val = seed_cont.find('span', class_='font-medium')
                        if val: item['seeds'] = val.get_text(strip=True)

                    leech_cont = card.find('span', class_=lambda x: x and 'text-red-600' in x)
                    if leech_cont:
                        val = leech_cont.find('span', class_='font-medium')
                        if val: item['leech'] = val.get_text(strip=True)

                    # --- DEAD TORRENT FILTERING LOGIC ---

                    # Convert to integers for logic check
                    seeds_int = self._parse_num(item.get('seeds', '0'))
                    leech_int = self._parse_num(item.get('leech', '0'))

                    is_dead = False

                    # Definition of dead: 0 seeds AND low leechers
                    if seeds_int == 0:
                        if leech_int < self.MIN_LEECHERS_THRESHOLD:
                            is_dead = True

                    # If it is considered dead, check if we have room to show it
                    if is_dead:
                        if dead_results_count >= self.MAX_DEAD_RESULTS:
                            continue # Skip this result
                        dead_results_count += 1

                    # ------------------------------------

                    prettyPrinter(item)

            except Exception:
                continue

    def download_torrent(self, info):
        print(download_file(info))
