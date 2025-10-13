# VERSION: 19.1 (Fixed Year Handling)
# AUTHORS: AI Assistant & User Collaboration

import re
import os
import datetime
from urllib.parse import quote_plus, urljoin, unquote_plus

# qBittorrent-specific imports
from helpers import retrieve_url
from novaprinter import prettyPrinter

class yts_mx(object):
    """
    This search engine script is designed to interface with the YTS.mx website.

    ## FIXED: Year Handling
    - Now preserves years when they are part of the intentional search
    - Only removes years in parentheses or when clearly not part of the main title
    """
    url = "https://en.yts-official.mx"
    name = "YTS (Fixed Year Handling)"
    supported_categories = {'all': 'all', 'movies': 'movies'}

    def __init__(self):
        pass

    def download_torrent(self, info):
        print(f"{info} -1")

    def _clean_query(self, query):
        try:
            cleaned_query = unquote_plus(query)
        except Exception:
            cleaned_query = query

        amp_pos = cleaned_query.find('&')
        if amp_pos != -1:
            cleaned_query = cleaned_query[:amp_pos].strip()

        # FIXED: Only remove parenthetical years, not all trailing years
        # Remove parenthetical years like (1999) but keep standalone years
        cleaned_query = re.sub(r'\(\s*\d{4}\s*\)', '', cleaned_query).strip()

        # Keep trailing years - they're likely intentional search terms
        # Only clean up any extra parentheses
        cleaned_query = cleaned_query.replace('(', '').replace(')', '').strip()

        return cleaned_query

    def _get_sort_rank(self, title, search_term):
        """Assigns a sort rank. Lower is better."""
        low_title = title.lower()
        low_term = search_term.lower()

        # Rank 1 (Best): Title starts with the search term
        if low_title.startswith(low_term):
            return 1
        # Rank 2: Title contains the search term as a whole word
        elif re.search(r'\b' + re.escape(low_term) + r'\b', low_title):
            return 2
        # Rank 3: Title contains the search term as part of another word
        elif low_term in low_title:
            return 3
        # Rank 4 (Worst): Default/No match
        else:
            return 4

    def search(self, query, cat='all'):
        try:
            search_query = self._clean_query(query)
            if not search_query:
                return

            all_movie_links = set()
            for page_num in range(1, 3):
                search_url = f"{self.url}/browse-movies?keyword={quote_plus(search_query)}&page={page_num}"
                search_page_html = retrieve_url(search_url)

                if not search_page_html:
                    break

                links_on_page = set(re.findall(
                    r'<div class="browse-movie-wrap[^"]*">.*?<a href="(/movies/[^"]+)"',
                    search_page_html,
                    re.DOTALL
                ))

                if not links_on_page:
                    break

                all_movie_links.update(links_on_page)

            if not all_movie_links:
                return

            all_results = []
            for movie_link in all_movie_links:
                desc_link = urljoin(self.url, movie_link)
                try:
                    detail_page_html = retrieve_url(desc_link)
                    if not detail_page_html:
                        continue
                except Exception:
                    continue

                title_match = re.search(
                    r'<div id="movie-info".*?>.*?<h1>([^<]+)</h1>',
                    detail_page_html,
                    re.DOTALL
                )
                year_match = re.search(
                    r'<div id="movie-info".*?>.*?<h2>(\d{4})</h2>',
                    detail_page_html,
                    re.DOTALL
                )

                if not title_match or not year_match:
                    continue

                movie_title = title_match.group(1).strip()
                movie_year = year_match.group(1).strip()

                # Enhanced torrent extraction pattern
                all_torrents = re.findall(
                    r'<div class="modal-torrent">.*?<span>([^<]+)</span>.*?<p class="quality-size">([^<]+)</p>.*?((?:\d|\.)+\s(?:GB|MB)).*?href="(magnet:[^"]+)"',
                    detail_page_html,
                    re.DOTALL
                )

                for torrent_data in all_torrents:
                    quality, torrent_type, size, magnet_link = torrent_data
                    result = {
                        'link': magnet_link.replace('&', '&'),
                        'name': f"{movie_title} ({movie_year}) [{quality.replace('º', '')}.{torrent_type}] [YTS]",
                        'size': size,
                        'seeds': -1,
                        'leech': -1,
                        'engine_url': self.url,
                        'desc_link': desc_link,
                        '_sort_title': movie_title,
                        '_year': movie_year  # Store year for additional filtering
                    }
                    all_results.append(result)

            # Enhanced sorting: prioritize by year relevance when year is in search
            search_has_year = any(word.isdigit() and len(word) == 4 for word in query.split())

            if search_has_year:
                # Extract year from search query if present
                search_year = None
                for word in query.split():
                    if word.isdigit() and len(word) == 4:
                        search_year = word
                        break

                # Sort: exact year matches first, then by title relevance
                all_results.sort(key=lambda r: (
                    0 if search_year and r['_year'] == search_year else 1,  # Exact year matches first
                    self._get_sort_rank(r['_sort_title'], search_query),    # Then title relevance
                    r['_sort_title']                                        # Then alphabetical
                ))
            else:
                # Original sorting when no year in search
                all_results.sort(key=lambda r: (
                    self._get_sort_rank(r['_sort_title'], search_query),
                    r['_sort_title']
                ))

            for result in all_results:
                # Remove temporary keys before printing
                del result['_sort_title']
                if '_year' in result:
                    del result['_year']
                prettyPrinter(result)

        except Exception as e:
            return
