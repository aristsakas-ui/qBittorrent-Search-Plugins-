# VERSION: 2.2
# AUTHORS: mauricci (with intelligent search features)
# Me

import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

try:
    from helpers import retrieve_url
    from novaprinter import prettyPrinter
except ImportError:
    pass

class torrentproject:
    url = 'https://torrentproject.cc'
    name = 'TorrentProject (Intelligent)'
    supported_categories = {'all': '0'}

    # Search settings
    MAX_PAGES_TO_FETCH = 3
    MAX_MAGNET_WORKERS = 10
    SAFETY_NET_RESULTS_COUNT = 5

    def _clean_conservative_query(self, query):
        """Remove unambiguous metadata from query."""
        query = re.sub(r'[\(\[]\d{4}[\)\]]', '', query)
        query = re.sub(r'\s+', ' ', query)
        return query.strip()

    def _clean_aggressive_query(self, query):
        """Remove all symbols from query."""
        query = re.sub(r'[^a-zA-Z0-9\s]', ' ', query)
        query = re.sub(r'\s+', ' ', query)
        return query.strip()

    def _get_scoring_keywords(self, query):
        """Extract keywords for scoring."""
        query = re.sub(r'[^a-zA-Z0-9]', ' ', query)
        query = re.sub(r'\s+', ' ', query)
        return [word for word in query.strip().lower().split() if len(word) > 1]

    def _calculate_score(self, torrent_title, search_keywords):
        """Calculate relevance score for torrent title."""
        title_lower = torrent_title.lower()
        title_keywords = self._get_scoring_keywords(title_lower)
        title_word_counts = Counter(title_keywords)
        search_word_counts = Counter(search_keywords)
        unique_search_words = set(search_keywords)

        bonus_score = 100 if unique_search_words and all(word in title_word_counts for word in unique_search_words) else 0
        base_score = sum(min(search_word_counts[word], title_word_counts.get(word, 0)) for word in search_word_counts)

        return bonus_score + base_score

    def _fetch_magnet_link(self, torrent):
        """Fetch magnet link for a torrent."""
        try:
            html = retrieve_url(torrent['desc_link'])
            magnet_match = re.search(r'href=["\'](magnet:\?[^"\']+)["\']', html, re.IGNORECASE)
            if magnet_match:
                magnet = unquote(magnet_match.group(1))
                torrent['link'] = magnet
                return torrent
        except Exception as e:
            print(f"DEBUG: Error fetching magnet: {e}", file=sys.stderr)
        return None

    class MyHTMLParser(HTMLParser):
        """Parse HTML to extract torrent data."""
        def __init__(self, url):
            HTMLParser.__init__(self)
            self.url = url
            self.insideResults = False
            self.insideDataDiv = False
            self.pageComplete = False
            self.spanCount = -1
            # Field positions
            self.infoMap = {
                "name": 0,
                "torrLink": 0,
                "seeds": 2,      # ORIGINAL: seeds at position 2
                "leech": 3,      # ORIGINAL: leech at position 3
                "pub_date": 4,   # ORIGINAL: date at position 4
                "size": 5,       # ORIGINAL: size at position 5
            }
            self.fullResData = []
            self.pageRes = []
            self.singleResData = self.get_single_data()

        def get_single_data(self):
            return {
                'name': '-1',
                'seeds': '-1',
                'leech': '-1',
                'size': '-1',
                'link': '-1',
                'desc_link': '-1',
                'engine_url': self.url,
                'pub_date': '-1',
            }

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)

            # Handle navigation detection
            if tag == 'div' and 'nav' in attributes.get('id', ''):
                self.pageComplete = True

            # Start of results section
            if tag == 'div' and attributes.get('id', '') == 'similarfiles':
                self.insideResults = True

            # Individual torrent divs
            if tag == 'div' and self.insideResults and 'gac_bb' not in attributes.get('class', ''):
                self.insideDataDiv = True

            # Count spans within torrent divs
            elif tag == 'span' and self.insideDataDiv and 'verified' != attributes.get('title', ''):
                self.spanCount += 1

            # Handle links - capture ALL catalog types (t0, t1, t2, t3, t4)
            if self.insideDataDiv and tag == 'a' and len(attrs) > 0:
                href = attributes.get('href', '')
                # Match ALL catalog types using regex
                if re.match(r'^/t[0-4]-', href):
                    if self.infoMap['torrLink'] == self.spanCount and href:
                        self.singleResData['link'] = self.url + href
                    if self.infoMap['name'] == self.spanCount and href:
                        self.singleResData['desc_link'] = self.url + href

        def handle_endtag(self, tag):
            if not self.pageComplete:
                if tag == 'div':
                    self.insideDataDiv = False
                    self.spanCount = -1
                    if len(self.singleResData) > 0:
                        # Only process valid torrents
                        if (self.singleResData['name'] != '-1' and
                                self.singleResData['size'] != '-1' and
                                self.singleResData['name'].lower() != 'nome'):
                            if self.singleResData['desc_link'] != '-1' or self.singleResData['link'] != '-1':
                                # Convert date to timestamp
                                try:
                                    date_string = self.singleResData['pub_date']
                                    if 'ago' not in date_string:  # Only convert absolute dates
                                        date = datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S')
                                        self.singleResData['pub_date'] = int(date.timestamp())
                                except Exception:
                                    pass

                                self.pageRes.append(self.singleResData.copy())
                                self.fullResData.append(self.singleResData.copy())
                        self.singleResData = self.get_single_data()

        def handle_data(self, data):
            if self.insideDataDiv:
                for key, val in self.infoMap.items():
                    if self.spanCount == val:
                        curr_key = key
                        if curr_key in self.singleResData and data.strip() != '':
                            if self.singleResData[curr_key] == '-1':
                                self.singleResData[curr_key] = data.strip()
                            elif curr_key != 'name':
                                self.singleResData[curr_key] += data.strip()

    def _execute_search_pass(self, query, cat='all'):
        """Execute one search pass across multiple pages."""
        if not query:
            return []

        what = query.replace(' ', '+')
        pass_torrents = []

        for currPage in range(0, self.MAX_PAGES_TO_FETCH):
            url = f"{self.url}/?t={what}&p={currPage}"
            try:
                html = retrieve_url(url)
                parser = self.MyHTMLParser(self.url)
                parser.feed(html)
                parser.close()
                pass_torrents.extend(parser.pageRes)

                # Stop if last page
                if len(parser.pageRes) < 20:
                    break

            except Exception as e:
                print(f"DEBUG: Error retrieving page {currPage}: {e}", file=sys.stderr)
                continue

        return pass_torrents

    def search(self, what, cat='all'):
        """Execute intelligent multi-pass search."""
        decoded_what = unquote(what)
        search_keywords = self._get_scoring_keywords(decoded_what)

        # Multi-pass search with different query cleaning
        all_results = []

        # Pass 1: Original query
        pass1_results = self._execute_search_pass(decoded_what, cat)
        all_results.extend(pass1_results)

        # Pass 2: Conservative cleaning
        pass2_query = self._clean_conservative_query(decoded_what)
        if pass2_query.lower() != decoded_what.lower():
            pass2_results = self._execute_search_pass(pass2_query, cat)
            all_results.extend(pass2_results)

        # Pass 3: Aggressive cleaning
        pass3_query = self._clean_aggressive_query(decoded_what)
        if pass3_query.lower() not in [decoded_what.lower(), pass2_query.lower()]:
            pass3_results = self._execute_search_pass(pass3_query, cat)
            all_results.extend(pass3_results)

        # Deduplicate by desc_link
        unique_torrents = {}
        for torrent in all_results:
            desc_link = torrent['desc_link']
            if desc_link not in unique_torrents:
                unique_torrents[desc_link] = torrent

        final_candidates = list(unique_torrents.values())

        if not final_candidates:
            return

        # Score and sort torrents by relevance
        for torrent in final_candidates:
            torrent['score'] = self._calculate_score(torrent['name'], search_keywords)
            try:
                torrent['seeds_int'] = int(torrent['seeds']) if torrent['seeds'] != '-1' else 0
            except (ValueError, TypeError):
                torrent['seeds_int'] = 0

        final_candidates.sort(key=lambda t: (t['score'], t['seeds_int']), reverse=True)

        # Select torrents for magnet fetching
        torrents_to_fetch = []
        if final_candidates:
            max_score = final_candidates[0]['score']
            top_tier = [t for t in final_candidates if t['score'] == max_score]
            torrents_to_fetch.extend(top_tier)

            # Add safety net from lower scoring results
            lower_tier = [t for t in final_candidates if t['score'] < max_score]
            torrents_to_fetch.extend(lower_tier[:self.SAFETY_NET_RESULTS_COUNT])

        # Fetch magnet links in parallel
        with ThreadPoolExecutor(max_workers=self.MAX_MAGNET_WORKERS) as executor:
            futures = {}
            for torrent in torrents_to_fetch:
                torrent_dict = {
                    'name': torrent['name'],
                    'size': torrent['size'],
                    'seeds': torrent['seeds'],
                    'leech': torrent['leech'],
                    'engine_url': self.url,
                    'desc_link': torrent['desc_link'],
                    'link': '-1'
                }
                future = executor.submit(self._fetch_magnet_link, torrent)
                futures[future] = torrent_dict

            for future in as_completed(futures):
                torrent_dict = futures[future]
                if result := future.result():
                    torrent_dict['link'] = result['link']
                prettyPrinter(torrent_dict)

    def download_torrent(self, info):
        """Download magnet link for a torrent."""
        try:
            html = retrieve_url(info)
            magnet_match = re.search(r'href=["\'](magnet:\?[^"\']+)["\']', html, re.IGNORECASE)
            if magnet_match:
                magnet = unquote(magnet_match.group(1))
                print(f"{magnet} {info}")
        except Exception as e:
            print(f"DEBUG: Error downloading torrent: {e}", file=sys.stderr)

if __name__ == "__main__":
    engine = torrentproject()
    engine.search('Breaking Bad S02E07')
