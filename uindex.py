# -*- coding: utf-8 -*-
#
# VERSION: 1.6
# AUTHORS: Me
#
# License: GPL v3
# DESCRIPTION:
#    This is a search plugin for qBittorrent that scrapes UIndex.org.
#    It parses the HTML result table to extract magnet links, file sizes,
#    dates (converted to Unix timestamps), and swarm statistics.
#
# REQUIREMENTS:
#    - Python 3.x
#    - BeautifulSoup4 (bs4)
#

import re
import sys
import html
import time
from urllib.parse import quote_plus, urljoin, unquote

# qBittorrent plugin helpers
from helpers import retrieve_url, download_file
from novaprinter import prettyPrinter

# Check for BeautifulSoup dependency
try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Error: BeautifulSoup (bs4) is not installed. Please install it to use this plugin.")


class uindex:
    """
    Search engine class for UIndex.org.
    """

    url = 'https://uindex.org'
    name = 'UIndex'

    # --- Tunables ---
    # How many results to show total
    max_results = 80

    # How many pages to scrape (default 1)
    pages_to_scrape = 1

    # How many results with 0 seeders are allowed before filtering them out (default 5)
    max_zero_seeders = 5

    # Mapping qBittorrent categories to UIndex integer IDs
    supported_categories = {
        'all': '0',
        'movies': '1',
        'tv': '2',
        'games': '3',
        'music': '4',
        'software': '5',
        'anime': '7'
    }

    def _parse_relative_date(self, date_str):
        """
        Parses strings like "7.3 months ago" into a Unix Timestamp.
        """
        try:
            # Current time in epoch seconds
            now = time.time()

            # Extract the numeric value (matches 7, 7.3, etc)
            number_match = re.search(r"([\d\.]+)", date_str)
            if not number_match:
                return -1

            val = float(number_match.group(1))

            # Determine multiplier based on unit
            lower_str = date_str.lower()
            if 'sec' in lower_str:
                seconds = val
            elif 'min' in lower_str:
                seconds = val * 60
            elif 'hour' in lower_str:
                seconds = val * 3600
            elif 'day' in lower_str:
                seconds = val * 86400
            elif 'week' in lower_str:
                seconds = val * 604800
            elif 'month' in lower_str:
                # Approx 30.44 days
                seconds = val * 2629743
            elif 'year' in lower_str:
                # Approx 365.24 days
                seconds = val * 31556926
            else:
                seconds = 0

            # Return integer timestamp
            return int(now - seconds)

        except Exception:
            return -1

    def search(self, query, cat='all'):
        """
        Performs the search operation.
        """

        # 1. Prepare Category ID
        cat_id = self.supported_categories.get(cat, '0')

        # 2. Prepare Query with Advanced Cleaning
        raw_query = unquote(query)
        # Regex: Replace any character that is NOT a letter, number, or whitespace with a space
        clean_string = re.sub(r'[^a-zA-Z0-9\s]', ' ', raw_query)
        # Collapse multiple spaces into one and strip edges
        clean_string = re.sub(r'\s+', ' ', clean_string).strip()
        search_term = quote_plus(clean_string)

        result_count = 0
        zero_seeder_count = 0

        # Loop through pages
        for page in range(1, self.pages_to_scrape + 1):

            # Stop if we hit the global limit
            if result_count >= self.max_results:
                break

            # Construct the search URL with page parameter
            # Assuming standard pagination format &page=X
            target_url = f"{self.url}/search.php?search={search_term}&c={cat_id}&page={page}"

            try:
                # Fetch HTML content
                data = retrieve_url(target_url)

                if not data:
                    break

                soup = BeautifulSoup(data, 'html.parser')

                # 3. Locate Result Rows
                rows = soup.find_all('tr')

                # If no rows found, we probably went past the last page
                if not rows:
                    break

                # Count rows processed on this page to determine if we should continue
                rows_processed_on_page = 0

                for row in rows:
                    # Stop if we hit the limit
                    if result_count >= self.max_results:
                        break

                    # --- Validation ---
                    # Check for seeds span (class='g') to ensure it's a data row
                    seeds_span = row.find('span', class_='g')
                    if not seeds_span:
                        continue

                    rows_processed_on_page += 1

                    # --- Parse Seeds & Zero Seeder Filter ---
                    try:
                        seeds_val = int(seeds_span.get_text(strip=True))
                    except ValueError:
                        seeds_val = 0

                    # Filter Logic:
                    # If torrent has 0 seeds...
                    if seeds_val == 0:
                        # ...and we have reached the limit of allowable 0-seeders...
                        if zero_seeder_count >= self.max_zero_seeders:
                            # ...skip this torrent.
                            continue
                        else:
                            # Otherwise count it and display it
                            zero_seeder_count += 1

                    item = {
                        'engine_url': self.url,
                        'seeds': str(seeds_val)
                    }

                    # --- Parse Name and Description Link ---
                    name_tag = row.find('a', href=re.compile(r'details\.php'))
                    if name_tag:
                        item['name'] = name_tag.get_text(strip=True)
                        item['desc_link'] = urljoin(self.url, name_tag.get('href'))
                    else:
                        continue

                    # --- Parse Date ---
                    # HTML: <div class="sub" style="float:right;font-size:12px">8.8 months ago</div>
                    date_div = row.find('div', class_='sub')
                    if date_div:
                        raw_date = date_div.get_text(strip=True)
                        item['pub_date'] = self._parse_relative_date(raw_date)
                    else:
                        item['pub_date'] = -1

                    # --- Parse Magnet Link ---
                    magnet_node = row.find('a', href=re.compile(r'^magnet:'))
                    if magnet_node:
                        raw_magnet = magnet_node.get('href')
                        item['link'] = html.unescape(raw_magnet)
                    else:
                        continue

                    # --- Parse File Size ---
                    size_td = row.find('td', style=re.compile(r'white-space:nowrap'))
                    if size_td:
                        item['size'] = size_td.get_text(strip=True)
                    else:
                        item['size'] = '-1'

                    # --- Parse Leechers ---
                    leech_span = row.find('span', class_='b')
                    if leech_span:
                        item['leech'] = leech_span.get_text(strip=True)
                    else:
                        item['leech'] = '0'

                    # Send to qBittorrent and increment counter
                    prettyPrinter(item)
                    result_count += 1

                # If we processed very few rows on this page (header only), break pagination
                if rows_processed_on_page == 0:
                    break

            except Exception:
                # If a page fails, try the next one or break? Usually break is safer.
                break

    def download_torrent(self, info):
        """
        Handles the download request.
        """
        print(download_file(info))
