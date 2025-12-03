# -*- coding: utf-8 -*-
#
# VERSION: 1.8
# AUTHORS: Me
#
# DESCRIPTION:
#    Search plugin for qBittorrent targeting BitSearch.to.
#    Strictly extracts Desktop magnet links, parses dates to timestamps,
#    and preserves search query spacing.
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

    # 2. How many results with 0 seeders are allowed per search (Default: 5)
    MAX_ZERO_SEEDERS = 5

    # 3. Enable specific query cleaning (Default: True)
    # True = Strip symbols, keep international text, single space between words.
    ENABLE_QUERY_CLEANING = True

    # 4. Fetch Publish Date (Default: True)
    # Set to False to skip date parsing.
    FETCH_DATE = True

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

    def _parse_seeds(self, seed_str):
        """ Helper to convert seed strings (e.g. '1.2k') to int. """
        try:
            s = seed_str.lower().strip()
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

        # Query Cleaning Logic
        if self.ENABLE_QUERY_CLEANING:
            text_without_symbols = re.sub(r'[^\w\s]', ' ', clean_query)
            clean_query = " ".join(text_without_symbols.split())

        search_term = quote_plus(clean_query)
        zero_seeder_count = 0

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

                    # 1. Name & Desc Link
                    title_tag = h3.find('a')
                    if title_tag:
                        item['name'] = title_tag.get_text(strip=True)
                        href = title_tag.get('href')
                        if href:
                            item['desc_link'] = urljoin(self.url, href)

                    # 2. Magnet Link (Desktop container: hidden sm:flex)
                    desktop_div = card.find('div', class_=lambda x: x and 'hidden' in x and 'sm:flex' in x)
                    if desktop_div:
                        magnet_node = desktop_div.find('a', href=re.compile(r'^magnet:'))
                        if magnet_node:
                            item['link'] = html.unescape(magnet_node.get('href'))

                    if 'link' not in item:
                        continue

                    # 3. Size and Date (Located in the Gray Stats Bar)
                    stats_div = card.find('div', class_=lambda x: x and 'text-gray-600' in x)

                    if stats_div:
                        # --- SIZE ---
                        size_icon = stats_div.find('i', class_='fa-download')
                        if size_icon:
                            size_span = size_icon.find_next_sibling('span')
                            if size_span:
                                item['size'] = size_span.get_text(strip=True)

                        # --- DATE (Simplified & Optional) ---
                        if self.FETCH_DATE:
                            date_icon = stats_div.find('i', class_='fa-calendar')
                            if date_icon:
                                date_span = date_icon.find_next_sibling('span')
                                if date_span:
                                    try:
                                        # One-liner conversion: String -> Datetime Object -> Timestamp
                                        dt = datetime.strptime(date_span.get_text(strip=True), '%m/%d/%Y')
                                        item['pub_date'] = int(dt.timestamp())
                                    except ValueError:
                                        pass

                    # 4. Seeds & Leechers
                    seed_cont = card.find('span', class_=lambda x: x and 'text-green-600' in x)
                    if seed_cont:
                        val = seed_cont.find('span', class_='font-medium')
                        if val: item['seeds'] = val.get_text(strip=True)

                    leech_cont = card.find('span', class_=lambda x: x and 'text-red-600' in x)
                    if leech_cont:
                        val = leech_cont.find('span', class_='font-medium')
                        if val: item['leech'] = val.get_text(strip=True)

                    # 5. Zero Seeder Limit Check
                    if self._parse_seeds(item['seeds']) == 0:
                        if zero_seeder_count >= self.MAX_ZERO_SEEDERS:
                            continue
                        zero_seeder_count += 1

                    prettyPrinter(item)

            except Exception:
                continue

    def download_torrent(self, info):
        print(download_file(info))
