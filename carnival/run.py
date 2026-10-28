"""The steps in order, and the state that lets a failed run pick up where it stopped.

The repo is the state. data/<week-start>/ holds everything about one week's ad, and its
meta.json says whether the message went out. An ad still being worked on lives in data/pending/,
which is committed when a run fails, so the next hourly run resumes at the failed step instead
of starting over. data/notices.json remembers the one-off notices already sent.
"""

import datetime as dt
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from . import ROOT, claude, diet, fetch, message, telegram, transcribe

DATA, WORK = ROOT / "data", ROOT / "work"
PENDING, NOTICES = DATA / "pending", DATA / "notices.json"
WIDTH, HEIGHT, OVERLAP = 1400, 1050, 500  # working width, tile height, tile overlap (px): see README, "Tuning"
MAX_ATTEMPTS = 6  # hourly tries at one file before waiting for a new one, or for force
LA = ZoneInfo("America/Los_Angeles")


def check(source=None, force=False):
    """The cheap hourly step (standard library only). True when there's an ad to process."""
    for folder in weeks():
        if read(folder / "meta.json")["status"] == "processed":
            deliver(folder)  # the send failed last time
    stage(PENDING, source, force)
    meta = read(PENDING / "meta.json")
    if not meta:
        stale_notice()
        return False
    if meta["status"] == "rejected" or meta["attempts"] >= MAX_ATTEMPTS:
        print(f"data/pending failed {meta['attempts']} time(s); waiting for a new file, or for force.")
        return False
    return True


def stage(folder, source=None, force=False, path=None, history=True):
    """Download the ad into `folder` unless it's a file we've already seen. True if staged."""
    known = [read(f / "meta.json") for f in (weeks() if history else [])] + [read(folder / "meta.json")]
    known = [m for m in known if m]
    seen = {s["sha256"] for m in known for s in [m["source"], *m.get("replaced", [])]}
    if path:
        body = Path(path).read_bytes()
        got = fetch.Download(body, {"url": str(path), **fetch.identify(body)})
    else:
        last = next((m["source"] for m in reversed(known) if m["source"]["url"] == fetch.STORE_PDF), {})
        validators = (last.get("etag"), last.get("last_modified")) if not (source or force) else ()
        got = fetch.download(source or fetch.STORE_PDF, *validators)
        if got is None:
            print("The store's ad hasn't changed since the last fetch.")
            return False
    if got.meta["sha256"] in seen and not force:
        print(f"Already have this file ({got.meta['sha256'][:12]}).")
        return False
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    (folder / got.filename).write_bytes(got.body)
    write(folder / "meta.json", {"status": "pending", "attempts": 0, "force": force, "source": {**got.meta, "fetched_at": now()}})
    print(f"Staged a new {got.meta['kind']} ({got.meta['sha256'][:12]}) from {got.meta['url']}")
    return True


def process(folder=PENDING, dry_run=False):
    """The heavy step: transcribe, check, filter, archive, send. Returns the message."""
    meta = read(folder / "meta.json")
    work = WORK / meta["source"]["sha256"][:12]
    try:
        transcript, judged, picks, added, manifest = pipeline(folder, work, dry_run)
    except Exception as error:
        fail(folder, meta, error, dry_run, final=isinstance(error, transcribe.CheckFailed))
        raise
    dest = archive(folder, work, meta, transcript, judged, picks, added, manifest, dry_run)
    if not dry_run and read(dest / "meta.json")["status"] == "processed":
        deliver(dest)
    return (dest / "message.html").read_text()


