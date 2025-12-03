# -*- coding: utf-8 -*-
#
# VERSION: 1.8
# AUTHORS: Me
#
# DESCRIPTION:
#    This is a search plugin for qBittorrent that scrapes SolidTorrents.to.
#    It parses the HTML result cards to extract magnet links, file sizes,
#    dates, and swarm statistics.
#
# REQUIREMENTS:
#    - Python 3.x
#    - BeautifulSoup4 (bs4)
#

import re
import sys
import html
import time
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


class solidtorrents:
    """
    Search engine class for SolidTorrents.to.
    """

    url = 'https://solidtorrents.to'
    name = 'SolidTorrents'

    # --- CONFIGURATION ---
    # 1. How many pages to scrape (Default: 2)
    MAX_PAGES = 2

    # 2. Maximum number of results with 0 seeders to display (Default: 5)
    # Set to -1 to show all, or 0 to show none.
    MAX_ZERO_SEEDS = 5

    # 3. Clean Search Query (Default: True)
    # Replaces symbols (:, -, ™) with spaces and collapses multiple spaces.
    # Keeps international letters (Amélie) intact.
    CLEAN_QUERY = True

    # 4. Fetch Publish Date (Default: True)
    # Parses the date from the result card. Set to False if you want to save processing time (negligible).
    FETCH_DATE = True
    # ---------------------

    # Mapping qBittorrent categories to SolidTorrents integer IDs
    supported_categories = {
        'all': '1',       # Default/All
        'movies': '2',
        'tv': '3',
        'anime': '4',
        'software': '5',
        'games': '6',
        'music': '7'
    }

    def search(self, query, cat='all'):
        """
        Performs the search operation.
        """

        # 1. Prepare Category ID
        cat_id = self.supported_categories.get(cat, '1')

        # 2. Prepare Query
        # Decode first (e.g., "die%20hard" -> "die hard")
        raw_query = unquote(query)

        if self.CLEAN_QUERY:
            # Regex Explanation:
            # [^\w\s] : Match any character that is NOT a word char (letter/number/_) AND NOT a whitespace.
            # This strips symbols like ™, :, -, !, etc. but KEEPS unicode letters (Amélie).
            # re.sub(r'\s+', ' ') : Collapses multiple spaces into one.
            clean_query = re.sub(r'[^\w\s]', ' ', raw_query)
            clean_query = re.sub(r'\s+', ' ', clean_query).strip()
        else:
            clean_query = raw_query

        # Encode for URL (e.g. "Amélie" -> "Am%C3%A9lie", "NieR Automata" -> "NieR+Automata")
        search_term = quote_plus(clean_query)

        # Counter for zero-seeder results found so far (across all pages)
        zero_seeds_found_count = 0

        # Loop through pages based on MAX_PAGES configuration
        for page in range(1, self.MAX_PAGES + 1):
            try:
                # Construct the search URL
                target_url = f"{self.url}/search?q={search_term}&category={cat_id}&page={page}"

                # Fetch HTML content
                data = retrieve_url(target_url)

                if not data:
                    continue

                soup = BeautifulSoup(data, 'html.parser')

                # Check if the page indicates no results
                if "No torrents found" in str(soup):
                    break

                # 3. Locate Result Cards
                candidate_divs = soup.find_all('div', class_=lambda x: x and 'bg-white' in x and 'shadow-sm' in x)

                for card in candidate_divs:
                    # --- Parse Name and Description Link ---
                    h3 = card.find('h3')
                    if not h3:
                        continue

                    a_tag = h3.find('a')
                    if not a_tag:
                        continue

                    name = a_tag.get_text(strip=True)
                    item = {
                        'name': name,
                        'engine_url': self.url
                    }

                    # Construct full description URL
                    desc_href = a_tag.get('href')
                    if desc_href:
                        item['desc_link'] = urljoin(self.url, desc_href)

                    # --- Parse Magnet Link ---
                    magnet_node = card.find('a', href=re.compile(r'^magnet:'))
                    if magnet_node:
                        raw_magnet = magnet_node.get('href')
                        item['link'] = html.unescape(raw_magnet)
                    else:
                        continue

                    # --- Parse Meta Data ---
                    item['size'] = '-1'

                    # Size
                    icon_dl = card.find('i', class_='fa-download')
                    if icon_dl:
                        size_span = icon_dl.find_next_sibling('span')
                        if size_span:
                            item['size'] = size_span.get_text(strip=True)

                    # Date (Optional)
                    item['pub_date'] = -1
                    if self.FETCH_DATE:
                        # Find calendar icon using lambda for partial match (solid vs reg style)
                        icon_cal = card.find('i', class_=lambda c: c and 'calendar' in c)
                        if icon_cal:
                            date_span = icon_cal.find_next_sibling('span')
                            if date_span:
                                date_str = date_span.get_text(strip=True)
                                # Convert string date (e.g. 6/19/2023) to Unix Timestamp
                                try:
                                    dt_obj = datetime.strptime(date_str, '%m/%d/%Y')
                                    item['pub_date'] = int(dt_obj.timestamp())
                                except ValueError:
                                    pass

                    # --- Parse Seeds and Leechers ---
                    item['seeds'] = '0'
                    item['leech'] = '0'

                    # Seeds: Located in green text span
                    seeds_div = card.find('span', class_=lambda x: x and 'text-green-600' in x)
                    if seeds_div:
                        s_val = seeds_div.find('span', class_='font-medium')
                        if s_val:
                            item['seeds'] = s_val.get_text(strip=True)

                    # Leechers: Located in red text span
                    leech_div = card.find('span', class_=lambda x: x and 'text-red-600' in x)
                    if leech_div:
                        l_val = leech_div.find('span', class_='font-medium')
                        if l_val:
                            item['leech'] = l_val.get_text(strip=True)

                    # --- Zero Seeder Logic ---
                    try:
                        seed_count_int = int(item['seeds'].replace(',', ''))
                    except ValueError:
                        seed_count_int = 0

                    if seed_count_int == 0:
                        # If we have reached the limit for 0-seed results, skip this one
                        if self.MAX_ZERO_SEEDS != -1 and zero_seeds_found_count >= self.MAX_ZERO_SEEDS:
                            continue
                        zero_seeds_found_count += 1

                    # Send the extracted item to qBittorrent
                    prettyPrinter(item)

            except Exception:
                continue

    def download_torrent(self, info):
        """
        Handles the download request.
        """
        print(download_file(info))
