# Discovery findings

**Run:** 2026-09-11 17:55 UTC, from the Claude Code remote container
(Linux, Python 3.11.15), not from the owner's machine.
**Script:** `discover.py` (unmodified, default args)
**Manifest:** `discovery/_manifest.json`

## Headline

**Nothing was confirmed. Zero endpoints returned data.** Every unknown in
handoff section 6 is still an unknown. Discovery has to be re-run from the
owner's machine before any collector or board code is written.

This is an environment failure, not an API failure. Nothing here says
anything about whether the endpoints in `discover.py` are correct.

| | |
|---|---|
| Endpoints attempted | 8 |
| Succeeded | 0 |
| Failed (network) | 8 |
| Skipped (no precondition) | 4 |

## Why it failed

Two independent blockers, one per platform.

### Sleeper - blocked by the session's egress policy

All 8 Sleeper calls failed identically:

```
network error: Tunnel connection failed: 403 Forbidden
```

This container routes outbound HTTPS through an agent proxy that enforces an
organization allowlist. `api.sleeper.app:443` is not on it, so the CONNECT
tunnel is refused before any request is sent. The proxy's own status endpoint
confirms it (`kind: connect_rejected`, "the egress proxy denied the CONNECT
(organization policy)"). `lm-api-reads.fantasy.espn.com:443` is refused the
same way.

Retries (3 attempts, exponential backoff) were spent and made no difference -
a policy denial is not transient. This was not worked around, per the
environment's own rule about not routing around policy denials.

### ESPN - no credentials, and the host is blocked anyway

`ESPN_S2` and `ESPN_SWID` are not set in this container, so every ESPN
endpoint was skipped before a request was attempted. Discovery correctly
refused to guess. Separately, a forced probe confirmed the ESPN host is
blocked by the same egress policy, so supplying cookies here would not have
helped - and the cookies should not be pasted into a remote container
regardless.

## Section 6 unknowns: current status

Every row is unresolved. The "what resolves it" column is the endpoint
already wired into `discover.py`.

### Sleeper (league `1389343119928991744`)

| Unknown (handoff section 6) | Status | What resolves it |
|---|---|---|
| `roster_positions` - mockup assumes 9 slots (QB/RB/RB/WR/WR/TE/FLEX/K/DEF) | **Unresolved** | `sleeper__league` |
| James's `roster_id` (match `user_id` -> `owner_id`) | **Unresolved** | `sleeper__users` + `sleeper__rosters` |
| `settings.playoff_week_start`, playoff team count (mockup assumed 4 of 8) | **Unresolved** | `sleeper__league` |
| Manager avatars / custom team image in `metadata` | **Unresolved** | `sleeper__users` |
| Whether all 8 managers set `team_name` | **Unresolved** | `sleeper__users` |
| Whether the league uses FAAB | **Unresolved** | `sleeper__league` (`settings.waiver_type` / `waiver_budget`) |
| 8 teams (stated by James, never verified) | **Unresolved** | `sleeper__rosters` (length) |
| `fpts` / `fpts_decimal` split is real | **Unresolved** | `sleeper__rosters` |
| `starters` is slot-ordered and identical across teams | **Unresolved** | `sleeper__matchups_w{n}` |
| `0` in `starters` means an empty slot | **Unresolved** | `sleeper__matchups_w{n}` |
| `week` vs `display_week` divergence | **Unresolved** | `sleeper__state_nfl` |
| Transactions include failed waiver claims | **Unresolved** | `sleeper__transactions_w{n}` |
| Postseason pairings live in `winners_bracket` | **Unresolved** | `sleeper__winners_bracket` |

The handoff is explicit that the entire Sleeper half is unverified
assumption. It still is. Nothing in the Sleeper section should be treated as
fact when writing `config/leagues.json`.

### ESPN (league `1529795`, season 2026)

| Unknown (handoff section 6) | Status | What resolves it |
|---|---|---|
| **Which view returns per-player live points** - the biggest ESPN unknown | **Unresolved** | `espn__mBoxscore_sp{n}`, `espn__mBoxscore_mRoster_sp{n}`, `espn__mRoster_sp{n}` |
| How to retrieve transactions (`mTransactions2` + `x-fantasy-filter`) | **Unresolved** | `espn__mTransactions2`, `espn__mTransactions2_nofilter` |
| Whether custom team logos load without auth (`mystique-api` host) | **Unresolved** | `logo__*__nocookie` probes (cookie-free, exactly what the board's `<img>` does) |
| Whether `totalProjectedPointsLive` populates during games | **Unresolved** | `espn__mBoxscore_sp{n}` mid-game vs pre-kickoff |
| Whether stacked views differ from separate views (section 7 warning) | **Unresolved** | `espn__combo_*` vs the individual `espn__{view}` captures |
| The section 6 table facts (12 teams, sparse IDs, 10 slots, 7-of-12 playoffs, $100 FAAB, `isPublic: false`) | **Not re-verified** | `espn__mSettings`, `espn__mTeam`, `espn__mStandings` |

The section 6 ESPN table is marked "confirmed" in the handoff from an earlier
session. This run neither confirmed nor contradicted any of it. Treat it as
prior evidence, not as something this discovery run stands behind.

## Endpoints that failed, individually

All Sleeper failures are the same policy denial, not distinct API problems:

- `sleeper__state_nfl`, `sleeper__league`, `sleeper__users`,
  `sleeper__rosters`, `sleeper__winners_bracket`, `sleeper__losers_bracket`,
  `sleeper__traded_picks`, `sleeper__drafts` - all `Tunnel connection
  failed: 403 Forbidden`.

Skipped, with reasons recorded in the manifest:

- `sleeper__matchups_*` and `sleeper__transactions_*` - week-dependent, and
  `/v1/state/nfl` never returned a week. A `--week N` run exercises them.
- `sleeper__players_nfl` - opt-in only (`--with-players`), since it is ~5MB.
- `espn__*` - `ESPN_S2` / `ESPN_SWID` missing from the environment.

## What the run did establish

Only that the script itself behaves. All paths were exercised, including a
forced ESPN run with throwaway placeholder values to drive the cookie branch:

- No crashes on total network failure; every endpoint failed independently
  and the run completed.
- Missing credentials skip ESPN cleanly instead of firing unauthenticated
  requests.
- Week-dependent endpoints skip with a recorded reason when no week is
  available, and fire correctly under `--week`.
- **Security rules hold.** No cookie value, no cookie dict, no request
  header, and no failed response body was printed or written. Failures
  record status code, failure kind, and transport reason only. The manifest
  was grepped for cookie and header terms; the only hit is the literal
  variable *names* in the message "ESPN_S2/ESPN_SWID not in environment".
- `HTTPError` bodies are never read. On 401/403, the status code is recorded
  and the body is deliberately discarded unread, per handoff section 4.

One note for the owner's machine: `truststore` is not installed here, so the
script logged `truststore: not installed (using default SSL context)` and
continued. On the owner's machine it should log `truststore: injected`. If it
does not, install it before trusting any HTTPS result.

## Next step

Re-run from the owner's machine, where both hosts are reachable:

```
py discover.py --only sleeper          # needs no auth, do this first
py discover.py                         # both, after ESPN_S2/ESPN_SWID are set
```

Set `ESPN_S2` and `ESPN_SWID` in the environment and **open a fresh terminal**
before the second command - an already-open terminal will not see them.

Then replace this file with the real findings before writing
`config/leagues.json` or any collector. Build order in handoff section 2 is
gated on it.
