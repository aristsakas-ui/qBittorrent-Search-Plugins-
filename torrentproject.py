import re
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

class torrentproject_fixed(object):
    url = 'https://torrentproject.cc'
    name = 'TorrentProject (Fixed)'
    supported_categories = {'all': '0'}

    def _parse_search_results(self, html):
        """New robust parser that handles the actual HTML structure"""
        torrents = []

        # Regex to extract all torrent divs
        torrent_divs = re.findall(r'<div><span>(.*?)</span>\s*<span>(.*?)</span><span>(.*?)</span><span>(.*?)</span><span>(.*?)</span></div>', html, re.DOTALL)

        for div in torrent_divs:
            try:
                title_block, seeds, leech, date, size = div

                # Extract title and link from the first span
                title_match = re.search(r'<a href=[\'"](/t\d[^\'"]*?)[\'"][^>]*>([^<]+)</a>', title_block)
                if not title_match:
                    continue

                desc_link, name = title_match.groups()
                desc_link = self.url + desc_link

                # Clean up the name
                name = re.sub(r'&nbsp;|⭐️|\.\.\.', '', name).strip()

                torrents.append({
                    'name': name,
                    'desc_link': desc_link,
                    'seeds': seeds.strip(),
                    'leech': leech.strip(),
                    'size': size.strip(),
                    'pub_date': date.strip(),
                    'engine_url': self.url
                })
            except Exception:
                continue

        return torrents

    def _execute_search_pass(self, query, cat='all'):
        """Execute search with direct category scanning"""
        if not query:
            return []

        what = query.replace(' ', '+')
        all_torrents = []

        # Search across all categories (t0 through t4)
        for category in ['t0', 't1', 't2', 't3', 't4']:
            for currPage in range(MAX_PAGES_TO_FETCH):
                # Use the category-specific search
                url = f"{self.url}/{category}/?s={what}&p={currPage}"
                try:
                    html = retrieve_url(url)
                    torrents = self._parse_search_results(html)
                    all_torrents.extend(torrents)

                    # If we got few results, this category might be exhausted
                    if len(torrents) < 10:
                        break
                except Exception:
                    continue

        return all_torrents

    def _convert_date_to_timestamp(self, date_str):
        """Convert relative dates to timestamps"""
        try:
            # Handle "X days/weeks/months/years ago"
            if 'ago' in date_str:
                # For now, return current timestamp as fallback
                # In a real implementation, you'd parse the relative date
                return int(datetime.now().timestamp())
            # Handle absolute dates if present
            elif re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                date = datetime.strptime(date_str, '%Y-%m-%d')
                return int(date.timestamp())
        except:
            pass
        return '-1'

    # Keep the rest of your intelligent search methods the same...
    def _get_conservative_query(self, query):
        query = re.sub(r'[\(\[]\d{4}[\)\]]', '', query)
        query = re.sub(r'\s+', ' ', query)
        return query.strip()

    def _get_aggressive_query(self, query):
        query = re.sub(r'[^a-zA-Z0-9\s]', ' ', query)
        query = re.sub(r'\s+', ' ', query)
        return query.strip()

    def search(self, what, cat='all'):
        """Main search with the fixed parser"""
        decoded_what = unquote(what)
        search_keywords = self._get_keywords_for_scoring(decoded_what)

        # Multi-pass search
        pass1_query = self._get_conservative_query(decoded_what)
        pass1_results = self._execute_search_pass(pass1_query, cat)

        pass2_query = self._get_aggressive_query(decoded_what)
        pass2_results = []
        if pass2_query.lower() != pass1_query.lower():
            pass2_results = self._execute_search_pass(pass2_query, cat)

        # De-duplication and scoring (your existing code)
        all_torrents = {t['desc_link']: t for t in pass1_results + pass2_results}
        final_candidates = list(all_torrents.values())

        if not final_candidates:
            return

        # Convert dates to timestamps for qBittorrent
        for torrent in final_candidates:
            torrent['pub_date'] = self._convert_date_to_timestamp(torrent.get('pub_date', ''))
            torrent['score'] = self._calculate_advanced_score(torrent['name'], search_keywords)
            try:
                torrent['seeds_int'] = int(torrent['seeds']) if torrent['seeds'] != 'N/A' else 0
            except ValueError:
                torrent['seeds_int'] = 0

        final_candidates.sort(key=lambda t: (t['score'], t['seeds_int']), reverse=True)

        # Fetch magnets and print results (your existing code)...
