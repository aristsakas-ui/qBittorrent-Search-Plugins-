#
#
# Free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation version 3#
# VERSION: 1.5
# AUTHORS: Me
#
#
# DESCRIPTION:
#    Search plugin for qBittorrent targeting BitSearch.to.
#    Strictly extracts Desktop magnet links and preserves search query spacing.
#
# REQUIREMENTS:
#    - Python 3.x
#    - BeautifulSoup4 (bs4)
#

import re
import sys
import html
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
    # How many pages to scrape (Default: 2)
    PAGES_TO_SCRAPE = 2
    # ---------------------

    # Mapping qBittorrent categories to BitSearch integer IDs
    supported_categories = {
        'all': '',        # Default (All Categories)
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
        cat_id = self.supported_categories.get(cat, '')

        # 2. Prepare Query
        # User Requirement: Preserve input spaces and encode them as '+'.
        clean_query = unquote(query)
        search_term = quote_plus(clean_query)

        # Loop through pages based on the configuration variable
        for page in range(1, self.PAGES_TO_SCRAPE + 1):
            try:
                # Construct URL: https://bitsearch.to/search?q=...&category=...&page=X
                target_url = f"{self.url}/search?q={search_term}&category={cat_id}&page={page}"

                # Fetch HTML content
                data = retrieve_url(target_url)

                if not data:
                    continue

                soup = BeautifulSoup(data, 'html.parser')

                # 3. Locate Result Cards
                # Target: <div class="bg-white rounded-lg shadow-sm border ...">
                candidate_divs = soup.find_all('div', class_=lambda x: x and 'bg-white' in x and 'shadow-sm' in x and 'border' in x)

                # If no results found on this page, stop scraping
                if not candidate_divs:
                    break

                for card in candidate_divs:
                    item = {
                        'engine_url': self.url,
                        'seeds': '-1',
                        'leech': '-1',
                        'size': '-1'
                    }

                    # --- A. Parse Title and Description Link ---
                    h3 = card.find('h3')
                    if not h3:
                        continue

                    title_tag = h3.find('a')
                    if not title_tag:
                        continue

                    item['name'] = title_tag.get_text(strip=True)

                    href = title_tag.get('href')
                    if href:
                        item['desc_link'] = urljoin(self.url, href)

                    # --- B. Parse Magnet Link (DESKTOP ONLY) ---
                    # User Requirement: Get link from "hidden sm:flex" container (Desktop).
                    desktop_div = card.find('div', class_=lambda x: x and 'hidden' in x and 'sm:flex' in x)

                    magnet_found = False
                    if desktop_div:
                        magnet_node = desktop_div.find('a', href=re.compile(r'^magnet:'))
                        if magnet_node:
                            item['link'] = html.unescape(magnet_node.get('href'))
                            magnet_found = True

                    if not magnet_found:
                        continue

                    # --- C. Parse Size ---
                    # Logic: Located in the 'Category and Stats' section (text-gray-600).
                    stats_div = card.find('div', class_=lambda x: x and 'text-gray-600' in x)
                    if stats_div:
                        icon = stats_div.find('i', class_=re.compile(r'fa-download'))
                        if icon:
                            size_span = icon.find_next_sibling('span')
                            if size_span:
                                item['size'] = size_span.get_text(strip=True)

                    # --- D. Parse Seeds & Leechers ---
                    # Seeds: text-green-600 -> font-medium
                    seed_span = card.find('span', class_=lambda x: x and 'text-green-600' in x)
                    if seed_span:
                        val_span = seed_span.find('span', class_='font-medium')
                        if val_span:
                            item['seeds'] = val_span.get_text(strip=True)

                    # Leechers: text-red-600 -> font-medium
                    leech_span = card.find('span', class_=lambda x: x and 'text-red-600' in x)
                    if leech_span:
                        val_span = leech_span.find('span', class_='font-medium')
                        if val_span:
                            item['leech'] = val_span.get_text(strip=True)

                    # Send to qBittorrent
                    prettyPrinter(item)

            except Exception:
                # Proceed to next page or exit cleanly on error
                continue

    def download_torrent(self, info):
        """
        Required by API. Handles download request.
        """
        print(download_file(info))
