#!/usr/bin/env python3
"""ESPN league -> data/latest/espn.json

Writes the same data contract as collect_sleeper.py so one renderer serves
both boards. See discovery/FINDINGS.md for what was verified against the
live API and what was inferred.

SECURITY - see CLAUDE.md section 1. This is a public repo and these cookies
are full ESPN account access:
  * ESPN_S2 / ESPN_SWID are read from os.environ only
  * cookie values, the cookie dict and request headers are never logged,
    printed, or written to disk
  * a failed response body is never read, logged, or stored - on a 401 the
    status code is recorded and nothing else
  * raw responses never reach data/latest/; only normalized fields do
  * auth failure preserves the last good espn.json and sets "stale": true

Usage:  set ESPN_S2 and ESPN_SWID, open a fresh terminal, then
        py collect_espn.py
"""

import json
import os
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
OUT = ROOT / "data" / "latest" / "espn.json"
UA = "Mozilla/5.0 (compatible; fantasyfootball-collector/1.0)"
MOVES_CAP = 8
MOVES_MAX_AGE_DAYS = 7   # only the last week of activity is interesting

# Discovery: proTeamId is a numeric id, not an abbreviation, so the contract's
# "t" field needs this map. 32 stable entries.
PRO_TEAMS = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL",
    7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV",
    14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ",
    21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB",
    28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

# Transaction types that are not roster moves worth showing.
SKIP_TX = {"DRAFT"}


class AuthError(Exception):
    pass


class FetchError(Exception):
    pass


# --------------------------------------------------------------------- http

def cookies():
    """Cookie header from the environment. The value is never logged."""
    s2 = os.environ.get("ESPN_S2")
    swid = os.environ.get("ESPN_SWID")
    if not s2 or not swid:
        missing = [n for n, v in (("ESPN_S2", s2), ("ESPN_SWID", swid)) if not v]
        raise AuthError(f"missing from environment: {', '.join(missing)}")
    swid = swid.strip()
    if not swid.startswith("{"):
        swid = "{" + swid.strip("{}") + "}"
    return f"espn_s2={s2.strip()}; SWID={swid}"


def request(url, cookie, binary=False, attempts=3):
    headers = {"User-Agent": UA, "Cookie": cookie}
    if not binary:
        headers["Accept"] = "application/json"
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = resp.read()
                return body if binary else json.loads(body)
        except urllib.error.HTTPError as e:
            # e.read() is deliberately never called: that is the failed
            # response body, which can echo request context.
            if e.code in (401, 403):
                raise AuthError(f"HTTP {e.code}") from None
            if attempt == attempts:
                raise FetchError(f"HTTP {e.code}") from None
        except (urllib.error.URLError, ValueError) as e:
            if attempt == attempts:
                raise FetchError(f"{getattr(e, 'reason', type(e).__name__)}") from None
        time.sleep(2 ** attempt)


# ------------------------------------------------------------------- logos

def mirror_logos(teams, cfg, cookie):
    """Copy auth-walled team logos into the repo.

    Discovery: logos on mystique-api return 401 without cookies, and the
    board loads images client-side with no cookies, so those would never
    render. 4 of 12 teams in this league are affected.
    """
    hosts = set(cfg.get("mirrorLogoHosts") or [])
    outdir = ROOT / cfg.get("logoMirrorDir", "assets/logos/espn")
    mapping, mirrored, failed = {}, 0, 0

    for t in teams:
        tid = t.get("id")
        logo = t.get("logo") or ""
        if not logo.startswith("http"):
            continue
        host = logo.split("/")[2]
        if host not in hosts:
            mapping[tid] = logo          # public CDN, board loads it directly
            continue
        try:
            blob = request(logo, cookie, binary=True)
        except (AuthError, FetchError) as e:
            failed += 1
            print(f"  logo team {tid}: mirror failed ({e})")
            # Fall back to any copy already on disk from a previous run.
            for ext in (".png", ".jpg"):
                p = outdir / f"{tid}{ext}"
                if p.exists():
                    mapping[tid] = f"{cfg['logoMirrorDir']}/{tid}{ext}"
                    break
            continue
        ext = ".jpg" if blob[:3] == b"\xff\xd8\xff" else ".png"
        outdir.mkdir(parents=True, exist_ok=True)
        path = outdir / f"{tid}{ext}"
        if not path.exists() or path.read_bytes() != blob:
            path.write_bytes(blob)
            mirrored += 1
        mapping[tid] = f"{cfg['logoMirrorDir']}/{tid}{ext}"

    print(f"  logos: {len(mapping)} resolved, {mirrored} written, {failed} failed")
    return mapping


