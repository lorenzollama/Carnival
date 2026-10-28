"""From the downloaded file to page images, and from pages to tiles a model sees unscaled."""

import math
import subprocess

from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # archived ads have run to 2840x6217 per page

# What reaches the model untouched, measured with tools/image_probe.py (see README, "How tiles
# are sized"). Claude sees an image in 28x28-pixel patches. Claude Code downscales an image wider
# or taller than 2,000 px or bigger than about 4,750 patches, and re-encodes any file over 512 KB
# as a ~500 KB JPEG of roughly quality 68. A tile within all three limits is what the model sees.
PATCH = 28
MAX_SIDE = 2000
MAX_PATCHES = 4700
MAX_BYTES = 500_000
QUALITY = 90


def extract(source, out):
    """Page images, untouched where possible. Returns their paths in page order.

    The store's PDF has no text layer, just one JPEG per page: pdfimages copies those out byte
    for byte. Rasterizing the PDF instead would resample the JPEGs and soften the small print.
    The texted ad is one PNG with the pages stacked and a transparent gap between them.
    """
    out.mkdir(parents=True, exist_ok=True)
    if source.read_bytes()[:5] == b"%PDF-":
        listing = subprocess.run(["pdfimages", "-list", source], capture_output=True, text=True, check=True)
        rows = [line.split() for line in listing.stdout.splitlines()[2:]]
        if [r[0] for r in rows] != [str(n) for n in range(1, len(rows) + 1)] or {r[2] for r in rows} != {"image"}:
            raise ValueError("expected exactly one image per page in the PDF:\n" + listing.stdout)
        subprocess.run(["pdfimages", "-all", source, out / "page"], check=True)
        return sorted(out.glob("page-*"))
    image = Image.open(source)
    pages = split_at_gaps(image) if "A" in image.getbands() else [image.convert("RGB")]
    paths = []
    for n, page in enumerate(pages):
        paths.append(out / f"page-{n:03d}.png")
        page.save(paths[-1])
    return paths


def split_at_gaps(image):
    """Split a stacked image at its fully transparent rows, dropping slivers."""
    alpha = image.getchannel("A")
    width, height = alpha.size
    data = alpha.tobytes()
    clear = [not data[y * width : (y + 1) * width].strip(b"\0") for y in range(height)] + [True]
    pages, top = [], None
    for y, is_clear in enumerate(clear):
        if not is_clear and top is None:
            top = y
        elif is_clear and top is not None:
            if y - top > width // 2:
                part = image.crop((0, top, width, y)).convert("RGBA")
                pages.append(Image.alpha_composite(Image.new("RGBA", part.size, "white"), part).convert("RGB"))
            top = None
    return pages


def patches(width, height):
    return math.ceil(width / PATCH) * math.ceil(height / PATCH)


def save(image, path):
    """Save a JPEG small enough to reach the model as is: quality 90, or less if it must."""
    if max(image.size) > MAX_SIDE or patches(*image.size) > MAX_PATCHES:
        raise ValueError(f"{image.width}x{image.height} is larger than the model sees unscaled")
    for quality in range(QUALITY, 59, -5):
        image.save(path, "JPEG", quality=quality)
        if path.stat().st_size <= MAX_BYTES:
            return quality
    raise ValueError(f"{path.name} won't fit in {MAX_BYTES} bytes")


def tile(pages, out, width, height, overlap):
    """Resample every page to `width`, then cut full-width tiles `height` tall for passes A and B.

    Consecutive tiles overlap by `overlap` pixels, more than the tallest cell on the ad, so every
    cell is whole in at least one tile. Pass B's tiles are offset by half a step, so a cell that
    sits on a tile edge in pass A sits mid-tile in pass B. Returns the manifest, which maps each
    tile back to its page.
    """
    out.mkdir(parents=True, exist_ok=True)
    step = height - overlap
    manifest = {"width": width, "height": height, "overlap": overlap, "pages": [], "tiles": []}
    for n, path in enumerate(pages, 1):
        source = Image.open(path).convert("RGB")
        scale = width / source.width
        page = source.resize((width, round(source.height * scale)), Image.Resampling.LANCZOS)
        manifest["pages"].append(
            {"page": n, "file": path.name, "size": list(source.size), "scale": scale, "height": page.height}
        )
        for pass_, offset in (("a", 0), ("b", step // 2)):
            y, i = -offset, 1
            while True:
                top, bottom = max(y, 0), min(y + height, page.height)
                tile_id = f"{pass_}{n}-{i}"  # "a1-2": pass A, page 1, second tile from the top
                quality = save(page.crop((0, top, width, bottom)), out / f"{tile_id}.jpg")
                manifest["tiles"].append({"id": tile_id, "pass": pass_, "page": n, "top": top, "bottom": bottom, "quality": quality})
                if y + height >= page.height:
                    break
                y, i = y + step, i + 1
    return manifest


def crop(manifest, pages_dir, page, box, out, zoom=2.0, margin=0.75):
    """A generous crop around `box` (page coordinates at working width), saved to `out`.

    It is cut from the original page and enlarged `zoom` times more than the tiles were, as far
    as the image limits allow. `margin` is the context added on each side, as a fraction of the
    box's size.
    """
    info = manifest["pages"][page - 1]
    image = Image.open(pages_dir / info["file"]).convert("RGB")
    x0, y0, x1, y1 = (v / info["scale"] for v in box)  # back to the page's own pixels
    pad_x, pad_y = max(40, (x1 - x0) * margin), max(40, (y1 - y0) * margin)
    region = image.crop(
        (max(0, int(x0 - pad_x)), max(0, int(y0 - pad_y)), min(image.width, int(x1 + pad_x)), min(image.height, int(y1 + pad_y)))
    )
    fit = min(info["scale"] * zoom, MAX_SIDE / region.width, MAX_SIDE / region.height)
    while patches(round(region.width * fit), round(region.height * fit)) > MAX_PATCHES:
        fit *= 0.95
    enlarged = region.resize((round(region.width * fit), round(region.height * fit)), Image.Resampling.LANCZOS)
    while True:  # a big crop may need to shrink to fit the byte limit at a good quality
        try:
            save(enlarged, out)
            return out
        except ValueError:
            enlarged = enlarged.resize((round(enlarged.width * 0.9), round(enlarged.height * 0.9)), Image.Resampling.LANCZOS)
