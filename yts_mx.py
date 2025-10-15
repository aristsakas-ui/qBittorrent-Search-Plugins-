# AUTHORS: Lyra Aranha (lyra@lazulyra.com) 
# improved by me



import re
import json
from urllib.parse import quote_plus, unquote, urlencode
from helpers import retrieve_url
from novaprinter import prettyPrinter

class yts_mx(object):
    """
    This search engine script interfaces with the YTS.mx API to retrieve movie torrents for qBittorrent.

    ## Functionality Explained:
    1. **API Integration**: Uses the YTS API (`https://yts.mx/api/v2/list_movies.json`) to fetch
       structured JSON data, providing rich metadata like seeds, peers, codecs, and audio channels.
    2. **Aggressive Query Cleaning**: Removes years, special characters, and trailing ampersands to
       ensure broad, forgiving searches, while supporting API-specific filters (quality, codec, rating, genre).
    3. **Custom Sorting**: Ranks results by title match:
       - Rank 1: Title STARTS WITH search term.
       - Rank 2: Title CONTAINS search term as a whole word.
       - Rank 3: Title CONTAINS search term as part of another word.
    4. **Output**: Formats results with detailed metadata (title, year, quality, codec, audio, seeds, peers)
       and prints them to the UI in sorted order.
    5. **No Diagnostics**: Error handling is silent, skipping invalid responses without logging.

    ## Notes:
    - Designed for qBittorrent plugin compatibility.
    - Combines API metadata, advanced query cleaning, and custom sorting for optimal results.
    - Static attributes (`url`, `name`, `supported_categories`) are defined as required by qBittorrent.
    """

    # Static attributes required by qBittorrent
    url = 'https://yts.mx/'
    name = 'YTS.MX (Intelligent)'
    supported_categories = {'all': '0', 'movies': '1'}
    api_url = 'https://yts.mx/api/v2/list_movies.json'

    def _clean_query(self, query):
        """
        Cleans the search query aggressively to ensure broad search results.

        Rules:
        - Decode URL-encoded query.
        - Remove trailing ampersands and anything after.
        - Unconditionally remove parenthetical years (e.g., `(1999)`).
        - Unconditionally remove trailing 4-digit years.
        - Remove parentheses and strip whitespace.

        Args:
            query (str): Raw search query.
        Returns:
            str: Cleaned query or empty string if invalid.
        """
        try:
            cleaned_query = unquote(query)
        except Exception:
            cleaned_query = query

        # Remove trailing ampersand and beyond
        amp_pos = cleaned_query.find('&')
        if amp_pos != -1:
            cleaned_query = cleaned_query[:amp_pos].strip()

        # Remove parenthetical years (e.g., (1999))
        cleaned_query = re.sub(r'\(\s*\d{4}\s*\)', '', cleaned_query).strip()

        # Remove trailing 4-digit years
        words = cleaned_query.split()
        if words and words[-1].isdigit() and len(words[-1]) == 4:
            cleaned_query = ' '.join(words[:-1]).strip()

        # Remove parentheses and strip
        cleaned_query = cleaned_query.replace('(', '').replace(')', '').strip()

        return cleaned_query

    def _get_sort_rank(self, title, search_term):
        """
        Assigns a sort rank based on how well the title matches the search term.
        Lower ranks are better.

        Ranking Hierarchy:
        - Rank 1: Title starts with the search term.
        - Rank 2: Title contains the search term as a whole word.
        - Rank 3: Title contains the search term as part of another word.
        - Rank 4: No match (default).

        Args:
            title (str): Movie title.
            search_term (str): Cleaned search query.
        Returns:
            int: Sort rank (1 is best, 4 is worst).
        """
        low_title = title.lower()
        low_term = search_term.lower()

        if low_title.startswith(low_term):
            return 1
        elif re.search(r'\b' + re.escape(low_term) + r'\b', low_title):
            return 2
        elif low_term in low_title:
            return 3
        return 4

    def search(self, what, cat='all'):
        """
        Searches YTS.mx API for the given query, with advanced filtering and custom sorting.

        Steps:
        1. Cleans the query aggressively to remove years and special characters.
        2. Parses quality, codec, rating, and genre filters from the query.
        3. Fetches all result pages from the API.
        4. Filters results by quality and codec if specified.
        5. Sorts results using custom ranking logic based on title match.
        6. Outputs formatted torrent data to the UI.

        Args:
            what (str): URL-encoded search query (e.g., "Matrix+1080p+x264+rating=7").
            cat (str): Category ('all' or 'movies').
        """
        # Clean query aggressively
        search_query = self._clean_query(what)
        if not search_query:
            return

        search_params = {}
        # Parse quality filter (e.g., 1080p, 3D)
        quality_rstring = r'(?:quality=)?((?:2160|1440|1080|720|480|240)p|3D)'
        quality_re = re.search(quality_rstring, what, re.IGNORECASE)
        search_resolution = None
        if quality_re:
            search_resolution = quality_re.group(1)
            search_params['quality'] = search_resolution
            what = re.sub(quality_rstring, '', what, flags=re.IGNORECASE).strip()

        # Parse codec filter (e.g., x264, x265)
        codec_rstring = r'\.?(?:x|h)(264|265)'
        codec_re = re.search(codec_rstring, what, re.IGNORECASE)
        search_codec = None
        if codec_re:
            search_codec = 'x' + codec_re.group(1)
            search_params['query_term'] = f'{search_query}.{search_codec}' if search_query else search_codec
            what = re.sub(codec_rstring, '', what, flags=re.IGNORECASE).strip()

        # Parse rating filter
        rating_rstring = r'(?:min(?:imum)?_)?rating=(\d)'
        rating_re = re.search(rating_rstring, what, re.IGNORECASE)
        if rating_re:
            search_params['minimum_rating'] = rating_re.group(1)
            what = re.sub(rating_rstring, '', what, flags=re.IGNORECASE).strip()

        # Parse genre filter
        genre_rstring = r'genre=(\w+)'
        genre_re = re.search(genre_rstring, what, re.IGNORECASE)
        if genre_re:
            search_params['genre'] = genre_re.group(1)
            what = re.sub(genre_rstring, '', what, flags=re.IGNORECASE).strip()

        # Remove page number attempts
        what = re.sub(r'&page=\d+', '', what, flags=re.IGNORECASE).strip()

        # Set query term if any remains
        if what and not search_codec:
            search_params['query_term'] = self._clean_query(what)

        # Build API URL
        search_url = f'{self.api_url}?{urlencode(search_params)}'

        # Fetch first page to get total movie count
        try:
            response = retrieve_url(search_url)
            if not response:
                return
            api_result = json.loads(response)
            if api_result.get('status') != 'ok' or api_result.get('data', {}).get('movie_count', 0) == 0:
                return
        except Exception:
            return

        all_results = []
        # Iterate through all pages
        total_pages = (api_result['data']['movie_count'] // api_result['data']['limit']) + 1
        for page_no in range(total_pages):
            try:
                page_url = f'{search_url}&page={page_no + 1}'
                response = retrieve_url(page_url)
                if not response:
                    continue
                api_result = json.loads(response)
                if api_result.get('status') != 'ok' or not api_result.get('data', {}).get('movies'):
                    continue

                for movie in api_result['data']['movies']:
                    for torrent in movie.get('torrents', []):
                        # Apply quality and codec filters
                        if search_resolution and torrent.get('quality') != search_resolution:
                            continue
                        if search_codec and torrent.get('video_codec') != search_codec:
                            continue

                        result = {
                            'link': torrent.get('url', '').replace('&', '&'),
                            'name': (f"{movie.get('title_long', '')} [{torrent.get('quality', '')}] "
                                     f"[{torrent.get('video_codec', '')}] [{torrent.get('type', '')}] "
                                     f"[{torrent.get('audio_channels', '')}] [YTS.MX]"),
                            'size': torrent.get('size', 'unknown'),
                            'seeds': str(torrent.get('seeds', -1)),
                            'leech': str(torrent.get('peers', -1)),
                            'engine_url': self.url,
                            'desc_link': movie.get('url', ''),
                            'pub_date': torrent.get('date_uploaded_unix', 0),
                            '_sort_title': movie.get('title', '')  # For sorting
                        }
                        all_results.append(result)
            except Exception:
                continue

        # Sort results by title match relevance
        all_results.sort(key=lambda r: self._get_sort_rank(r['_sort_title'], search_query))

        # Output results
        for result in all_results:
            del result['_sort_title']  # Remove temporary sort key
            prettyPrinter(result)

    def download_torrent(self, info):
        """
        Outputs torrent info for qBittorrent compatibility.

        Args:
            info (str): Torrent URL or magnet link.
        """
        print(f"{info} -1")