# -------------------------------------------------------------- normalising

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def team_record(t):
    o = ((t.get("record") or {}).get("overall") or {})
    w, l, ties = o.get("wins", 0), o.get("losses", 0), o.get("ties", 0)
    return (f"{w}-{l}-{ties}" if ties else f"{w}-{l}"), w, l, ties


def team_streak(t):
    """ESPN reports the streak directly, unlike Sleeper."""
    o = ((t.get("record") or {}).get("overall") or {})
    n = o.get("streakLength") or 0
    kind = (o.get("streakType") or "").upper()
    if not n or kind not in ("WIN", "LOSS"):
        return ""
    return f"{'W' if kind == 'WIN' else 'L'}{int(n)}"


def faab_spent(t):
    tc = t.get("transactionCounter") or {}
    for key in ("acquisitionBudgetSpent",):
        if key in tc:
            return num(tc[key])
        if key in t:
            return num(t[key])
    return 0.0


def playoff_pct(t):
    """ESPN-only. Emitted when present; the renderer omits the column if not.

    Not observed in discovery - the league had played no games - so this is
    read defensively and simply absent when ESPN does not supply it.
    """
    sim = t.get("currentSimulationResults") or {}
    for key in ("playoffPct", "playoffOdds"):
        if key in sim:
            v = num(sim[key])
            return v / 100.0 if v > 1 else v
    return None


def player_points(player, week, projected=False):
    """Per-player points from mBoxscore.

    statSourceId 0 = actual, 1 = projected. statSplitTypeId 1 is the single
    scoring period. Discovery only observed statSourceId 1, pre-kickoff, so
    the actual branch is inferred - this selector is the one place to change
    if that proves wrong.
    """
    want = 1 if projected else 0
    for s in player.get("stats") or []:
        if s.get("statSourceId") != want:
            continue
        if s.get("statSplitTypeId") not in (1, None):
            continue
        if s.get("scoringPeriodId") not in (week, None):
            continue
        return num(s.get("appliedTotal"))
    return 0.0


def roster_rows(side, week, slot_order):
    """Map a team's starters onto the configured slot order.

    ESPN returns lineupSlotCounts as an unordered map, so unlike Sleeper's
    ordered roster_positions the display order is imposed here.
    """
    roster = (side or {}).get("rosterForCurrentScoringPeriod") \
        or (side or {}).get("rosterForMatchupPeriod") or {}
    by_slot = {}
    for e in roster.get("entries") or []:
        by_slot.setdefault(e.get("lineupSlotId"), []).append(e)

    rows = []
    for slot in slot_order:
        pool = by_slot.get(slot) or []
        if not pool:
            rows.append({"empty": True, "p": 0.0})
            continue
        e = pool.pop(0)
        p = (e.get("playerPoolEntry") or {}).get("player") or {}
        rows.append({
            "n": p.get("fullName") or "Unknown",
            "t": PRO_TEAMS.get(p.get("proTeamId"), ""),
            "p": round(player_points(p, week), 2),
            "proj": round(player_points(p, week, projected=True), 2),
        })
    return rows


def bench_total(side, week, slot_order):
    """Everything on the roster that is not a starter, excluding IR (slot 21)."""
    roster = (side or {}).get("rosterForCurrentScoringPeriod") \
        or (side or {}).get("rosterForMatchupPeriod") or {}
    need = {}
    for s in slot_order:
        need[s] = need.get(s, 0) + 1
    total, used = 0.0, {}
    for e in roster.get("entries") or []:
        slot = e.get("lineupSlotId")
        if slot == 21:
            continue
        if used.get(slot, 0) < need.get(slot, 0):
            used[slot] = used.get(slot, 0) + 1
            continue
        p = (e.get("playerPoolEntry") or {}).get("player") or {}
        total += player_points(p, week)
    return round(total, 2)


