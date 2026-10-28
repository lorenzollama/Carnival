import datetime as dt
import subprocess
import sys

import pytest

from carnival import ROOT, run


def test_the_hourly_check_needs_only_the_standard_library():
    # The workflow installs Pillow, poppler, and Claude Code only when there's an ad to process.
    code = "import sys; sys.modules['PIL'] = None; import carnival.run, carnival.__main__"
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


@pytest.mark.parametrize(
    "local, overdue",
    [
        ("2026-10-27 09:49", None),  # Tuesday: the ad usually goes up this morning
        ("2026-10-28 17:59", None),  # Wednesday, a minute early
        ("2026-10-28 18:00", "2026-10-27"),
        ("2026-11-02 23:00", "2026-10-27"),  # Monday: still that week
        ("2026-11-03 08:00", None),  # the next Tuesday starts a new week
    ],
)
def test_staleness_deadline_is_wednesday_6_pm_in_san_diego(local, overdue):
    when = dt.datetime.fromisoformat(local).replace(tzinfo=run.LA)
    assert run.overdue_week(when) == (dt.date.fromisoformat(overdue) if overdue else None)
