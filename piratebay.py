# VERSION: 3.9.1(intelligent version)
# AUTHORS: Fabien Devaux (fab@gnux.info)
# CONTRIBUTORS: Christophe Dumez (chris@qbittorrent.org)
#               Arthur (custparasite@gmx.se)
#               Diego de las Heras (ngosang@hotmail.es)
#               Me

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#    * Redistributions of source code must retain the above copyright notice,
#      this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above copyright
#      notice, this list of conditions and the following disclaimer in the
#      documentation and/or other materials provided with the distribution.
#    * Neither the name of the author nor the names of its contributors may be
#      used to endorse or promote products derived from this software without
#      specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import datetime
import gzip
import html
import http.client
import io
import json
import re
import urllib.error
import urllib.request
from typing import Mapping
from urllib.parse import unquote, urlencode

import helpers  # for setting SOCKS proxy side-effect
from novaprinter import prettyPrinter

helpers.htmlentitydecode  # pylint: disable=pointless-statement # dirty workaround to surpress static checkers

class piratebay:
    url = 'https://thepiratebay.org'
    name = 'The Pirate Bay (Intelligent)'
    supported_categories = {
        'all': '0',
        'music': '100',
        'movies': '200',
        'games': '400',
        'software': '300'
    }

    # initialize trackers for magnet links
    trackers_list = [
        'udp://tracker.internetwarriors.net:1337/announce',
        'udp://tracker.opentrackr.org:1337/announce',
        'udp://p4p.arenabg.ch:1337/announce',
        'udp://tracker.openbittorrent.com:6969/announce',
        'udp://www.torrent.eu.org:451/announce',
        'udp://tracker.torrent.eu.org:451/announce',
        'udp://retracker.lanta-net.ru:2710/announce',
        'udp://open.stealth.si:80/announce',
        'udp://exodus.desync.com:6969/announce',
        'udp://tracker.tiny-vps.com:6969/announce'
    ]
    trackers = '&'.join(urlencode({'tr': tracker}) for tracker in trackers_list)

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
            title (str): Torrent title.
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

    def search(self, what: str, cat: str = 'all') -> None:
        """
        Searches The Pirate Bay API for the given query, with intelligent query cleaning and custom sorting.

        Steps:
        1. Cleans the query aggressively to remove years and special characters.
        2. Fetches results from the API using the cleaned query.
        3. Sorts results by title match relevance using custom ranking logic.
        4. Outputs formatted torrent data to the UI.

        Args:
            what (str): URL-encoded search query (e.g., "Matrix+1999").
            cat (str): Category ('all', 'music', 'movies', 'games', 'software').
        """
        # Clean query aggressively
        search_query = self._clean_query(what)
        if not search_query:
            return

        base_url = "https://apibay.org/q.php?%s"

        # get response json
        category = self.supported_categories[cat]
        params = {'q': search_query}
        if category != '0':
            params['cat'] = category

        # Calling custom `retrieve_url` function with adequate escaping
        data = self.retrieve_url(base_url % urlencode(params))
        response_json = json.loads(data)

        # check empty response
        if len(response_json) == 0:
            return

        # Parse and collect results
        all_results = []
        for result in response_json:
            if result['info_hash'] == '0000000000000000000000000000000000000000':
                continue
            torrent_data = {
                'link': self.download_link(result),
                'name': result['name'],
                'size': str(result['size']) + " B",
                'seeds': result['seeders'],
                'leech': result['leechers'],
                'engine_url': self.url,
                'desc_link': self.url + '/description.php?id=' + result['id'],
                'pub_date': result['added'],
                '_sort_title': result['name']  # For sorting
            }
            all_results.append(torrent_data)

        # Sort results by title match relevance
        all_results.sort(key=lambda r: self._get_sort_rank(r['_sort_title'], search_query))

        # Output results
        for result in all_results:
            del result['_sort_title']  # Remove temporary sort key
            prettyPrinter(result)

    def download_link(self, result: Mapping[str, str]) -> str:
        dn = urlencode({'dn': result['name']})
        return f"magnet:?xt=urn:btih:{result['info_hash']}&{dn}&{self.trackers}"

    def retrieve_url(self, url: str) -> str:
        def getBrowserUserAgent() -> str:
            """ Disguise as browser to circumvent website blocking """

            # Firefox release calendar
            # https://whattrainisitnow.com/calendar/
            # https://wiki.mozilla.org/index.php?title=Release_Management/Calendar&redirect=no

            baseDate = datetime.date(2024, 4, 16)
            baseVersion = 125

            nowDate = datetime.date.today()
            nowVersion = baseVersion + ((nowDate - baseDate).days // 30)

            return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{nowVersion}.0) Gecko/20100101 Firefox/{nowVersion}.0"

        # Request data from API
        request = urllib.request.Request(url, None, {'User-Agent': getBrowserUserAgent()})

        try:
            response: http.client.HTTPResponse = urllib.request.urlopen(request)  # pylint: disable=consider-using-with
        except urllib.error.HTTPError:
            return ""

        data = response.read()

        if data[:2] == b'\x1f\x8b':
            # Data is gzip encoded, decode it
            with io.BytesIO(data) as stream, gzip.GzipFile(fileobj=stream) as gzipper:
                data = gzipper.read()

        charset = 'utf-8'
        try:
            charset = response.getheader('Content-Type', '').split('charset=', 1)[1]
        except IndexError:
            pass

        dataStr = data.decode(charset, 'replace')
        dataStr = dataStr.replace('&quot;', '\\"')  # Manually escape &quot; before
        dataStr = html.unescape(dataStr)

        return dataStr