# --------------------------------------------------------------------- main

def build(cfg, cookie):
    base = (f"{cfg['base']}/apis/v3/games/ffl/seasons/{cfg['season']}"
            f"/segments/0/leagues/{cfg['leagueId']}")
    slot_order = cfg["slotOrder"]

    def view(*views, **params):
        q = [f"view={v}" for v in views] + [f"{k}={v}" for k, v in params.items()]
        return f"{base}?{'&'.join(q)}"

    meta = request(base, cookie)
    status = meta.get("status") or {}
    current = int(status.get("currentMatchupPeriod")
                  or meta.get("scoringPeriodId") or 1)

    team_doc = request(view("mTeam", "mStandings"), cookie)
    teams = team_doc.get("teams") or []
    score_doc = request(view("mMatchupScore"), cookie)
    schedule = score_doc.get("schedule") or []

    # Anchor on the league's current matchup period, which ESPN rolls forward
    # by Tuesday morning (logs: currentMatchupPeriod=3 on a Tuesday while
    # week 2 was final). That keeps the upcoming matchup on the board from
    # Tuesday through the weekend. From Monday until the Tuesday 04:00 ET
    # rollover, stay on the latest period with points instead, so an early
    # roll never cuts off Monday night.
    anchor = max(1, current)
    if nfl_schedule.hold_previous_week():
        scored = 0
        for g in schedule:
            mp = g.get("matchupPeriodId") or 0
            if mp > current:
                continue
            pts = num((g.get("home") or {}).get("totalPoints")) \
                + num((g.get("away") or {}).get("totalPoints")) \
                + num((g.get("home") or {}).get("totalPointsLive")) \
                + num((g.get("away") or {}).get("totalPointsLive"))
            if pts > 0:
                scored = max(scored, mp)
        if scored:
            anchor = scored
    print(f"  currentMatchupPeriod={current}, anchored on {anchor}")

    box = request(view("mBoxscore", scoringPeriodId=anchor), cookie)
    logos = mirror_logos(teams, cfg, cookie)

    by_id = {t["id"]: t for t in teams}
    me = cfg["me"]["teamId"]
    budget = cfg["faab"]["budget"]

    def name_of(tid):
        t = by_id.get(tid) or {}
        # Discovery: raw names carry double and trailing spaces.
        raw = t.get("name") or " ".join(
            x for x in (t.get("location"), t.get("nickname")) if x) or f"Team {tid}"
        return " ".join(str(raw).split())

    def side_of(tid):
        return {"n": name_of(tid), "logo": logos.get(tid)}

    def team_pts(s):
        """totalPointsLive is the in-game score; totalPoints is the settled one."""
        return round(max(num(s.get("totalPoints")), num(s.get("totalPointsLive"))), 2)

    def team_proj(s):
        return round(max(num(s.get("totalProjectedPoints")),
                         num(s.get("totalProjectedPointsLive"))), 2)

    # --- hero -------------------------------------------------------------
    my_game = my_side = opp_side = None
    for g in schedule:
        if g.get("matchupPeriodId") != anchor:
            continue
        h, a = g.get("home") or {}, g.get("away") or {}
        if h.get("teamId") == me or a.get("teamId") == me:
            my_game = g
            my_side, opp_side = (h, a) if h.get("teamId") == me else (a, h)
            break

    def hero_side(s, is_me):
        if not s:
            return {"name": "-", "rec": "", "pts": 0.0, "proj": 0.0, "logo": None}
        tid = s.get("teamId")
        rec, _, _, _ = team_record(by_id.get(tid) or {})
        out = {"name": name_of(tid), "rec": rec, "pts": team_pts(s),
               "proj": team_proj(s), "logo": logos.get(tid)}
        if is_me:
            out["me"] = True
        return out

    # --- lineup grid ------------------------------------------------------
    box_home = box_away = None
    for g in box.get("schedule") or []:
        if g.get("matchupPeriodId") != anchor:
            continue
        h, a = g.get("home") or {}, g.get("away") or {}
        if h.get("teamId") == me or a.get("teamId") == me:
            box_home, box_away = (h, a) if h.get("teamId") == me else (a, h)
            break

    a_rows = roster_rows(box_home, anchor, slot_order)
    b_rows = roster_rows(box_away, anchor, slot_order)
    names = cfg["slotNames"]
    lineup = [{"pos": names.get(str(slot), str(slot)),
               "a": a_rows[i], "b": b_rows[i]}
              for i, slot in enumerate(slot_order)]

    # --- other games ------------------------------------------------------
    # All other games, closest first. The handoff suggested cutting this to
    # the two closest plus the high score, because 5 games crowded the strip -
    # but the board now pages through them, so nothing has to be dropped.
    # Closest first means the most interesting games land on the first page.
    others = []
    for g in schedule:
        if g.get("matchupPeriodId") != anchor or g is my_game:
            continue
        h, a = g.get("home") or {}, g.get("away") or {}
        ph, pa = team_pts(h), team_pts(a)
        others.append({"a": side_of(h.get("teamId")), "pa": ph,
                       "b": side_of(a.get("teamId")), "pb": pa,
                       "_gap": abs(ph - pa), "_top": max(ph, pa)})
    others.sort(key=lambda m: m["_gap"])
    matchups = [{k: v for k, v in m.items() if not k.startswith("_")}
                for m in others]

    # --- next week --------------------------------------------------------
    upcoming_week = anchor + 1
    games = []
    if upcoming_week <= cfg["regularSeasonWeeks"]:
        for g in schedule:
            if g.get("matchupPeriodId") != upcoming_week:
                continue
            entry = {}
            for key, s in (("a", g.get("home") or {}), ("b", g.get("away") or {})):
                tid = s.get("teamId")
                rec, _, _, _ = team_record(by_id.get(tid) or {})
                entry[key] = {"n": name_of(tid), "rec": rec, "logo": logos.get(tid)}
                if tid == me:
                    entry[key]["me"] = True
            games.append(entry)

    # --- standings --------------------------------------------------------
    standings, has_odds = [], False
    for t in teams:
        tid = t["id"]
        rec, w, l, ties = team_record(t)
        o = ((t.get("record") or {}).get("overall") or {})
        row = {
            "t": name_of(tid), "w": w, "l": l,
            "pf": round(num(o.get("pointsFor")), 2),
            "s": team_streak(t),
            "logo": logos.get(tid),
            "me": tid == me,
            "faab": round(budget - faab_spent(t), 2),
        }
        if ties:
            row["ties"] = ties
        pct = playoff_pct(t)
        if pct is not None:
            row["playoffPct"] = round(pct, 4)
            has_odds = True
        standings.append(row)
    # ESPN publishes playoffSeed, which encodes the league's tiebreak (total
    # points scored) - but only once results exist. Before any game has been
    # decided every team is 0-0 and the seeds are effectively arbitrary, which
    # renders as a table in no discernible order. So the seed is trusted only
    # once someone has a win or a loss; until then, sort by whatever ordering
    # signal is actually meaningful.
    played = any(r["w"] or r["l"] for r in standings)
    seeds = {name_of(t["id"]): (t.get("playoffSeed") or 0) for t in teams}
    if played and any(v > 0 for v in seeds.values()):
        standings.sort(key=lambda r: (seeds.get(r["t"]) or 99, -r["w"], -r["pf"]))
    elif has_odds:
        standings.sort(key=lambda r: (-(r.get("playoffPct") or 0), -r["pf"]))
    else:
        standings.sort(key=lambda r: (-r["w"], -r["pf"]))
    print(f"  playoff odds present: {has_odds}")

    # --- moves ------------------------------------------------------------
    moves = []
    try:
        tx_doc = request(view("mTransactions2"), cookie)
        tx = tx_doc.get("transactions") or []
    except FetchError as e:
        print(f"  transactions unavailable ({e})")
        tx = []

    # Player names are not in the transaction payload. Build the lookup from
    # the roster data already fetched rather than adding an endpoint.
    pnames = {}
    for g in box.get("schedule") or []:
        for s in (g.get("home") or {}, g.get("away") or {}):
            r = s.get("rosterForCurrentScoringPeriod") \
                or s.get("rosterForMatchupPeriod") or {}
            for e in r.get("entries") or []:
                p = (e.get("playerPoolEntry") or {}).get("player") or {}
                if p.get("id"):
                    pnames[p["id"]] = p.get("fullName") or ""

    def pname(pid):
        """None when the id cannot be resolved.

        The name map is built from current rosters, so a dropped player is
        often no longer resolvable. Callers omit the clause rather than
        printing a raw id at the reader.
        """
        return pnames.get(pid) or None

    cutoff_ms = (time.time() - MOVES_MAX_AGE_DAYS * 86400) * 1000
    for t in sorted(tx, key=lambda x: x.get("proposedDate") or 0, reverse=True):
        if t.get("type") in SKIP_TX or t.get("isPending"):
            continue
        if (t.get("proposedDate") or 0) < cutoff_ms:
            continue
        if t.get("status") not in ("EXECUTED", None):
            continue
        items = t.get("items") or []
        adds = [i for i in items if (i.get("toTeamId") or 0) > 0
                and i.get("type") != "DRAFT"]
        drops = [i for i in items if (i.get("fromTeamId") or 0) > 0
                 and (i.get("toTeamId") or 0) == 0]
        secs = int(time.time() - (t.get("proposedDate") or 0) / 1000)
        when = (f"{max(1, secs // 60)}m" if secs < 3600
                else f"{secs // 3600}h" if secs < 86400 else f"{secs // 86400}d")

        if t.get("type") == "TRADE_ACCEPTED" and len(items) >= 1:
            a = items[0].get("fromTeamId")
            b = items[0].get("toTeamId")
            moves.append({"k": "trade",
                          "txt": f"<b>{name_of(a)}</b> traded with <b>{name_of(b)}</b>",
                          "when": when})
        elif adds:
            i = adds[0]
            added = pname(i.get("playerId"))
            if not added:
                continue  # the added player is the subject; no name, no move
            verb = "claimed" if t.get("type") == "WAIVER" else "added"
            txt = f"<b>{name_of(i.get('toTeamId'))}</b> {verb} {added}"
            if num(t.get("bidAmount")) > 0:
                txt += f" (${int(num(t['bidAmount']))})"
            dropped = pname(drops[0].get("playerId")) if drops else None
            if dropped:
                txt += f", dropped {dropped}"
            moves.append({"k": "add", "txt": txt, "when": when})
        elif drops:
            i = drops[0]
            dropped = pname(i.get("playerId"))
            if not dropped:
                continue
            moves.append({"k": "drop",
                          "txt": f"<b>{name_of(i.get('fromTeamId'))}</b> dropped "
                                 f"{dropped}",
                          "when": when})
        if len(moves) >= MOVES_CAP:
            break

    return {
        "league": cfg["league"],
        "platform": "espn",
        "week": anchor,
        "stale": False,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "playoffCut": cfg["playoffCut"],
        "faab": {"budget": budget},
        "hero": {"a": hero_side(my_side, True), "b": hero_side(opp_side, False)},
        "lineup": lineup,
        "bench": {"a": bench_total(box_home, anchor, slot_order),
                  "b": bench_total(box_away, anchor, slot_order)},
        "matchups": matchups,
        "upcoming": {"week": upcoming_week, "games": games},
        "windows": nfl_schedule.game_windows(cfg["season"], anchor),
        "standings": standings,
        "moves": moves,
    }


def mark_stale(reason):
    """Cookies expire. That is a normal operating state, not a crash."""
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
    cfg = json.loads(CONFIG.read_text())["espn"]
    try:
        cookie = cookies()
    except AuthError as e:
        return mark_stale(f"credentials {e}")

    try:
        data = build(cfg, cookie)
    except AuthError as e:
        # Status code only. Never the body, never the headers.
        return mark_stale(f"auth failed ({e})")
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
