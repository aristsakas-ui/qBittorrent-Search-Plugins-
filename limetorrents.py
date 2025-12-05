# This script searches LimeTorrents.si for torrents and returns magnet links.
# It supports searching across all categories and handles result deduplication.
#
# Free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation version 3


# VERSION: 1.8
# Me

import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, unquote

from helpers import retrieve_url
from novaprinter import prettyPrinter

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# --- Filtering Configuration ---
# 1. How many "Dead" torrents (0 Seeds, Low Leechers) to show?
# Set to 0 to hide them completely.
MAX_DEAD_RESULTS = 0

# 2. Threshold for 0-Seed torrents.
# If a torrent has 0 Seeds, it must have at least this many Leechers to be shown.
MIN_LEECHERS_THRESHOLD = 3

# 3. Pagination
MAX_PAGES = 1
# -------------------------------

class limetorrents:
    """Search plugin for LimeTorrents.si torrent search engine"""

    url = "https://limetorrent.si"
    name = "LimeTorrents"
    supported_categories = {
        'all': '',
        'anime': 'anime',
        'software': 'applications',
        'games': 'games',
        'movies': 'movies',
        'music': 'music',
        'tv': 'tv',
        'other': 'other'
    }

    def __init__(self):
        self.seen_urls = set()
        self.seen_hashes = set()

        self.now = datetime.now()
        self.date_parsers = {
            r"yesterday": lambda m: self.now - timedelta(days=1),
            r"last\s+month": lambda m: self.now - timedelta(days=30),
            r"(\d+)\s+years?": lambda m: self.now - timedelta(days=int(m[1]) * 365),
            r"(\d+)\s+months?": lambda m: self.now - timedelta(days=int(m[1]) * 30),
            r"(\d+)\s+days?": lambda m: self.now - timedelta(days=int(m[1])),
            r"(\d+)\s+hours?": lambda m: self.now - timedelta(hours=int(m[1])),
            r"(\d+)\s+minutes?": lambda m: self.now - timedelta(minutes=int(m[1])),
        }

    def parse_date(self, date_text: str) -> str:
        """Convert relative date text to UNIX timestamp"""
        timestamp = -1
        for pattern, calc in self.date_parsers.items():
            m = re.match(pattern, date_text.strip(), re.IGNORECASE)
            if m:
                timestamp = int(calc(m).timestamp())
                break
        return str(timestamp)

    def extract_info_hash(self, torrent_link: str) -> str:
        """Extract info hash from torrent URL for deduplication"""
        hash_match = re.search(r'([a-fA-F0-9]{10,})\.html', torrent_link)
        if hash_match:
            return hash_match.group(1).lower()
        return ""

    def search(self, query: str, cat: str = 'all') -> None:
        """
        Search LimeTorrents for torrents
        Args:
            query: Search term
            cat: Category to search in (default: 'all')
        """
        self.seen_urls.clear()
        self.seen_hashes.clear()

        # Counter for dead results in the current search
        dead_results_count = 0

        query = unquote(query)
        category = self.supported_categories[cat]

        for page in range(1, MAX_PAGES + 1):
            try:
                params = {'q': query}
                if category:
                    params['catname'] = category

                search_url = f"{self.url}/search?{urlencode(params)}"
                if page > 1:
                    search_url += f"&page={page}"

                html = retrieve_url(search_url)

                if not HAS_BS4:
                    continue

                soup = BeautifulSoup(html, 'html.parser')
                rows = soup.find_all('tr', attrs={'bgcolor': ['#F4F4F4', '#FFFFFF', '#f4f4f4', '#ffffff']})

                if not rows:
                    break

                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) < 4:
                        continue

                    item = {"engine_url": self.url}

                    # Find torrent page link
                    name_cell = cells[0]
                    link_tags = name_cell.find_all('a', href=True)
                    torrent_link = None

                    for link_tag in link_tags:
                        link = link_tag['href']
                        if link and (link.endswith('.html') or '/torrent/' in link):
                            if link.startswith('/'):
                                link = self.url + link
                            if link not in self.seen_urls:
                                torrent_link = link
                                break

                    if not torrent_link or torrent_link in self.seen_urls:
                        continue

                    # Deduplication check
                    info_hash = self.extract_info_hash(torrent_link)
                    if info_hash and info_hash in self.seen_hashes:
                        continue

                    # Extract name and clean it
                    name_text = name_cell.get_text(strip=True)
                    for unwanted in ['Download', 'Direct Download', 'Torrent', 'Magnet Download']:
                        name_text = name_text.replace(unwanted, '')
                    item["name"] = name_text.strip()

                    # Extract metadata
                    if len(cells) > 1:
                        date_text = cells[1].get_text(strip=True)
                        item["pub_date"] = self.parse_date(date_text)

                    if len(cells) > 2:
                        size_text = cells[2].get_text(strip=True).replace(',', '')
                        item["size"] = size_text

                    # --- Seeds/Leech Extraction & Filtering Logic ---
                    seeds_int = 0
                    leech_int = 0

                    if len(cells) > 3:
                        seeds_text = cells[3].get_text(strip=True).replace(',', '')
                        item["seeds"] = seeds_text
                        try:
                            seeds_int = int(seeds_text)
                        except ValueError:
                            seeds_int = 0

                    if len(cells) > 4:
                        leech_text = cells[4].get_text(strip=True).replace(',', '')
                        item["leech"] = leech_text
                        try:
                            leech_int = int(leech_text)
                        except ValueError:
                            leech_int = 0

                    # Check if torrent is "Dead"
                    is_dead = False
                    # Logic: If 0 seeds AND leechers < 3, it is dead.
                    # Otherwise (Seeds > 0 OR Leechers >= 3), it is active.
                    if seeds_int == 0:
                        if leech_int < MIN_LEECHERS_THRESHOLD:
                            is_dead = True

                    # Apply Filter limits
                    if is_dead:
                        if dead_results_count >= MAX_DEAD_RESULTS:
                            continue # Skip showing this dead result
                        dead_results_count += 1
                    # -----------------------------------------------

                    self.seen_urls.add(torrent_link)
                    if info_hash:
                        self.seen_hashes.add(info_hash)

                    item["link"] = torrent_link
                    item["desc_link"] = torrent_link

                    if item["name"]:
                        prettyPrinter(item)

                # Check if next page exists using the button ID provided
                if page < MAX_PAGES:
                    next_button = soup.find(id="loadMorep")
                    if not next_button:
                        break  # No more pages available

            except Exception:
                continue

    def download_torrent(self, info: str) -> None:
        """
        Download torrent by extracting magnet link from torrent page
        Args:
            info: URL of the torrent detail page
        """
        try:
            if 'limetorrent.net' in info:
                info = info.replace('limetorrent.net', 'limetorrent.si')

            info_page = retrieve_url(info)

            if not HAS_BS4:
                raise ValueError('BeautifulSoup not available')

            soup = BeautifulSoup(info_page, 'html.parser')

            # Extract magnet link from page
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                if href.startswith('magnet:'):
                    magnet_url = href.replace('&amp;', '&').strip()
                    # Output format required by qBittorrent
                    print(f"{magnet_url} {info}")
                    return

            raise ValueError('No magnet link found')

        except Exception as e:
            raise ValueError(f'Download failed: {str(e)}')
