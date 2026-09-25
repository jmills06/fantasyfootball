#!/usr/bin/env python3
"""Sleeper league -> data/latest/sleeper.json

Writes the shared data contract (handoff section 5) that both boards render.
Everything here is built against real API responses captured in discovery;
see discovery/FINDINGS.md for what was confirmed and what was assumed.

Sleeper needs no auth. Failures preserve the last good file and set
"stale": true rather than blanking the board.

Usage:  py collect_sleeper.py
"""

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import nfl_schedule

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config" / "leagues.json"
OUT = ROOT / "data" / "latest" / "sleeper.json"
PLAYERS = ROOT / "data" / "latest" / "players.json"
UA = "Mozilla/5.0 (compatible; fantasyfootball-collector/1.0)"
MOVES_CAP = 8
MOVES_MAX_AGE_DAYS = 7   # only the last week of activity is interesting

# Slots that are not part of the starting lineup.
BENCH_SLOTS = {"BN", "TAXI", "IR"}


class FetchError(Exception):
    pass


def get(url, attempts=3):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
            if attempt == attempts:
                kind = getattr(e, "code", None) or getattr(e, "reason", e)
                raise FetchError(f"{url.rsplit('/', 2)[-2:]}: {kind}") from None
            time.sleep(2 ** attempt)


# ------------------------------------------------------------- presentation

def team_name(user):
    """metadata.team_name, falling back to display_name.

    Discovery: 7 of 8 managers set a team_name. Roster 2's owner did not,
    so this fallback is load-bearing, not theoretical.
    """
    if not user:
        return "Unclaimed"
    meta = user.get("metadata") or {}
    return meta.get("team_name") or user.get("display_name") or "Unclaimed"


def team_logo(user):
    """Custom upload, then the avatar hash, then nothing (board draws initials).

    Discovery: 5 of 8 have a custom upload, all 8 have a hash, so the
    initials fallback never fires in this league today. It still has to
    exist for a manager who clears their avatar.
    """
    if not user:
        return None
    meta = user.get("metadata") or {}
    if meta.get("avatar"):
        return meta["avatar"]
    if user.get("avatar"):
        return f"https://sleepercdn.com/avatars/thumbs/{user['avatar']}"
    return None


def record(settings):
    w = settings.get("wins", 0)
    l = settings.get("losses", 0)
    t = settings.get("ties", 0)
    return f"{w}-{l}-{t}" if t else f"{w}-{l}"


def ago(ms):
    if not ms:
        return ""
    secs = max(0, int(time.time() - ms / 1000))
    if secs < 3600:
        return f"{max(1, secs // 60)}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


# ------------------------------------------------------------------- points

def week_points(entry):
    """custom_points overrides points when a commissioner has adjusted a score."""
    cp = entry.get("custom_points")
    return float(cp if cp is not None else (entry.get("points") or 0.0))


def pair_up(week_entries):
    """Group a week's matchup entries by matchup_id -> [entry, entry]."""
    pairs = {}
    for e in week_entries or []:
        mid = e.get("matchup_id")
        if mid is None:
            continue
        pairs.setdefault(mid, []).append(e)
    return pairs


# --------------------------------------------------------------------- main

