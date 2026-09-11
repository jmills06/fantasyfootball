#!/usr/bin/env python3
"""Raw API discovery for the fantasy football boards.

Hits every endpoint listed in section 6 of
reference/fantasy-football-boards-handoff.md for both leagues and dumps the
raw JSON into discovery/, one file per endpoint per league. No normalization,
no transformation, no trimming - whatever the API returned is what lands on
disk.

Usage (owner's machine):

    set ESPN_S2 / ESPN_SWID in the environment, open a fresh terminal, then
    py discover.py                  # both leagues
    py discover.py --only sleeper   # Sleeper only, needs no auth
    py discover.py --with-players   # also pull the ~5MB Sleeper players file

SECURITY - see CLAUDE.md section 1. This script:
  * reads ESPN cookies only from os.environ
  * never prints cookie values, the cookie dict, or request headers
  * never prints or writes a response body for a failed request
  * writes only into discovery/, which is gitignored
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# The owner's machine needs truststore for HTTPS to verify. Optional
# elsewhere, so a missing module is a note, not a failure.
try:
    import truststore

    truststore.inject_into_ssl()
    TRUSTSTORE = "injected"
except ImportError:
    TRUSTSTORE = "not installed (using default SSL context)"

SLEEPER_BASE = "https://api.sleeper.app"
SLEEPER_LEAGUE = "1389343119928991744"

ESPN_HOST = "https://lm-api-reads.fantasy.espn.com"
ESPN_SEASON = 2026
ESPN_LEAGUE = "1529795"
ESPN_BASE = (
    f"{ESPN_HOST}/apis/v3/games/ffl/seasons/{ESPN_SEASON}"
    f"/segments/0/leagues/{ESPN_LEAGUE}"
)
ESPN_HISTORY_BASE = f"{ESPN_HOST}/apis/v3/games/ffl/leagueHistory/{ESPN_LEAGUE}"

OUT = Path(__file__).resolve().parent / "discovery"
UA = "Mozilla/5.0 (compatible; fantasyfootball-discovery/1.0)"
TIMEOUT = 30

manifest = []


def log(msg):
    print(msg, flush=True)


def record(label, url, **kw):
    """Append one manifest row. Never carries headers or a body."""
    row = {"label": label, "url": url}
    row.update(kw)
    manifest.append(row)
    return row


def fetch(label, url, cookies=None, extra_headers=None, attempts=3):
    """GET url and write the raw body to discovery/<label>.json.

    Returns the parsed JSON on success, None on any failure. Nothing about
    the request headers or a failed response body is printed or stored -
    only status codes and sizes.
    """
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    if cookies:
        headers["Cookie"] = cookies

    last_status = None
    last_kind = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers=headers)
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read()
                status = resp.status
        except urllib.error.HTTPError as e:
            # Deliberately do NOT read or store e.read() - that is the
            # failed response body, which may echo request context.
            last_status, last_kind = e.code, "http_error"
            if e.code in (401, 403):
                log(f"  [FAIL] {label}: HTTP {e.code}")
                record(label, url, ok=False, status=e.code, kind="http_error",
                       note="auth/permission; body deliberately not captured")
                return None
            if attempt < attempts:
                time.sleep(2 ** attempt)
                continue
            log(f"  [FAIL] {label}: HTTP {e.code}")
            record(label, url, ok=False, status=e.code, kind="http_error",
                   note="body deliberately not captured")
            return None
        except urllib.error.URLError as e:
            # Network/TLS/proxy layer. e.reason is a transport message, not
            # a response body, so it is safe to surface.
            last_status, last_kind = None, "network_error"
            reason = str(getattr(e, "reason", e))
            if attempt < attempts:
                time.sleep(2 ** attempt)
                continue
            log(f"  [FAIL] {label}: network error: {reason}")
            record(label, url, ok=False, status=None, kind="network_error",
                   reason=reason)
            return None
        except Exception as e:  # noqa: BLE001 - discovery script, stay alive
            last_status, last_kind = None, type(e).__name__
            if attempt < attempts:
                time.sleep(2 ** attempt)
                continue
            log(f"  [FAIL] {label}: {type(e).__name__}")
            record(label, url, ok=False, status=None, kind=type(e).__name__)
            return None

        elapsed = round(time.time() - started, 2)
        path = OUT / f"{label}.json"
        path.write_bytes(body)

        parsed, shape = None, "unparsed"
        try:
            parsed = json.loads(body)
            if isinstance(parsed, list):
                shape = f"list[{len(parsed)}]"
            elif isinstance(parsed, dict):
                shape = f"object[{len(parsed)} keys]"
            else:
                shape = type(parsed).__name__
        except ValueError:
            shape = "non-JSON body"

        log(f"  [ok]   {label}: {status}, {len(body):,} bytes, {shape}, {elapsed}s")
        record(label, url, ok=True, status=status, bytes=len(body),
               shape=shape, seconds=elapsed, file=path.name)
        return parsed

    record(label, url, ok=False, status=last_status, kind=last_kind)
    return None


def probe(label, url, cookies=None):
    """HEAD-ish probe that records reachability only, no body written.

    Used for the logo-host question: do custom team logos load with no
    cookies at all, the way the board will load them client-side?
    """
    headers = {"User-Agent": UA}
    if cookies:
        headers["Cookie"] = cookies
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
            row = {"ok": True, "status": resp.status,
                   "content_type": resp.headers.get("Content-Type"),
                   "bytes": len(body)}
    except urllib.error.HTTPError as e:
        row = {"ok": False, "status": e.code, "kind": "http_error"}
    except urllib.error.URLError as e:
        row = {"ok": False, "status": None, "kind": "network_error",
               "reason": str(getattr(e, "reason", e))}
    except Exception as e:  # noqa: BLE001
        row = {"ok": False, "status": None, "kind": type(e).__name__}
    log(f"  [{'ok' if row['ok'] else 'FAIL'}]   {label}: {row.get('status')}")
    record(label, url, **row)
    return row


# ---------------------------------------------------------------- Sleeper

def discover_sleeper(args):
    log("\n=== SLEEPER (no auth required) ===")
    lg = SLEEPER_LEAGUE

    state = fetch("sleeper__state_nfl", f"{SLEEPER_BASE}/v1/state/nfl")

    fetch("sleeper__league", f"{SLEEPER_BASE}/v1/league/{lg}")
    fetch("sleeper__users", f"{SLEEPER_BASE}/v1/league/{lg}/users")
    fetch("sleeper__rosters", f"{SLEEPER_BASE}/v1/league/{lg}/rosters")
    fetch("sleeper__winners_bracket", f"{SLEEPER_BASE}/v1/league/{lg}/winners_bracket")
    fetch("sleeper__losers_bracket", f"{SLEEPER_BASE}/v1/league/{lg}/losers_bracket")
    fetch("sleeper__traded_picks", f"{SLEEPER_BASE}/v1/league/{lg}/traded_picks")
    fetch("sleeper__drafts", f"{SLEEPER_BASE}/v1/league/{lg}/drafts")

    # Week-dependent endpoints. /v1/state/nfl returns both `week` and
    # `display_week`, which diverge on Tuesdays - capture both, and pull
    # every week up to and including next week so the streak walk and the
    # "next week's pairings" assumption can both be checked.
    week = args.week
    if week is None and isinstance(state, dict):
        week = state.get("week")
        log(f"  state: week={state.get('week')} display_week={state.get('display_week')} "
            f"season={state.get('season')} season_type={state.get('season_type')}")
    if not week:
        log("  [skip] week-dependent endpoints: no week available "
            "(state call failed and --week not given)")
        record("sleeper__matchups_*", "-", ok=False, kind="skipped",
               reason="no week available")
        record("sleeper__transactions_*", "-", ok=False, kind="skipped",
               reason="no week available")
    else:
        week = int(week)
        for w in range(1, min(week + 1, 18) + 1):
            fetch(f"sleeper__matchups_w{w}",
                  f"{SLEEPER_BASE}/v1/league/{lg}/matchups/{w}")
        # Two weeks of transactions so the list is not empty on a Tuesday.
        for w in {max(1, week - 1), week}:
            fetch(f"sleeper__transactions_w{w}",
                  f"{SLEEPER_BASE}/v1/league/{lg}/transactions/{w}")

    if args.with_players:
        log("  fetching the ~5MB all-players file (opt-in)")
        fetch("sleeper__players_nfl", f"{SLEEPER_BASE}/v1/players/nfl")
    else:
        log("  [skip] sleeper__players_nfl (~5MB) - pass --with-players to capture")
        record("sleeper__players_nfl", f"{SLEEPER_BASE}/v1/players/nfl",
               ok=False, kind="skipped", reason="opt-in via --with-players")


# ------------------------------------------------------------------- ESPN

def espn_cookies():
    """Build the Cookie header from env. Returns (header, note).

    The header value is never logged or written anywhere.
    """
    s2 = os.environ.get("ESPN_S2")
    swid = os.environ.get("ESPN_SWID")
    if not s2 or not swid:
        missing = [n for n, v in (("ESPN_S2", s2), ("ESPN_SWID", swid)) if not v]
        return None, f"missing from environment: {', '.join(missing)}"
    swid = swid.strip()
    if not swid.startswith("{"):
        swid = "{" + swid.strip("{}") + "}"
    return f"espn_s2={s2.strip()}; SWID={swid}", "present"


def discover_espn(args):
    log("\n=== ESPN (private league, cookie auth) ===")
    cookies, note = espn_cookies()
    log(f"  credentials: {note}")
    if not cookies:
        log("  [skip] all ESPN endpoints - set ESPN_S2 and ESPN_SWID, then "
            "open a fresh terminal")
        record("espn__*", ESPN_BASE, ok=False, kind="skipped",
               reason="ESPN_S2/ESPN_SWID not in environment")
        return

    def url_for(*views, **params):
        q = [f"view={v}" for v in views]
        q += [f"{k}={v}" for k, v in params.items()]
        return f"{ESPN_BASE}?{'&'.join(q)}" if q else ESPN_BASE

    base = fetch("espn__base_noview", ESPN_BASE, cookies=cookies)
    if isinstance(base, dict):
        log(f"  base: scoringPeriodId={base.get('scoringPeriodId')} "
            f"currentMatchupPeriod="
            f"{(base.get('status') or {}).get('currentMatchupPeriod')} "
            f"latestScoringPeriod="
            f"{(base.get('status') or {}).get('latestScoringPeriod')}")

    # Views called individually. Section 7 warns that stacking views can
    # return different results than calling them separately, so do both.
    for view in ("mSettings", "mTeam", "mStandings", "mRoster", "mMatchup",
                 "mMatchupScore", "mBoxscore", "mSchedule", "mPositionalRatings",
                 "mPendingTransactions"):
        fetch(f"espn__{view}", url_for(view), cookies=cookies)

    # The same views stacked, to compare against the singles above.
    fetch("espn__combo_team_roster_settings",
          url_for("mTeam", "mRoster", "mSettings"), cookies=cookies)
    fetch("espn__combo_matchup_boxscore",
          url_for("mMatchup", "mMatchupScore", "mBoxscore"), cookies=cookies)

    # Per-player live points: the single biggest ESPN unknown. mBoxscore
    # with an explicit scoringPeriodId, alone and with mRoster.
    sp = args.espn_week
    if sp is None and isinstance(base, dict):
        sp = base.get("scoringPeriodId")
    if not sp:
        log("  [skip] scoringPeriodId probes: no scoring period available")
        record("espn__mBoxscore_sp*", "-", ok=False, kind="skipped",
               reason="no scoringPeriodId available")
    else:
        sp = int(sp)
        fetch(f"espn__mBoxscore_sp{sp}",
              url_for("mBoxscore", scoringPeriodId=sp), cookies=cookies)
        fetch(f"espn__mBoxscore_mRoster_sp{sp}",
              url_for("mBoxscore", "mRoster", scoringPeriodId=sp), cookies=cookies)
        fetch(f"espn__mRoster_sp{sp}",
              url_for("mRoster", scoringPeriodId=sp), cookies=cookies)
        fetch(f"espn__mMatchupScore_sp{sp}",
              url_for("mMatchupScore", scoringPeriodId=sp), cookies=cookies)
        if sp > 1:
            fetch(f"espn__mBoxscore_sp{sp - 1}",
                  url_for("mBoxscore", scoringPeriodId=sp - 1), cookies=cookies)

    # Transactions. mTransactions2 needs an x-fantasy-filter header. The
    # filter is request metadata we author ourselves, not a credential, so
    # it is recorded here in the source for reproducibility - but the header
    # dict itself is still never logged at runtime.
    tx_filter = json.dumps({
        "transactions": {
            "filterType": {"value": ["WAIVER", "FREEAGENT", "TRADE_ACCEPTED",
                                     "ROSTER", "DRAFT"]},
        }
    })
    fetch("espn__mTransactions2", url_for("mTransactions2"), cookies=cookies,
          extra_headers={"x-fantasy-filter": tx_filter})
    fetch("espn__mTransactions2_nofilter", url_for("mTransactions2"),
          cookies=cookies)

    # Prior seasons via leagueHistory.
    fetch("espn__history_2025",
          f"{ESPN_HISTORY_BASE}?seasonId=2025&view=mTeam&view=mStandings",
          cookies=cookies)

    # Do custom team logos load with no cookies, the way the board loads
    # them client-side? Pull the URLs out of mTeam and probe each host once.
    logo_probe(cookies)


def logo_probe(cookies):
    team_file = OUT / "espn__mTeam.json"
    if not team_file.exists():
        log("  [skip] logo probe: no mTeam capture to read URLs from")
        return
    try:
        teams = json.loads(team_file.read_text()).get("teams") or []
    except (ValueError, AttributeError):
        log("  [skip] logo probe: mTeam capture not parseable")
        return

    seen_hosts = {}
    for t in teams:
        logo = t.get("logo")
        if not logo or not logo.startswith("http"):
            continue
        host = logo.split("/")[2]
        seen_hosts.setdefault(host, logo)

    if not seen_hosts:
        log("  [skip] logo probe: no logo URLs in mTeam")
        return

    log(f"  logo hosts in this league: {', '.join(sorted(seen_hosts))}")
    for host, url in sorted(seen_hosts.items()):
        # No cookies: this is exactly what the board's <img> does.
        probe(f"logo__{host.replace('.', '_')}__nocookie", url)


# ------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Raw API discovery, both leagues.")
    ap.add_argument("--only", choices=("sleeper", "espn", "all"), default="all")
    ap.add_argument("--week", type=int, default=None,
                    help="override the Sleeper week (default: /v1/state/nfl)")
    ap.add_argument("--espn-week", type=int, default=None,
                    help="override the ESPN scoringPeriodId")
    ap.add_argument("--with-players", action="store_true",
                    help="also fetch the ~5MB Sleeper all-players file")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    started = datetime.now(timezone.utc)

    log(f"discovery run {started.isoformat(timespec='seconds')}")
    log(f"python {sys.version.split()[0]}  truststore: {TRUSTSTORE}")
    log(f"output: {OUT}")

    if args.only in ("all", "sleeper"):
        discover_sleeper(args)
    if args.only in ("all", "espn"):
        discover_espn(args)

    ok = sum(1 for r in manifest if r.get("ok"))
    failed = sum(1 for r in manifest if not r.get("ok") and r.get("kind") != "skipped")
    skipped = sum(1 for r in manifest if r.get("kind") == "skipped")

    (OUT / "_manifest.json").write_text(json.dumps({
        "started": started.isoformat(timespec="seconds"),
        "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "truststore": TRUSTSTORE,
        "counts": {"ok": ok, "failed": failed, "skipped": skipped},
        "endpoints": manifest,
    }, indent=2))

    log(f"\n{ok} ok, {failed} failed, {skipped} skipped")
    log(f"manifest: {OUT / '_manifest.json'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
