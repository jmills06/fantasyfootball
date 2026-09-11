#!/usr/bin/env python3
"""Sleeper all-players lookup -> data/latest/players.json

The source file is ~5MB and changes slowly, so this runs once daily on its
own workflow. The main collector never calls it (handoff section 7).

Output is a trimmed id -> {n, t, p} map. Sleeper transactions carry no
display text at all - metadata is null on every record - so this lookup is
what turns a numeric player id into "Team claimed Player" in the moves block.

Usage:  py collect_players.py
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "latest" / "players.json"
URL = "https://api.sleeper.app/v1/players/nfl"
UA = "Mozilla/5.0 (compatible; fantasyfootball-collector/1.0)"

# Roster-eligible positions only. Keeps the file small without dropping
# anyone who can appear in a transaction. Free agents have team == None and
# must be kept, so never filter on team.
KEEP = {"QB", "RB", "WR", "TE", "K", "DEF"}


def preserve_and_exit(reason):
    """Never overwrite a good file with an error state."""
    if OUT.exists():
        print(f"{reason}; keeping existing {OUT.name}")
        return 0
    print(f"{reason}; no existing {OUT.name} to fall back on")
    return 1


def main():
    print(f"fetching {URL}")
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return preserve_and_exit(f"HTTP {e.code}")
    except urllib.error.URLError as e:
        return preserve_and_exit(f"network error: {getattr(e, 'reason', e)}")
    except ValueError:
        return preserve_and_exit("response was not JSON")

    if not isinstance(raw, dict) or len(raw) < 1000:
        # A truncated or unexpected payload is worse than yesterday's file.
        return preserve_and_exit(f"implausible payload ({type(raw).__name__})")

    players = {}
    for pid, p in raw.items():
        if not isinstance(p, dict):
            continue
        pos = p.get("position")
        if pos not in KEEP:
            continue
        name = p.get("full_name")
        if not name:
            # Team defences carry no full_name; they key off the team code.
            first, last = p.get("first_name") or "", p.get("last_name") or ""
            name = (first + " " + last).strip() or pid
        players[pid] = {
            "n": name,
            "t": p.get("team"),
            "p": pos,
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(players),
        "players": players,
    }, separators=(",", ":")))
    tmp.replace(OUT)

    print(f"wrote {OUT} - {len(players):,} of {len(raw):,} players, "
          f"{OUT.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
