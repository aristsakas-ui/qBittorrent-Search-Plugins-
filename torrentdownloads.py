# -*- coding: utf-8 -*-
#
# VERSION: 1.6
# AUTHORS: Me
#
# License: GPL v3
# DESCRIPTION:
#    Search plugin for TorrentDownloads.pro.
#    It handles category-specific searches using the site's native IDs,
#    cleans search queries to ensure compatibility with the search engine,
#    and parses result rows to extract magnet links, size, and swarm stats.
#    Limits results with 0 seeders to a maximum of 3 to keep lists clean.
#
# REQUIREMENTS:
#    - Python 3.x
#    - BeautifulSoup4 (bs4)
#

import sys
import re
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

class torrentdownloads(object):
    """
    Search engine class for TorrentDownloads.pro.
    """
    url = 'https://www.torrentdownloads.pro'
    name = 'TorrentDownloads'

    # Category Mapping
    # Maps qBittorrent categories to the site's specific integer IDs.
    supported_categories = {
        'all': '0',       # -- Any Category --
        'movies': '4',    # Movies
        'tv': '8',        # TV Shows
        'music': '5',     # Music
        'games': '3',     # Games
        'software': '7',  # Software
        'anime': '1',     # Anime
        'books': '2',     # Books
        'other': '9'      # Other
    }

    def search(self, query, cat='all'):
        """
        Performs the search operation.

        1. Cleans the query (removes special chars, collapses spaces).
        2. Constructs the URL using the specific category ID (s_cat).
        3. Parses the HTML to find valid torrent links and their statistics.
        """

        # --- 1. Query Cleaning ---
        # Decode the query first to handle URL-encoded characters (e.g., %20)
        decoded_query = unquote(query)

        # Replace any character that is NOT a letter or number with a space.
        # This ensures the search engine accepts complex titles (e.g., "Mission: Impossible").
        clean_query = re.sub(r'[^a-zA-Z0-9]', ' ', decoded_query)

        # Collapse multiple consecutive spaces into a single space.
        clean_query = " ".join(clean_query.split())

        # --- 2. URL Construction ---
        # Retrieve the internal category ID, defaulting to '0' (All).
        cat_id = self.supported_categories.get(cat, '0')

        # Construct the target URL using the 's_cat' parameter.
        target_url = f"{self.url}/search/?new=1&s_cat={cat_id}&search={quote_plus(clean_query)}"

        # --- 3. Fetch Data ---
        try:
            data = retrieve_url(target_url)
        except Exception:
            # Silently fail if connection drops
            return

        soup = BeautifulSoup(data, 'html.parser')

        # --- 4. Parse Results ---
        # Strategy: Find all anchor tags pointing to '/torrent/', then look at their parent container
        # to find the associated statistics (seeds, leechers, size).
        potential_links = soup.find_all('a', href=re.compile(r'^/torrent/'))

        seen_urls = set()
        zero_seeder_count = 0

        for a_tag in potential_links:
            try:
                # -- Filters --
                # 1. Ignore comment bubbles (class 'cloud')
                if 'cloud' in a_tag.get('class', []):
                    continue

                # 2. Ignore numeric titles (usually comment counts linked to the page)
                title = a_tag.get_text(strip=True)
                if title.isdigit():
                    continue

                # -- Deduplication --
                href = a_tag.get('href')
                # Remove anchor hashes (e.g., #comments) to ensure uniqueness
                clean_href = href.split('#')[0]
                full_link = urljoin(self.url, clean_href)

                if full_link in seen_urls:
                    continue
                seen_urls.add(full_link)

                # -- Locate Data Row --
                row = a_tag.find_parent('div')
                if not row:
                    continue

                # -- Extract Statistics --
                # Expected HTML layout: [0]HealthImg, [1]Leech, [2]Seeds, [3]Size
                spans = row.find_all('span')
                if len(spans) < 4:
                    continue

                leech = spans[1].get_text(strip=True)
                seeds = spans[2].get_text(strip=True)
                raw_size = spans[3].get_text(strip=True)

                # -- Size Correction --
                # Sometimes the layout shifts. If column [3] doesn't look like a file size
                # (missing 'B' for Byte), check the next column.
                final_size = raw_size
                if "B" not in raw_size and len(spans) > 4:
                    alt_size = spans[4].get_text(strip=True)
                    if "B" in alt_size:
                        final_size = alt_size

                # Clean Non-Breaking Spaces (\xa0) so qBittorrent can parse the size correctly.
                final_size = final_size.replace(u'\xa0', u' ').strip()

                # Verify seed count is numeric to ensure we aren't parsing a header row.
                if not seeds.isdigit():
                    continue

                # -- Zero Seeder Limit --
                # If seeds are 0, check if we have reached the limit of 3.
                if int(seeds) == 0:
                    if zero_seeder_count >= 3:
                        continue
                    zero_seeder_count += 1

                item = {
                    'link': full_link,
                    'name': title,
                    'size': final_size,
                    'seeds': seeds,
                    'leech': leech,
                    'engine_url': self.url,
                    'desc_link': full_link
                }

                prettyPrinter(item)

            except Exception:
                # Skip problematic rows without crashing the search
                continue

    def download_torrent(self, info):
        """
        Handles the download request.
        Since the search result only provides the details page URL,
        this function visits that page to scrape the actual magnet link.
        """
        url = info
        try:
            data = retrieve_url(url)
            soup = BeautifulSoup(data, 'html.parser')

            # Find the link starting with 'magnet:?'
            magnet_link = soup.find('a', href=re.compile(r'^magnet:\?'))
            if magnet_link:
                # Decode HTML entities (e.g. &amp; -> &)
                print(html.unescape(magnet_link['href']) + " " + url)
            else:
                # Fallback to the page URL if magnet is missing
                print(url)
        except Exception:
            print(url)