def build(cfg, players):
    base = cfg["base"]
    lg = cfg["leagueId"]

    state = get(f"{base}/v1/state/nfl")
    league = get(f"{base}/v1/league/{lg}")
    users = get(f"{base}/v1/league/{lg}/users")
    rosters = get(f"{base}/v1/league/{lg}/rosters")

    current = int(state.get("week") or 1)
    print(f"state: week={state.get('week')} display_week={state.get('display_week')}")

    # Pull every week up to and including next week. Needed anyway for the
    # streak walk, and it is what lets the anchor be chosen from data.
    weeks = {}
    for w in range(1, min(current + 1, 18) + 1):
        weeks[w] = get(f"{base}/v1/league/{lg}/matchups/{w}")

    # Anchor on the league's current week, which Sleeper rolls forward by
    # Tuesday morning (logs: week=3 display_week=2 on a Tuesday). That keeps
    # the upcoming matchup on the board from Tuesday through the weekend.
    # From Monday until the Tuesday 04:00 ET rollover, stay on the latest
    # week with points instead, so an early roll never cuts off Monday night.
    anchor = max(1, current)
    if nfl_schedule.hold_previous_week():
        scored = [w for w in sorted(weeks)
                  if w <= current and any(week_points(e) > 0 for e in weeks[w] or [])]
        if scored:
            anchor = scored[-1]
    print(f"anchor week: {anchor} (upcoming {anchor + 1})")

    # roster_positions is an ordered array, so the starting slots are just
    # the leading non-bench entries. 10 slots here: two FLEX, no kicker.
    slots = [s for s in league.get("roster_positions", []) if s not in BENCH_SLOTS]

    users_by_id = {u["user_id"]: u for u in users}
    rosters_by_id = {r["roster_id"]: r for r in rosters}

    # Identify "me" by user_id, which survives a roster_id renumbering.
    my_roster = None
    for r in rosters:
        if r.get("owner_id") == cfg["me"]["userId"]:
            my_roster = r["roster_id"]
            break
    if my_roster is None:
        my_roster = cfg["me"]["rosterId"]
        print(f"WARNING: userId not matched to any owner_id; "
              f"falling back to configured rosterId {my_roster}")
    elif my_roster != cfg["me"].get("rosterId"):
        print(f"WARNING: config rosterId {cfg['me'].get('rosterId')} "
              f"disagrees with derived {my_roster}; using derived")

    def owner(rid):
        r = rosters_by_id.get(rid) or {}
        return users_by_id.get(r.get("owner_id"))

    def side(rid):
        u = owner(rid)
        return {"n": team_name(u), "logo": team_logo(u)}

    # --- points for, and streak, from the weekly matchups ------------------
    # fpts/fpts_decimal are deliberately not used: every value was 0 at
    # discovery so the decimal field's scale could not be verified, while
    # summing weekly points is exact and needs no assumption.
    # Completed weeks only: the anchor week is the one being played (or about
    # to be), so counting it would add partial points and turn an unplayed
    # 0-0 into a tie in the streak.
    pf = {rid: 0.0 for rid in rosters_by_id}
    results = {rid: [] for rid in rosters_by_id}
    for w in range(1, anchor):
        for entries in pair_up(weeks.get(w)).values():
            if len(entries) != 2:
                continue
            a, b = entries
            ap, bp = week_points(a), week_points(b)
            for e in (a, b):
                pf[e["roster_id"]] = pf.get(e["roster_id"], 0.0) + week_points(e)
            if ap == bp:
                ra = rb = "T"
            else:
                ra, rb = ("W", "L") if ap > bp else ("L", "W")
            results[a["roster_id"]].append(ra)
            results[b["roster_id"]].append(rb)

    def streak(rid):
        seq = results.get(rid) or []
        if not seq:
            return ""
        last = seq[-1]
        n = 0
        for r in reversed(seq):
            if r != last:
                break
            n += 1
        return f"{last}{n}"

    # --- hero and lineup --------------------------------------------------
    anchor_pairs = pair_up(weeks.get(anchor))
    mine = opp = None
    for entries in anchor_pairs.values():
        ids = [e["roster_id"] for e in entries]
        if my_roster in ids and len(entries) == 2:
            mine = next(e for e in entries if e["roster_id"] == my_roster)
            opp = next(e for e in entries if e["roster_id"] != my_roster)
            break

    def hero_side(entry, me=False):
        if not entry:
            return {"name": "-", "rec": "", "pts": 0.0, "logo": None, "me": me}
        rid = entry["roster_id"]
        u = owner(rid)
        s = {
            "name": team_name(u),
            "rec": record((rosters_by_id.get(rid) or {}).get("settings") or {}),
            "pts": round(week_points(entry), 2),
            "logo": team_logo(u),
        }
        if me:
            s["me"] = True
        return s

    def name_of(pid):
        p = players.get(str(pid))
        return p["n"] if p else str(pid)

    def team_of(pid):
        p = players.get(str(pid))
        return (p.get("t") or "") if p else ""

    def pos_of(pid):
        p = players.get(str(pid))
        return (p.get("p") or "") if p else ""

    # Each NFL team's game this week, for the lineup grid's game line.
    games = nfl_schedule.team_games(cfg["season"], anchor)

    def slot_cell(entry, i):
        """One side of one lineup row.

        A 0 in starters means an empty slot. It gets its own row rather than
        being collapsed - the opposing side still takes the slot win.
        """
        if not entry:
            return {"empty": True, "p": 0.0}
        starters = entry.get("starters") or []
        pts = entry.get("starters_points") or []
        if i >= len(starters):
            return {"empty": True, "p": 0.0}
        pid = starters[i]
        p = round(float(pts[i]), 2) if i < len(pts) else 0.0
        if pid in (0, "0", None, ""):
            return {"empty": True, "p": p}
        cell = {"n": name_of(pid), "t": team_of(pid), "p": p}
        if pos_of(pid):
            cell["pos"] = pos_of(pid)
        g = nfl_schedule.game_for(games, cell["t"])
        if g:
            cell["g"] = g
        return cell

    lineup = [{"pos": slot, "a": slot_cell(mine, i), "b": slot_cell(opp, i)}
              for i, slot in enumerate(slots)]

    def bench_total(entry):
        """Everything scoring that is not a starter, excluding taxi and IR.

        Dynasty league: taxi and reserve players sit outside roster_positions
        and would inflate the bench number if counted.
        """
        if not entry:
            return 0.0
        rid = entry["roster_id"]
        r = rosters_by_id.get(rid) or {}
        excluded = set(str(p) for p in (entry.get("starters") or []))
        excluded |= set(str(p) for p in (r.get("taxi") or []))
        excluded |= set(str(p) for p in (r.get("reserve") or []))
        pp = entry.get("players_points") or {}
        return round(sum(v for k, v in pp.items() if str(k) not in excluded), 2)

    # --- other games in the anchor week -----------------------------------
    matchups = []
    for entries in anchor_pairs.values():
        if len(entries) != 2:
            continue
        if my_roster in [e["roster_id"] for e in entries]:
            continue
        a, b = entries
        matchups.append({
            "a": side(a["roster_id"]), "pa": round(week_points(a), 2),
            "b": side(b["roster_id"]), "pb": round(week_points(b), 2),
        })

    # --- next week's pairings ---------------------------------------------
    # Regular season only. The bracket endpoints return fabricated pairings
    # outside the playoffs, so they are not consulted here.
    upcoming_week = anchor + 1
    games = []
    if upcoming_week < int(league.get("settings", {}).get("playoff_week_start", 15)):
        for entries in pair_up(weeks.get(upcoming_week)).values():
            if len(entries) != 2:
                continue
            g = {}
            for key, e in zip(("a", "b"), entries):
                rid = e["roster_id"]
                u = owner(rid)
                g[key] = {
                    "n": team_name(u),
                    "rec": record((rosters_by_id.get(rid) or {}).get("settings") or {}),
                    "logo": team_logo(u),
                }
                if rid == my_roster:
                    g[key]["me"] = True
            games.append(g)

    # --- standings --------------------------------------------------------
    standings = []
    for r in rosters:
        rid = r["roster_id"]
        s = r.get("settings") or {}
        u = owner(rid)
        row = {
            "t": team_name(u),
            "w": s.get("wins", 0),
            "l": s.get("losses", 0),
            "pf": round(pf.get(rid, 0.0), 2),
            "s": streak(rid),
            "logo": team_logo(u),
            "me": rid == my_roster,
            # FAAB remaining. Carried on the row rather than as a separate
            # block because the board knows team names, not roster ids, and
            # a column costs no vertical space in the swap zone.
            "faab": cfg["faab"]["budget"] - s.get("waiver_budget_used", 0),
        }
        if s.get("ties"):
            row["ties"] = s["ties"]
        standings.append(row)
    standings.sort(key=lambda x: (-x["w"], -x["pf"]))

    # --- moves ------------------------------------------------------------
    moves = []
    tx = []
    for w in sorted({max(1, anchor - 1), anchor}):
        try:
            tx += get(f"{base}/v1/league/{lg}/transactions/{w}") or []
        except FetchError as e:
            print(f"WARNING: transactions week {w} unavailable ({e})")
    tx.sort(key=lambda t: t.get("created") or 0, reverse=True)

    cutoff_ms = (time.time() - MOVES_MAX_AGE_DAYS * 86400) * 1000
    for t in tx:
        if t.get("status") != "complete":
            continue  # drops failed waiver claims
        if (t.get("created") or 0) < cutoff_ms:
            # Sleeper files dynasty offseason cuts under leg 1, so without this
            # a quiet week shows moves from weeks ago.
            continue
        kind = t.get("type")
        adds, drops = t.get("adds") or {}, t.get("drops") or {}
        rids = t.get("roster_ids") or []
        when = ago(t.get("created"))
        if kind == "trade":
            if len(rids) >= 2:
                moves.append({
                    "k": "trade",
                    "txt": f"<b>{team_name(owner(rids[0]))}</b> traded with "
                           f"<b>{team_name(owner(rids[1]))}</b>",
                    "when": when,
                })
        elif adds:
            pid, rid = next(iter(adds.items()))
            verb = "claimed" if kind == "waiver" else "added"
            txt = f"<b>{team_name(owner(rid))}</b> {verb} {name_of(pid)}"
            if drops:
                txt += f", dropped {name_of(next(iter(drops)))}"
            moves.append({"k": "add", "txt": txt, "when": when})
        elif drops:
            pid, rid = next(iter(drops.items()))
            moves.append({
                "k": "drop",
                "txt": f"<b>{team_name(owner(rid))}</b> dropped {name_of(pid)}",
                "when": when,
            })
        if len(moves) >= MOVES_CAP:
            break

    return {
        "league": league.get("name") or cfg["league"],
        "platform": "sleeper",
        "week": anchor,
        "stale": False,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "playoffCut": cfg["playoffCut"],
        "faab": {"budget": cfg["faab"]["budget"]},
        "hero": {"a": hero_side(mine, me=True), "b": hero_side(opp)},
        "lineup": lineup,
        "bench": {"a": bench_total(mine), "b": bench_total(opp)},
        "matchups": matchups,
        "upcoming": {"week": upcoming_week, "games": games},
        "windows": nfl_schedule.game_windows(cfg["season"], anchor),
        "standings": standings,
        "moves": moves,
    }


def mark_stale(reason):
    """Preserve the last good file and flag it. Never blank the board."""
    if not OUT.exists():
        print(f"{reason}; no existing {OUT.name} to preserve")
        return 1
    try:
        data = json.loads(OUT.read_text())
    except ValueError:
        print(f"{reason}; existing {OUT.name} is unreadable, leaving it alone")
        return 1
    data["stale"] = True
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print(f"{reason}; preserved {OUT.name} and set stale")
    return 0


def main():
    cfg = json.loads(CONFIG.read_text())["sleeper"]

    players = {}
    if PLAYERS.exists():
        players = json.loads(PLAYERS.read_text()).get("players", {})
        print(f"player lookup: {len(players):,} entries")
    else:
        print(f"WARNING: {PLAYERS.name} missing - run collect_players.py. "
              f"Names will fall back to raw ids.")

    try:
        data = build(cfg, players)
    except FetchError as e:
        return mark_stale(f"fetch failed ({e})")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(OUT)

    print(f"wrote {OUT} - week {data['week']}, "
          f"{len(data['lineup'])} lineup rows, "
          f"{len(data['standings'])} standings rows, "
          f"{len(data['matchups'])} other games, "
          f"{len(data['moves'])} moves, {OUT.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
