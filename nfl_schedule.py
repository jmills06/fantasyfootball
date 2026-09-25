"""NFL week timing shared by both collectors.

Two jobs:

1. hold_previous_week(): the leagues' own "current week" rolls forward
   overnight Monday into Tuesday. The board follows it from Tuesday 04:00 ET,
   so the upcoming matchup shows all week, but not a moment before Monday
   night football is safely over.

2. game_windows(): the stretches of the anchor week when NFL games are on
   (Thursday night, Sunday, Monday night, plus any Saturday or holiday game),
   taken from ESPN's public NFL scoreboard. The board goes LIVE inside these
   windows rather than by day of week. If the scoreboard cannot be fetched,
   a fixed Thu/Sun/Mon pattern is used so the board still flips on game days.

The scoreboard is public and needs no auth. Nothing here touches the ESPN
fantasy cookies, and a failed fetch logs only the status, never a body.
"""

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

SCOREBOARD = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
              "scoreboard?dates={season}&seasontype=2&week={week}")
UA = "Mozilla/5.0 (compatible; fantasyfootball-collector/1.0)"

ROLLOVER_HOUR_ET = 4                 # Tuesday 04:00 ET: new week takes over
PREGAME = timedelta(minutes=30)      # go LIVE a little before kickoff
GAME_LENGTH = timedelta(hours=4)     # covers overtime and long reviews


# ------------------------------------------------------------ eastern time

def _eastern_offset(utc):
    """UTC offset for US Eastern at a UTC instant.

    zoneinfo is not used because it needs the tzdata package on Windows,
    and the owner runs these collectors there by hand. US DST: second Sunday
    of March 02:00 local to first Sunday of November 02:00 local.
    """
    y = utc.year

    def nth_sunday(month, n):
        d = datetime(y, month, 1, tzinfo=timezone.utc)
        d += timedelta(days=(6 - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)

    dst_start = nth_sunday(3, 2) + timedelta(hours=7)   # 02:00 EST = 07:00Z
    dst_end = nth_sunday(11, 1) + timedelta(hours=6)    # 02:00 EDT = 06:00Z
    return timedelta(hours=-4) if dst_start <= utc < dst_end else timedelta(hours=-5)


def to_eastern(utc):
    return (utc + _eastern_offset(utc)).replace(tzinfo=None)


def from_eastern(naive_et):
    """Naive Eastern wall time -> aware UTC."""
    guess = naive_et.replace(tzinfo=timezone.utc) + timedelta(hours=5)
    return (naive_et - _eastern_offset(guess)).replace(tzinfo=timezone.utc)


def week_start(now=None):
    """Most recent Tuesday 04:00 ET at or before now, as aware UTC."""
    now = now or datetime.now(timezone.utc)
    et = to_eastern(now)
    days_back = (et.weekday() - 1) % 7            # Monday=0, Tuesday=1
    start = (et - timedelta(days=days_back)).replace(
        hour=ROLLOVER_HOUR_ET, minute=0, second=0, microsecond=0)
    if start > et:
        start -= timedelta(days=7)
    return from_eastern(start)


def hold_previous_week(now=None):
    """True from Monday 00:00 ET until the Tuesday rollover.

    The leagues roll their current week forward during this span, sometimes
    before the Monday night game has finished. Inside it the collectors stay
    on the week that has points; outside it they follow the league's week.
    """
    now = now or datetime.now(timezone.utc)
    et = to_eastern(now)
    return et.weekday() == 0 or (et.weekday() == 1 and et.hour < ROLLOVER_HOUR_ET)


# ----------------------------------------------------------------- windows

def _parse_utc(s):
    """ESPN dates look like 2026-09-25T00:15Z (no seconds)."""
    s = str(s).strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(s, fmt).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _kickoffs(season, week):
    url = SCOREBOARD.format(season=season, week=week)
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            doc = json.loads(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
        kind = getattr(e, "code", None) or getattr(e, "reason", type(e).__name__)
        print(f"  nfl schedule: week {week} unavailable ({kind})")
        return []
    out = []
    for ev in doc.get("events") or []:
        k = _parse_utc(ev.get("date"))
        if k:
            out.append(k)
    return sorted(out)


def _fallback_kickoffs(now=None):
    """Standard slots for the current Tue-Mon week, in ET: Thu 20:15,
    Sun 13:00 / 16:05 / 16:25 / 20:20, Mon 20:15."""
    start_et = to_eastern(week_start(now)).replace(hour=0)
    slots = [(2, 20, 15), (5, 13, 0), (5, 16, 5), (5, 16, 25), (5, 20, 20),
             (6, 20, 15)]
    return [from_eastern(start_et + timedelta(days=d, hours=h, minutes=m))
            for d, h, m in slots]


def _merge(kickoffs):
    spans = []
    for k in sorted(kickoffs):
        s, e = k - PREGAME, k + GAME_LENGTH
        if spans and s <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], e)
        else:
            spans.append([s, e])
    iso = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [{"start": iso(s), "end": iso(e)} for s, e in spans]


def game_windows(season, week, now=None):
    """Merged LIVE windows for one NFL week, as ISO UTC strings.

    Each game counts from 30 minutes before kickoff to 4 hours after, and
    overlapping games merge, so a Sunday reads as one block from the early
    kickoff through the night game.
    """
    kicks = _kickoffs(season, week) if week and week <= 18 else []
    source = "espn scoreboard"
    if not kicks:
        kicks = _fallback_kickoffs(now)
        source = "fallback Thu/Sun/Mon"
    windows = _merge(kicks)
    print(f"  nfl schedule: week {week}, {len(kicks)} kickoffs, "
          f"{len(windows)} windows ({source})")
    return windows


# -------------------------------------------------------------------- gate

SLOW_HOURS = 6    # outside game windows, refresh when data is this old


def gate(paths, now=None):
    """What one workflow run should do, from the payloads already on disk.

    Returns ("live", seconds_left_in_window), ("idle", 0) or ("skip", 0).
    One cron-job.org trigger every 30 minutes is all the workflow needs:
    inside a game window the run stays up and collects on a short loop until
    the window closes; outside one it collects only when the data is older
    than SLOW_HOURS, and otherwise exits in seconds.
    """
    now = now or datetime.now(timezone.utc)
    newest = None
    live_end = None
    refresh = False
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        u = _parse_utc(str(doc.get("updated", ""))[:16] + "Z")
        if u and (newest is None or u > newest):
            newest = u
        # Collect regardless of age when a payload cannot be trusted to carry
        # this week's windows: written before windows existed, or before the
        # latest Tuesday rollover (its windows are last week's). Without this
        # the gate waits out SLOW_HOURS before it ever sees a game window.
        if "windows" not in doc or not u or u < week_start(now):
            refresh = True
        for w in doc.get("windows") or []:
            s, e = _parse_utc(str(w.get("start", ""))[:16] + "Z"), \
                   _parse_utc(str(w.get("end", ""))[:16] + "Z")
            if s and e and s <= now < e:
                live_end = max(live_end or e, e)
    if live_end:
        return "live", int((live_end - now).total_seconds())
    if refresh or newest is None \
            or now - newest >= timedelta(hours=SLOW_HOURS) - timedelta(minutes=5):
        return "idle", 0
    return "skip", 0


if __name__ == "__main__":
    import sys
    mode, secs = gate(sys.argv[1:])
    print(f"{mode} {secs}")