def pipeline(folder, work, dry_run):
    """Steps 2-8. Each Claude step's output is saved the moment it exists and reused on a rerun."""
    from . import pages  # Pillow and poppler: installed only when there is an ad to process

    source = next(folder.glob("source.*"))
    saved = read(folder / "tiles.json") or {"width": WIDTH, "height": HEIGHT, "overlap": OVERLAP}
    manifest = pages.tile(pages.extract(source, work / "pages"), work / "tiles", saved["width"], saved["height"], saved["overlap"])
    write(folder / "tiles.json", manifest)

    missing = [p for p in "ab" if not (folder / f"pass-{p}.json").exists()]
    print(f"Transcribing: pass {' and '.join(missing).upper()}" if missing else "Both passes already done.")
    with ThreadPoolExecutor(2) as pool:
        running = {p: pool.submit(transcribe.transcribe, work, manifest, p) for p in missing}
    errors = []
    for p, future in running.items():
        try:
            write(folder / f"pass-{p}.json", future.result())
        except Exception as e:
            errors.append(e)
    if errors:
        raise errors[0]
    passes = [read(folder / f"pass-{p}.json") for p in "ab"]

    groups = transcribe.group(transcribe.readings(passes, manifest))
    if not (folder / "resolutions.json").exists():
        cases = transcribe.disputes(groups)
        print(f"Reconciled {len(groups)} cells: {len(cases)} need a closer look.")
        resolved, usage = transcribe.resolve(work, manifest, cases) if cases else ([], [])
        write(folder / "resolutions.json", {"cases": resolved, "usage": usage})
    transcript = transcribe.assemble(passes, groups, read(folder / "resolutions.json")["cases"])
    write(folder / "transcript.json", transcript)
    transcribe.check(transcript, None if dry_run or not weeks() else weeks()[-1].name)

    settings = diet.rules()
    if not (folder / "filter.json").exists():
        sorted_items, usage = diet.sort(work, transcript, settings)
        write(folder / "filter.json", {**sorted_items, "usage": usage})
    sorted_items = read(folder / "filter.json")
    table = diet.nutrition()
    added = [r for r in sorted_items["new_nutrition"] if r["key"] not in table]
    table.update({r["key"]: diet.typed(r) for r in added})
    judged = diet.judge(transcript, sorted_items, table, settings)
    return transcript, judged, sorted_items["headline"], added, manifest


def archive(folder, work, meta, transcript, judged, picks, added, manifest, dry_run):
    """Render the message and photos, then move the folder to data/<week-start>/ and commit it."""
    from . import pages

    week = transcript["week"]["start"]
    dest = folder if dry_run else DATA / week
    previous = None if dry_run else read(dest / "meta.json")
    source = next(folder.glob("source.*"))
    full_ad = f"https://github.com/{repo()}/blob/main/data/{week}/{source.name}"
    html = message.render(transcript, judged, picks, full_ad, revised=bool(previous))
    unchanged = bool(previous) and not meta["force"] and message.lines(transcript, judged) == message.lines(
        read(dest / "transcript.json"), read(dest / "verdicts.json")
    )
    write(folder / "verdicts.json", judged)
    (folder / "message.html").write_text(html + "\n")
    for n, spot in enumerate(transcript["unreadable"], 1):
        pages.crop(manifest, work / "pages", spot["page"], spot["box"], folder / f"unreadable-{n}.jpg", zoom=1.5)
    kept, total = sum(d["kept"] for d in judged), len(judged) + len(transcript["unreadable"])
    usage = [u for name in ("pass-a", "pass-b", "resolutions", "filter") for u in read(folder / f"{name}.json")["usage"]]
    meta.update(
        status="unchanged" if unchanged else "processed", week=week, kept=kept, items=total, processed_at=now(),
        run=run_url(), revision=previous["revision"] + 1 if previous else 1,
        claude={"models": sorted({m for u in usage for m in u["models"]}), "version": claude.version()},
        tiles={k: manifest[k] for k in ("width", "height", "overlap")},
    )  # fmt: skip
    if previous:
        meta["replaced"] = [previous["source"], *previous.get("replaced", [])]
    write(folder / "meta.json", meta)
    if dry_run:
        return folder
    shutil.rmtree(dest, ignore_errors=True)
    folder.rename(dest)
    if added:
        diet.add_rows(added)
    subject = f"{message.week_label(week, year=True)}: {kept} of {total} items kept"
    if previous:
        subject += f" (revision {meta['revision']}{', deals unchanged' if unchanged else ''})"
    if added:
        subject += f"; {len(added)} unverified nutrition row{'s' * (len(added) > 1)} added"
    commit(subject)
    return dest


