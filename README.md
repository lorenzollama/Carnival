# Carnival deals bot

Every Tuesday, Carnival Supermarket in San Diego posts its weekly ad: two pages, about 85 offers,
no text layer. This repo checks for it every hour, keeps the deals that fit a lean,
cook-for-yourself diet, and sends them to Telegram:

```
Carnival · Oct 27 – Nov 2
Chicken leg meat 89¢/lb Friday · chicken milanesa $2.99/lb Tue–Thu

Protein · grams of protein per $
Chicken leg meat — 89¢/lb · 64 g/$ · Fri
Chicken drumsticks, plain or marinated — 99¢/lb · 53 g/$
Chicken thighs, plain, adobado or marinated — $1.29/lb · 48 g/$
Chicken milanesa — $2.99/lb · 34 g/$ · Tue–Thu
Tilapia fillet — $3.99/lb · 23 g/$
…
Produce (14)
Pantry (12)

Full ad
```

(Produce and pantry fold open in Telegram. When something can't be read, a ⚠️ line lists
what's legible and a photo of the spot follows.)

It runs free on GitHub Actions, and Claude runs on a Claude subscription (never an API key).
Accuracy comes first: a wrong price is worse than a missing one, so the ad is read twice,
every disagreement gets a closer look, and anything that still can't be read is flagged with a
photo instead of guessed.

## How it works

One workflow, [`.github/workflows/carnival.yml`](.github/workflows/carnival.yml), runs hourly.
Python does everything deterministic; Claude only reads and judges, in separate headless
`claude -p` calls that can read and write files in one folder and nothing else.

1. **Check** (seconds, standard library): a conditional GET of the store's PDF and a SHA-256
   against what's already in `data/`. Only a new file goes further.
2. **Pages**: `pdfimages` copies the PDF's page JPEGs out byte for byte. The texted PNG is split
   at its transparent gap.
3. **Tiles**: every page is resampled to a working width and cut into overlapping tiles sized to
   reach the model exactly as cut (see below).
4. **Transcribe twice**: two Claude processes read the tiles independently, with pass B's tiles
   offset by half a step. Prompt: [`prompts/transcribe.md`](prompts/transcribe.md).
5. **Reconcile** in Python: readings of the same cell are grouped by position and name; any
   field the passes disagree on, and any cell only one pass found, is disputed.
6. **Resolve**: Claude gets an enlarged crop of each disputed cell and both readings, and
   returns what's printed or "unreadable", never a guess. Prompt:
   [`prompts/resolve.md`](prompts/resolve.md).
7. **Check** in Python: the week starts on a Tuesday and runs seven days, the sale windows fall
   inside it in order, the item count looks like a whole ad, and the week is new.
8. **Filter**: Claude sorts each item against [`diet.md`](diet.md) and maps protein to rows of
   [`nutrition.csv`](nutrition.csv); Python applies the protein rule and computes grams of
   protein per dollar. Prompt: [`prompts/filter.md`](prompts/filter.md).
9. **Message**: rendered from JSON, under Telegram's limit, headline checked against the kept
   items' printed prices.
10. **Archive, send, record**: the week's folder is committed, then the message is sent, then
    the send is recorded. A failure at any step resumes there on the next hourly run.

The repo is the state. `data/<week-start>/` holds the source file exactly as downloaded, both
raw passes, the tile manifest, the resolution log, the reconciled transcript (every item), the
filter output with cut reasons, the exact message, and `meta.json` (URLs, hashes, model, run,
timestamps, Telegram message IDs). An ad being worked on lives in `data/pending/` until it's
done. A new file for the same week is processed as a revision, and you hear about it only if
the kept deals changed. If no ad has arrived by Wednesday 6 PM, you get one short notice with a
link to paste the texted ad link into the **Run workflow** form.

## Setup

You need a GitHub account, a Claude Pro or Max subscription, and Telegram.

1. **Fork or copy this repo**, keep it public (Actions minutes are free for public repos), and
   make `main` the default branch: the hourly schedule only runs there.
2. **Create the bot.** In Telegram, message [@BotFather](https://t.me/BotFather), send
   `/newbot`, and follow the prompts. Keep the token it gives you. Then open a chat with your new
   bot and send it any message.
3. **Find your chat ID** with the token from step 2 (it asks for the token, hidden):

   ```bash
   python3 tools/chat_id.py
   ```

4. **Create a Claude token** for your subscription. It lasts a year:

   ```bash
   claude setup-token
   ```

5. **Add three repository secrets**: on GitHub, **Settings → Secrets and variables → Actions →
   New repository secret**, once each for `CLAUDE_CODE_OAUTH_TOKEN` (step 4),
   `TELEGRAM_BOT_TOKEN` (step 2), and `TELEGRAM_CHAT_ID` (step 3). Or, with the GitHub CLI, run
   `gh secret set CLAUDE_CODE_OAUTH_TOKEN` and paste the value when it asks.
6. **Try it**: **Actions → Carnival weekly ad → Run workflow**. Leave the link empty to use the
   store's PDF, or paste the ad link the store texts you. Tick **force** to redo a week.

Never put `ANTHROPIC_API_KEY` in the secrets: every Claude step refuses to run when it's set,
so this can't quietly bill an API account.

## Running locally

```bash
brew install poppler        # for pdfimages
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
claude auth login           # once, with your Claude subscription
.venv/bin/python -m carnival --dry-run                                    # this week's ad
.venv/bin/python -m carnival --dry-run --file tests/fixtures/2026-09-22.png
.venv/bin/python -m pytest
```

A dry run works in `work/dry-run/`, prints the message, and commits and sends nothing; rerun it
and it reuses the Claude steps already done. Without `--dry-run`, `python -m carnival` does
exactly what the workflow does, including committing to `data/` and sending to Telegram (set
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`).

## Changing the diet

Edit [`diet.md`](diet.md). The two numbers the code uses live in its front matter
(`protein_min_g_per_100kcal`, `skip_min_purchase_coupons`); everything else is plain English
that Claude follows. Protein figures come only from [`nutrition.csv`](nutrition.csv): USDA
FoodData Central IDs, protein and kcal per 100 g raw, edible yield, and a collagen flag. If an
item matches no row, Claude proposes one; it's added marked `verified=no` and the commit says
so, so check the FDC ID when that happens.

Grams of protein per dollar = 453.592 × yield × (protein per 100 g ÷ 100) ÷ price per lb.

## How tiles are sized

Small print is where transcription goes wrong, so every tile should reach the model exactly as
cut: no downscaling, no recompression. Claude Code reads an image file and processes it before
the model sees it, so I measured what it does, with [`tools/image_probe.py`](tools/image_probe.py)
(Claude Code 2.1.308, `claude-opus-5-5`). It cuts test images from the ad, has a headless
session Read each one, and decodes the image that ended up in the conversation:

| Sent | File | Reached the model | Input tokens |
|---|---|---|---|
| 1000×1000 PNG | 1.7 MB | JPEG, 1000×1000 | 1,410 |
| 1400×2000 PNG | 4.2 MB | JPEG, 1400×2000 | 3,714 |
| 1874×1960 PNG | 4.7 MB | JPEG, 1874×1960 | 4,804 |
| 1960×1960 PNG | 4.8 MB | JPEG, **1932×1932** | 4,923 |
| 2600×1300 PNG | 3.6 MB | JPEG, **2000×1000** | 2,754 |
| 400×400 PNG | 236 KB | the same bytes | |
| 1400×2000 JPEG | 509 KB | the same bytes | |
| 1400×2000 JPEG | 528 KB | **re-encoded, 503 KB** | |

Three findings:

- **Tokens are 28×28-pixel patches.** An image costs ⌈width/28⌉ × ⌈height/28⌉ tokens, plus
  about 114 for the Read call (and 48 more for a note when Claude Code has resized it).
- **Sizes are capped at 2,000 px a side and about 4,750 patches.** 1874×1960 (4,690 patches)
  arrived intact; 1960×1960 (4,900) was scaled down to 1932×1932 (4,761).
- **Files over 512 KB are re-encoded**, whatever their format, as a JPEG of about 500 KB at
  roughly quality 68. That's the limit that binds: a full 1400×2000 tile fits in 500 KB only at
  quality 68 or so.

So tiles are JPEGs at quality 90 (stepping down only if one wouldn't fit), at most 500 KB,
2,000 px a side, and 4,700 patches. At quality 90 a full-width tile of this ad fits in 500 KB up
to about 1,100 px tall at a 1,400 px working width (1,270 at 937, 990 at 1,874), which is what
sets the tile height.

## Tuning

The working width was chosen on three past ads. The Oct 27 – Nov 2 PDF has a reference
transcription in [`tests/golden/`](tests/golden/2026-10-27.json), checked by hand against
3×–6× crops of the page images: 84 items and 3 coupons, with the 5 size lines too degraded to
be sure of left unscored. The texted PNGs for Sep 22 and Sep 29 are in
[`tests/fixtures/`](tests/fixtures/). For each setting,
[`tools/evaluate.py`](tools/evaluate.py) runs both passes and reports how often they agree and,
on the golden ad, every field each pass got wrong:

| Working width | Tiles per pass | Golden ad: fields wrong, pass A / B | Cells both passes agree on: golden / Sep 22 / Sep 29 | Tokens per ad |
|---|---|---|---|---|
| 937 px (the PDF's own) | 4–6 | 1 / 3 | 92% / 95% / 86% | 0.3M in, 41k out |
| **1400 px** | 10–12 | **0 / 0** | 92% / 100% / 92% | 0.9M in, 55k out |
| 1874 px (2×) | 26–28 | 0 / 0 | 94% / 100% / 94% | 3.8M in, 90k out |

At the PDF's own width, the small `LB.` and `EA.` beside a price were the casualties: three
times a pass read 99¢/lb as plain 99¢, which would have priced the drumsticks per piece.
Upscaling to 1400 px fixed that. 1874 px agreed slightly more often, but read 2.5 times as many
tiles for 4.5 times the tokens and no fewer errors, and every disagreement goes to the resolver
anyway. The same golden scored the texted PNG of the Oct 27 ad (1200 px wide) at 1400 px with a
single error, a `99¢ EA.` the other pass read correctly, so it was disputed rather than missed.
At every setting, no wrong value got past both passes at once: what remained was a `?` the
model wrote for a character it couldn't read, or a size line the golden itself couldn't settle.

The overlap isn't a free choice: it has to exceed the tallest cell, which on this ad is about a
third of the page width (page 2's cereal block, the coupons), so it's 500 px at 1400. Tile
height then follows from the 500 KB limit. At that setting both passes found every cell (one
of them they flagged as unreadable). A whole ad runs 73 to 84 items on these three, and the
check step expects 60 to 110.

## Security

The ad, and the link pasted into the Run workflow form, are untrusted input.

- The form's link reaches Python through an environment variable, never a shell command. Only
  https links on the hosts this ad comes from are fetched, and every redirect hop is checked
  against the same list. Chula Vista's ad (`/ad/`) is refused by path.
- Each Claude step runs with exactly two tools, Read and Write, in a folder holding only its
  inputs. A probe in the same setup confirmed that reading `/etc/hosts` and writing `../x`
  were both denied, and that no shell or web tool exists. The machine's own Claude settings,
  hooks, plugins, and MCP servers aren't loaded.
- The prompts tell Claude that anything printed on the ad is data, and Python validates every
  JSON file it writes, so text on the ad can at worst produce a bad transcription, which the
  second pass and the checks are there to catch.
- Actions are pinned to commit SHAs, and Claude Code, Python, and Pillow to exact versions.
  poppler comes from the pinned runner image's Ubuntu 24.04 archive (24.02).
