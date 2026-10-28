import pytest
from PIL import Image

from carnival import fetch, pages


def test_the_texted_png_splits_at_its_transparent_gap(tmp_path):
    stacked = Image.new("RGBA", (100, 530), (200, 0, 0, 255))
    stacked.paste((0, 0, 0, 0), (0, 260, 100, 262))  # the gap: two fully transparent rows
    stacked.save(tmp_path / "ad.png")
    paths = pages.extract(tmp_path / "ad.png", tmp_path / "pages")
    assert [Image.open(p).size for p in paths] == [(100, 260), (100, 268)]
    assert Image.open(paths[0]).mode == "RGB"


def test_tiles_cover_every_row_with_the_overlap_and_b_is_offset(tmp_path):
    Image.new("RGB", (937, 2052), "white").save(tmp_path / "page-000.png")
    manifest = pages.tile([tmp_path / "page-000.png"], tmp_path / "tiles", width=1400, height=1050, overlap=520)
    height = manifest["pages"][0]["height"]
    assert height == round(2052 * 1400 / 937)
    for p in "ab":
        tiles = [t for t in manifest["tiles"] if t["pass"] == p]
        assert tiles[0]["top"] == 0 and tiles[-1]["bottom"] == height
        for upper, lower in zip(tiles, tiles[1:]):
            assert upper["bottom"] - lower["top"] >= 520  # every cell shorter than this is whole somewhere
    a = {t["top"] for t in manifest["tiles"] if t["pass"] == "a"}
    b = {t["top"] for t in manifest["tiles"] if t["pass"] == "b"}
    assert a & b == {0}  # different cuts, apart from the top of the page
    for t in manifest["tiles"]:
        path = tmp_path / "tiles" / f"{t['id']}.jpg"
        size = Image.open(path).size
        assert path.stat().st_size <= pages.MAX_BYTES
        assert max(size) <= pages.MAX_SIDE and pages.patches(*size) <= pages.MAX_PATCHES


@pytest.mark.parametrize(
    "url",
    [
        "https://carnivalsupermarkets.com/sd-ad/AD.pdf",
        "https://www.carnivalsupermarkets.com/sd-ad/page1.jpg",
        "https://sf0.co/AbC123",
    ],
)
def test_accepted_urls(url):
    assert fetch.check_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://carnivalsupermarkets.com/sd-ad/AD.pdf",  # not https
        "https://carnivalsupermarkets.com/ad/ad.pdf",  # the Chula Vista store
        "https://carnivalsupermarkets.com.evil.example/sd-ad/AD.pdf",
        "https://user@carnivalsupermarkets.com/sd-ad/AD.pdf",
        "https://example.com/ad.png",
        "file:///etc/passwd",
    ],
)
def test_rejected_urls(url):
    with pytest.raises(fetch.Rejected):
        fetch.check_url(url)


def test_the_texted_links_viewer_unwraps_to_the_ad_image():
    viewer = "https://salefish.invisipon.com/consumer/adview?id=152812105&url=https://salefish-salead.b-cdn.net/74298.png"
    assert fetch.check_url(viewer) == "https://salefish-salead.b-cdn.net/74298.png"
    for bad in (
        "https://salefish.invisipon.com/consumer/adview?id=1&url=https://example.com/x.png",
        "https://salefish.invisipon.com/consumer/adview?id=1&url=http://salefish-salead.b-cdn.net/1.png",
        "https://salefish.invisipon.com/consumer/adview?id=1",
        "https://salefish.invisipon.com/somewhere-else?url=https://salefish-salead.b-cdn.net/1.png",
    ):
        with pytest.raises(fetch.Rejected):
            fetch.check_url(bad)


def test_downloads_must_be_an_ad_file():
    assert fetch.identify(b"%PDF-1.4 ...")["kind"] == "pdf"
    with pytest.raises(fetch.Rejected, match="web page"):
        fetch.identify(b"<!doctype html><html>")
