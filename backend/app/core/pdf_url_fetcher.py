"""Stop PDF rendering from fetching URLs on the server's behalf.

WeasyPrint resolves every ``img src`` and CSS ``url()`` it meets, using the
application's own network position. Templates are authored by members of an
organization, so an ``<img src="http://169.254.169.254/...">`` turns the
renderer into a proxy for whatever the server can reach — cloud metadata,
internal admin ports — and the response can come back inside the rendered page.

The HTML sanitizer deliberately keeps ``img[src]``, ``a[href]`` and ``style``,
because those are legitimate in a document template. The limit belongs here
instead: only ``data:`` URIs resolve, which is what the in-tree templates use
(barcodes and QR codes are embedded base64). WeasyPrint raises on anything else
and renders the document without that resource.
"""

from weasyprint.urls import URLFetcher

_ALLOWED_PROTOCOLS = ('data',)


def data_only_fetcher() -> URLFetcher:
    """Return a fetcher that resolves ``data:`` URIs and refuses everything else.

    A fresh instance per render: ``URLFetcher`` keeps per-request state, so a
    shared one would not be safe across concurrent renders.
    """
    return URLFetcher(allowed_protocols=_ALLOWED_PROTOCOLS)
