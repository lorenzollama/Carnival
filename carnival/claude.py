"""Run one Claude step: a prompt file, some input files, and JSON output that Python checks.

Each step is its own headless `claude -p` process on Opus. Claude gets two tools, Read and
Write, confined to the step's working directory: no shell, no network, nothing from this
machine's own Claude configuration. It reads its inputs, writes JSON files, and exits; Python
validates every file, retries once with the errors spelled out, then gives up cleanly.
"""

import json
import os
import shutil
import subprocess
import time

from . import ROOT

MODEL = "opus"
TIMEOUT = 45 * 60


class StepFailed(RuntimeError):
    pass


def run(name, workdir, outputs, validate, inputs=""):
    """Run prompts/<name>.md in `workdir`; return ({output file: validated JSON}, usage).

    `outputs` are the files Claude must write there; `validate(file, data)` raises ValueError
    when one is wrong. `inputs` is appended to the prompt to describe this run's files.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        raise StepFailed(
            "ANTHROPIC_API_KEY is set, so Claude Code would bill the API instead of your subscription. "
            "Unset it; this bot runs on `claude setup-token` (CLAUDE_CODE_OAUTH_TOKEN) or your own login."
        )
    prompt = (ROOT / "prompts" / f"{name}.md").read_text() + "\n" + inputs
    usage = []
    for attempt in (1, 2):
        for f in outputs:
            (workdir / f).unlink(missing_ok=True)
        usage.append(_claude(prompt, workdir))
        errors = []
        results = {}
        for f in outputs:
            try:
                results[f] = json.loads((workdir / f).read_text())
                validate(f, results[f])
            except (OSError, ValueError, KeyError, TypeError) as e:
                errors.append(f"{f}: {e}")
        if not errors:
            return results, usage
        print(f"[{name}] attempt {attempt} produced invalid output:\n  " + "\n  ".join(errors))
        prompt += (
            "\n\n## Your previous attempt was rejected\n\nThese files were missing or invalid; "
            "write all of them again, following the format exactly:\n\n" + "\n".join(f"- {e}" for e in errors)
        )
    raise StepFailed(f"{name}: invalid output twice: {'; '.join(errors)[:300]}")


def version():
    """The installed Claude Code version, for the record."""
    out = subprocess.run([_binary(), "--version"], capture_output=True, text=True)
    return out.stdout.split(" ")[0].strip() or None


def _binary():
    return os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"


def _claude(prompt, workdir):
    """One `claude -p` process. Returns what it reported about itself."""
    command = [
        _binary(),
        "--print",
        "--model", MODEL,
        "--tools", "Read,Write",  # the only tools that exist in this session
        "--permission-mode", "acceptEdits",  # writes allowed inside workdir, nowhere else
        "--setting-sources", "",  # ignore this machine's settings, hooks, and plugins
        "--strict-mcp-config",  # and its MCP servers
        "--no-session-persistence",
        "--output-format", "json",
    ]  # fmt: skip
    started = time.monotonic()
    proc = subprocess.run(command, input=prompt, cwd=workdir, capture_output=True, text=True, timeout=TIMEOUT)
    try:
        report = json.loads(proc.stdout)
    except ValueError:
        raise StepFailed(f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:300]}") from None
    if report.get("is_error") or proc.returncode:
        raise StepFailed(f"claude: {str(report.get('result'))[:300]}")
    return {
        "models": sorted(report.get("modelUsage", {})),
        "seconds": round(time.monotonic() - started),
        "turns": report.get("num_turns"),
        "usage": {k: v for k, v in report.get("usage", {}).items() if k.endswith("tokens")},
    }
