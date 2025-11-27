# -*- coding: utf-8 -*-
#
# VERSION: 1.3
# AUTHORS: Me
#
# DESCRIPTION:
#    This is a search plugin for qBittorrent that scrapes SolidTorrents.to.
#    It parses the HTML result cards to extract magnet links, file sizes,
#    and swarm statistics (seeds/leechers).
#
# REQUIREMENTS:
#    - Python 3.x
#    - BeautifulSoup4 (bs4)
#
# INSTALLATION:
#    Place this file in the qBittorrent search plugins directory:
#    - Windows: %localappdata%\qBittorrent\nova3\engines\
#    - Linux: ~/.local/share/data/qBittorrent/nova3/engines/
#    - macOS: ~/Library/Application Support/qBittorrent/nova3/engines/
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


class solidtorrents:
    """
    Search engine class for SolidTorrents.to.
    """

    url = 'https://solidtorrents.to'
    name = 'SolidTorrents'

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

        Args:
            query (str): The search term entered by the user.
            cat (str): The category selected by the user (default: 'all').
        """

        # 1. Prepare Category ID
        cat_id = self.supported_categories.get(cat, '1')

        # 2. Prepare Query
        # Decode first to handle cases where qBittorrent passes encoded strings (e.g., "die%20hard"),
        # then re-encode using quote_plus to ensure spaces become '+' as required by the site.
        clean_query = unquote(query)
        search_term = quote_plus(clean_query)

        # Loop through the first 2 pages to get results
        for page in range(1, 3):
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
                # The site uses Tailwind CSS generic classes. We look for 'div' elements that look like cards.
                # Attributes: background white (bg-white) and small shadow (shadow-sm).
                candidate_divs = soup.find_all('div', class_=lambda x: x and 'bg-white' in x and 'shadow-sm' in x)

                for card in candidate_divs:
                    # --- Parse Name and Description Link ---
                    # We verify the card is a torrent result by checking for an H3 tag containing a link.
                    # This filters out UI headers which share similar CSS classes.
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
                    # Locate the anchor tag with an href starting with "magnet:".
                    # IMPORTANT: The site HTML encodes magnet params (e.g., "&amp;" instead of "&").
                    # We must unescape/decode this or the link will be invalid.
                    magnet_node = card.find('a', href=re.compile(r'^magnet:'))
                    if magnet_node:
                        raw_magnet = magnet_node.get('href')
                        item['link'] = html.unescape(raw_magnet)
                    else:
                        # Skip this result if no magnet link is available
                        continue

                    # --- Parse File Size ---
                    # Logic: Find the 'text-gray-600' div (meta row), look for the download icon (fa-download),
                    # and get the text from the sibling span.
                    item['size'] = '-1' # Default fallback
                    meta_div = card.find('div', class_=lambda x: x and 'text-gray-600' in x)
                    if meta_div:
                        icon = meta_div.find('i', class_='fa-download')
                        if icon:
                            size_span = icon.find_next_sibling('span')
                            if size_span:
                                item['size'] = size_span.get_text(strip=True)

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

                    # Send the extracted item to qBittorrent
                    prettyPrinter(item)

            except Exception:
                # If an error occurs on a specific page, skip to the next
                continue

    def download_torrent(self, info):
        """
        Handles the download request.
        Since 'link' (magnet) is populated in search(), this is largely a fallback.
        """
        print(download_file(info))
