"""Unit tests for the PDF renderer's URL fetcher.

A template author is a member of the organization, not an administrator of the
server; the renderer must not fetch on their behalf.
"""

import base64
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from weasyprint import HTML

from app.core.pdf_url_fetcher import data_only_fetcher

# 1x1 white PNG.
_PNG = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4'
    '//8/AAX+Av4N70a4AAAAAElFTkSuQmCC'
)
_DATA_URI = f'data:image/png;base64,{_PNG}'


class _CountingHandler(BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):  # BaseHTTPRequestHandler API
        type(self).hits.append(self.path)
        self.send_response(200)
        self.send_header('Content-Type', 'image/png')
        self.end_headers()
        self.wfile.write(base64.b64decode(_PNG))

    def log_message(self, *args):  # silence test server logging
        pass


@pytest.fixture
def counting_server():
    _CountingHandler.hits = []
    server = HTTPServer(('127.0.0.1', 0), _CountingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}'
    finally:
        server.shutdown()
        server.server_close()


class TestDataOnlyFetcher:
    def test_data_uri_resolves(self):
        response = data_only_fetcher().fetch(_DATA_URI)
        assert response.content_type == 'image/png'

    @pytest.mark.parametrize(
        'url',
        [
            'http://169.254.169.254/latest/meta-data/',
            'https://example.com/pixel.png',
            'file:///etc/passwd',
            '/relative/path.png',
        ],
    )
    def test_everything_else_is_refused(self, url):
        with pytest.raises(ValueError):
            data_only_fetcher().fetch(url)


class TestRenderingHonoursTheFetcher:
    def test_template_image_never_reaches_the_network(self, counting_server):
        html = f'<html><body><img src="{counting_server}/tracker.png"></body></html>'

        pdf = HTML(string=html, url_fetcher=data_only_fetcher()).write_pdf()

        assert pdf
        assert _CountingHandler.hits == []

    def test_the_probe_server_would_otherwise_be_hit(self, counting_server):
        """Guards the test itself: the default fetcher does make the request."""
        html = f'<html><body><img src="{counting_server}/tracker.png"></body></html>'

        HTML(string=html).write_pdf()

        assert _CountingHandler.hits == ['/tracker.png']

    def test_data_uri_image_still_renders(self):
        html = f'<html><body><img src="{_DATA_URI}"></body></html>'

        pdf = HTML(string=html, url_fetcher=data_only_fetcher()).write_pdf()

        assert pdf.startswith(b'%PDF')


def test_no_dns_lookup_needed():
    """Sanity: the probe host is a literal IP, so no resolver is involved."""
    assert socket.inet_aton('127.0.0.1')
