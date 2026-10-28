"""Step 1: download the ad. Every URL is untrusted, including the one pasted into the form.

We only speak https, only to the hosts this ad comes from, and check every redirect hop
before following it. The store's site serves two ads: /sd-ad/ is the Ashford St. store, and
/ad/ is Chula Vista, which is never what we want. The link the store texts out (sf0.co)
redirects to Salefish's ad viewer, a web page whose `url` parameter is the ad itself, a PNG on
Salefish's CDN; we go straight to the PNG.
"""

import hashlib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

STORE_PDF = "https://carnivalsupermarkets.com/sd-ad/AD.pdf"
VIEWER = "salefish.invisipon.com"
HOSTS = {"carnivalsupermarkets.com", "www.carnivalsupermarkets.com", "sf0.co", VIEWER, "salefish-salead.b-cdn.net"}
MAX_BYTES = 50 * 2**20
KINDS = {b"%PDF-": "pdf", b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg"}


class Rejected(ValueError):
    """A URL or file we refuse to use."""


def check_url(url):
    """The URL to fetch for `url`, or Rejected. Unwraps Salefish's viewer to the ad it shows."""
    parts = urllib.parse.urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise Rejected(f"only https links: {url!r}")
    if host not in HOSTS or parts.username or parts.password or parts.port not in (None, 443):
        raise Rejected(f"{host or url!r} isn't a host this ad comes from")
    if host.endswith("carnivalsupermarkets.com") and not parts.path.lower().startswith("/sd-ad/"):
        raise Rejected("that's not the Ashford St. store's ad (it lives under /sd-ad/)")
    if host == VIEWER:
        shown = urllib.parse.parse_qs(parts.query).get("url", [])
        if parts.path != "/consumer/adview" or len(shown) != 1 or urllib.parse.urlsplit(shown[0]).hostname == VIEWER:
            raise Rejected("that ad viewer link doesn't name an ad image")
        return check_url(shown[0])
    return url.strip()


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, check_url(newurl))


_open = urllib.request.build_opener(_CheckedRedirects).open


@dataclass
class Download:
    body: bytes
    meta: dict  # what meta.json records about the source

    @property
    def filename(self):
        return f"source.{self.meta['kind']}"


def download(url, etag=None, last_modified=None):
    """GET the ad, conditionally if we have validators. None means it hasn't changed."""
    headers = {"User-Agent": "carnival-deals-bot (+https://github.com/lorenzollama/Carnival)"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        with _open(urllib.request.Request(check_url(url), headers=headers), timeout=60) as r:
            body = r.read(MAX_BYTES + 1)
            final_url, etag, last_modified = r.url, r.headers.get("ETag"), r.headers.get("Last-Modified")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None
        raise
    return Download(body, {"url": url, "final_url": final_url, "etag": etag, "last_modified": last_modified, **identify(body)})


def identify(body):
    """Size, hash, and kind of a downloaded file, which must be a PDF or an image."""
    if len(body) > MAX_BYTES:
        raise Rejected("the file is larger than any ad")
    kind = next((k for magic, k in KINDS.items() if body.startswith(magic)), None)
    if not kind:
        raise Rejected("the link didn't lead to a PDF or an image (a web page, perhaps?)")
    return {"kind": kind, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
