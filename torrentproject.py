# VERSION: 1.8
# AUTHORS: mauricci (with intelligent search features, minimal readability improvements)

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
    MAX_PAGES_TO_FETCH = 3           # Search 3 pages per pass
    MAX_MAGNET_WORKERS = 10          # Parallel magnet fetching
    SAFETY_NET_RESULTS_COUNT = 5     # Show lower-scoring results as backup

    def _clean_conservative_query(self, query):
        """Remove unambiguous metadata (e.g., year) from query."""
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
            match = re.search(r'href=["\'](.*?(magnet.+?))["\']', html)
            if match:
                magnet = unquote(match.group(1))
                torrent['link'] = magnet
                print(f"DEBUG: Fetched magnet for {torrent['name']}: {magnet}", file=sys.stderr)
                return torrent
            else:
                print(f"DEBUG: No magnet link found for {torrent['desc_link']}", file=sys.stderr)
        except Exception as e:
            print(f"DEBUG: Error fetching magnet for {torrent['desc_link']}: {e}", file=sys.stderr)
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
            self.infoMap = {
                "name": 0,
                "torrLink": 0,
                "seeds": 2,
                "leech": 3,
                "pub_date": 4,
                "size": 5,
            }
            self.fullResData = []
            self.pageRes = []
            self.singleResData = self.get_single_data()

        def get_single_data(self):
            """Return default torrent data dictionary."""
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
            if tag == 'div' and 'nav' in attributes.get('id', ''):
                self.pageComplete = True
            if tag == 'div' and attributes.get('id', '') == 'similarfiles':
                self.insideResults = True
            if tag == 'div' and self.insideResults and 'gac_bb' not in attributes.get('class', ''):
                self.insideDataDiv = True
            elif tag == 'span' and self.insideDataDiv and 'verified' != attributes.get('title', ''):
                self.spanCount += 1
            if self.insideDataDiv and tag == 'a' and len(attrs) > 0:
                if self.infoMap['torrLink'] == self.spanCount and 'href' in attributes:
                    self.singleResData['link'] = self.url + attributes['href']
                if self.infoMap['name'] == self.spanCount and 'href' in attributes:
                    self.singleResData['desc_link'] = self.url + attributes['href']

        def handle_endtag(self, tag):
            if not self.pageComplete:
                if tag == 'div':
                    self.insideDataDiv = False
                    self.spanCount = -1
                    if len(self.singleResData) > 0:
                        if (self.singleResData['name'] != '-1' and
                                self.singleResData['size'] != '-1' and
                                self.singleResData['name'].lower() != 'nome'):
                            if self.singleResData['desc_link'] != '-1' or self.singleResData['link'] != '-1':
                                try:
                                    date_string = self.singleResData['pub_date']
                                    date = datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S')
                                    self.singleResData['pub_date'] = int(date.timestamp())
                                except Exception:
                                    pass
                                try:
                                    prettyPrinter(self.singleResData)
                                    print(f"DEBUG: Parsed torrent: {self.singleResData['name']}", file=sys.stderr)
                                except Exception:
                                    print(self.singleResData)
                                self.pageRes.append(self.singleResData)
                                self.fullResData.append(self.singleResData)
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
            url = f"{self.url}/browse?t={what}&p={currPage}"
            try:
                html = retrieve_url(url)
                print(f"DEBUG: Fetched page {currPage} for query {what}", file=sys.stderr)
                parser = self.MyHTMLParser(self.url)
                parser.feed(html)
                parser.close()
                pass_torrents.extend(parser.pageRes)
                print(f"DEBUG: Found {len(parser.pageRes)} torrents on page {currPage}", file=sys.stderr)
                if len(parser.pageRes) < 20:
                    break
            except Exception as e:
                if __name__ == '__main__':
                    print(f"Error retrieving page {currPage}: {e}", file=sys.stderr)
                continue

        return pass_torrents

    def search(self, what, cat='all'):
        """Execute intelligent multi-pass search."""
        decoded_what = unquote(what)
        search_keywords = self._get_scoring_keywords(decoded_what)

        # First pass: conservative cleaning
        pass1_query = self._clean_conservative_query(decoded_what)
        pass1_results = self._execute_search_pass(pass1_query, cat)
        print(f"DEBUG: Pass 1 found {len(pass1_results)} results", file=sys.stderr)

        # Second pass: aggressive cleaning
        pass2_query = self._clean_aggressive_query(decoded_what)
        pass2_results = []
        if pass2_query.lower() != pass1_query.lower():
            pass2_results = self._execute_search_pass(pass2_query, cat)
            print(f"DEBUG: Pass 2 found {len(pass2_results)} results", file=sys.stderr)

        # Deduplicate results
        all_torrents = {t['desc_link']: t for t in pass1_results + pass2_results}
        final_candidates = list(all_torrents.values())
        print(f"DEBUG: Total unique torrents: {len(final_candidates)}", file=sys.stderr)

        if not final_candidates:
            return

        # Score and sort torrents
        for torrent in final_candidates:
            torrent['score'] = self._calculate_score(torrent['name'], search_keywords)
            try:
                torrent['seeds_int'] = int(torrent['seeds'])
            except ValueError:
                torrent['seeds_int'] = 0

        final_candidates.sort(key=lambda t: (t['score'], t['seeds_int']), reverse=True)

        # Select top and safety net torrents
        torrents_to_fetch = []
        if final_candidates:
            max_score = final_candidates[0]['score']
            top_tier = [t for t in final_candidates if t['score'] == max_score]
            torrents_to_fetch.extend(top_tier)
            lower_tier = [t for t in final_candidates if t['score'] < max_score]
            torrents_to_fetch.extend(lower_tier[:self.SAFETY_NET_RESULTS_COUNT])
            print(f"DEBUG: Fetching {len(torrents_to_fetch)} torrents", file=sys.stderr)

        # Fetch magnet links in parallel
        with ThreadPoolExecutor(max_workers=self.MAX_MAGNET_WORKERS) as executor:
            futures = [executor.submit(self._fetch_magnet_link, t) for t in torrents_to_fetch]
            for future in as_completed(futures):
                if result := future.result():
                    prettyPrinter({
                        'link': result['link'],
                        'name': result['name'],
                        'size': result['size'],
                        'seeds': result['seeds'],
                        'leech': result['leech'],
                        'engine_url': self.url,
                        'desc_link': result['desc_link']
                    })

    def download_torrent(self, info):
        """Download magnet link for a torrent."""
        try:
            html = retrieve_url(info)
            match = re.search(r'href=["\'](.*?(magnet.+?))["\']', html)
            if match:
                magnet = unquote(match.group(1))
                print(f"{magnet} {info}")
            else:
                print(f"DEBUG: No magnet link found for {info}", file=sys.stderr)
        except Exception as e:
            if __name__ == '__main__':
                print(f"Error downloading torrent: {e}", file=sys.stderr)