def deliver(folder):
    """Send a processed week's message, then a photo of each unreadable spot, recording as we go."""
    meta = read(folder / "meta.json")
    sent = meta.setdefault("telegram", {}).setdefault("message_ids", [])
    try:
        if not sent:
            sent.append(telegram.send_message((folder / "message.html").read_text().strip()))
        for n, caption in enumerate(message.captions(read(folder / "transcript.json")), 1):
            if len(sent) <= n:
                sent.append(telegram.send_photo(folder / f"unreadable-{n}.jpg", caption, reply_to=sent[0]))
        meta["status"], meta["telegram"]["sent_at"] = "sent", now()
    finally:
        write(folder / "meta.json", meta)
        label = message.week_label(meta["week"], year=True)
        commit(f"Sent the {label} deals" if meta["status"] == "sent" else f"Sending the {label} deals failed partway")


def fail(folder, meta, error, dry_run, final=False):
    """Record a failed attempt, and tell me once per source file."""
    meta["attempts"] += 1
    meta["status"] = "rejected" if final else meta["status"]
    meta.setdefault("errors", []).append({"at": now(), "run": run_url(), "error": f"{type(error).__name__}: {error}"[:1000]})
    write(folder / "meta.json", meta)
    if dry_run:
        return
    commit(f"Couldn't process the new ad (attempt {meta['attempts']}{', giving up' if final else ''})")
    reason = escape(str(error).splitlines()[0][:200] if str(error) else type(error).__name__, quote=False)
    log = f'<a href="{run_url()}">Run log</a>' if run_url() else "See the terminal."
    notify("failure", meta["source"]["sha256"], f"<b>Carnival</b>: couldn't process the new ad ({reason}). {log}")


def stale_notice():
    """No ad for this week by Wednesday 6 PM in San Diego: say so, once."""
    start = overdue_week(dt.datetime.now(LA))
    if not start or any(w.name >= start.isoformat() for w in weeks()):
        return
    form = f"https://github.com/{repo()}/actions/workflows/carnival.yml"
    notify("stale", start.isoformat(), f"<b>Carnival · {message.week_label(start.isoformat())}</b>\n"
           f'No new ad yet. If the store texted you a link, paste it into <a href="{form}">Run workflow</a>.')  # fmt: skip


def overdue_week(local):
    """This ad week's Tuesday once it's past Wednesday 6 PM, San Diego time; before that, None."""
    start = local.date() - dt.timedelta(days=(local.weekday() - 1) % 7)
    return start if local >= dt.datetime.combine(start + dt.timedelta(days=1), dt.time(18), LA) else None


def notify(kind, key, html):
    """Send a one-off notice, unless one of this kind already went out for this key."""
    notices = read(NOTICES, [])
    if any(n["kind"] == kind and n["key"] == key for n in notices):
        return
    notices.append({"kind": kind, "key": key, "sent_at": now(), "message_id": telegram.send_message(html)})
    write(NOTICES, notices)
    commit(f"Sent a {kind} notice ({key[:12]})")


# State and plumbing --------------------------------------------------------------------------


def weeks():
    """Folders of processed ads, oldest first."""
    return sorted(p for p in DATA.glob("20??-??-??") if (p / "meta.json").exists())


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write(path, data):
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def repo():
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True).stdout
    return re.sub(r"^(git@github\.com:|https://github\.com/)|\.git$", "", url.strip())


def run_url():
    env = os.environ
    if env.get("GITHUB_RUN_ID"):
        return f"{env['GITHUB_SERVER_URL']}/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
    return None


def commit(subject):
    """Commit everything under data/ (and nutrition.csv), then push, retrying over a race."""

    def git(*args, check=True):
        return subprocess.run(["git", *args], cwd=ROOT, check=check)

    git("add", "--all", "data", "nutrition.csv")
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return
    git("commit", "--quiet", "-m", subject)
    for _ in range(3):
        if git("push", "--quiet", check=False).returncode == 0:
            return
        git("pull", "--rebase", "--quiet")
    raise RuntimeError("couldn't push to GitHub")
