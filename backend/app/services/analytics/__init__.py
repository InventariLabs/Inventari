"""Domain-neutral analytics service layer.

Pure aggregate read-models (GROUP BY, SUM, counts) that back the
``core_api.queries`` CoreAPI namespace. These functions are the legitimate
home for Core DB access — the public_api facade delegates here so module
code never imports ``app.models`` directly.
"""
