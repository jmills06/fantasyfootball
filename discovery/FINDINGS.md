# Discovery findings

**Sleeper run:** 2026-09-11 18:03 UTC, owner's machine (Windows, Python
3.14.2, `truststore: injected`). 11 ok, 0 failed, 1 skipped.
**ESPN run:** 2026-09-11 18:06 UTC, same machine. 31 ok, 2 failed, 1 skipped.
**Script:** `discover.py`

An earlier run from the Claude Code remote container failed entirely (both API
hosts blocked by that container's egress policy). Everything below comes from
the owner's machine.

---

## Headline

Both leagues are captured, with two different outcomes.

**Sleeper: the handoff's assumptions are wrong in ways that change the
layout.** The lineup grid is 10 rows, not 9, there is no kicker, and the
league is a dynasty league with FAAB - none of which the handoff anticipated.

**ESPN: every fact in the section 6 table re-verified exactly.** Both run
failures are answers rather than problems - custom team logos require auth, so
mirroring is now mandatory, and transactions work fine unfiltered.

Both boards are 10 lineup rows. That is a coincidence, not a plan.

Two ESPN unknowns cannot be closed until a live Sunday, and are called out
below as such.

---

## Sleeper - confirmed, wrong, and still unknown

League `1389343119928991744`, name **"Laces Out"**, season 2026,
`season_type: regular`, captured at `week=1 display_week=1`.

### WRONG - assumptions the data contradicts

**1. `roster_positions` is 10 starting slots, not 9, and there is no kicker.**

Actual:

```
QB, RB, RB, WR, WR, WR, TE, FLEX, FLEX, DEF
```

then 12 `BN`. The handoff assumed `QB/RB/RB/WR/WR/TE/FLEX/K/DEF`. Three
differences: **3 WR not 2**, **2 FLEX not 1**, **no K slot at all**.

Consequences:

- The lineup grid is 10 rows on both boards, not 9 on Sleeper and 10 on ESPN.
- There are **two** gold FLEX rows, not one.
- Any kicker handling in the mockup comes out.
- Scoring settings still contain kicker scoring (`fgm_*`, `xpm`). Ignore it;
  the roster has no K slot.

**2. This is a dynasty league. The handoff never mentions it.**

`settings.type: 2` (dynasty), plus `taxi_slots: 3`, `taxi_years: 2`,
`draft_rounds: 5` (rookie draft), `max_keepers: 1`, and
`previous_league_id: "1225620718889222144"`.

Consequences:

- Rosters carry populated `taxi` and `reserve` arrays. Both sit outside the 22
  `roster_positions` slots and must not leak into the lineup grid or a bench
  total.
- `players` includes taxi and IR players, so roster length runs 25-28.
- Week 1 transactions are mostly **offseason dynasty cuts** - see below.

**3. `previous_league_id` exists, so Sleeper history is not impossible.**

Handoff section 11 says all-time records are "possible on the ESPN board and
impossible on the Sleeper one". Not correct: `previous_league_id` chains back
through prior seasons. Same out-of-scope-for-v1 call as ESPN, but the
reasoning should be corrected rather than carried forward as fact.

**4. Scoring differs from ESPN.**

`rec: 0.5` (**half PPR**, not full PPR like ESPN), `pass_td: 6` (ESPN is 4),
`pass_yd: 0.04`. Does not affect the renderer, but do not assume the two
leagues score alike when sanity-checking numbers.

### CONFIRMED

| Assumption | Result |
|---|---|
| 8 teams | Confirmed. `total_rosters: 8`, 8 users, 8 rosters. |
| Playoffs are 4 of 8 | **Confirmed.** `playoff_teams: 4`. The mockup's green-border treatment stands. |
| `playoff_week_start` | **15**, regular season weeks 1-14. Same shape as ESPN. |
| `starters` slot-ordered and identical across teams | Confirmed. All 8 rosters, 10 entries, same order, DEF always last. The grid aligns row by row with no matching logic. |
| Points split across two integer fields | `fpts` / `fpts_decimal` exist, both 0 pre-scoring. Split is real; recombination untestable until scores land. |
| Streak not in the API | Confirmed. Only `wins`/`losses`/`ties`. "W2" must be computed by walking prior weeks. |
| Not all managers set `team_name` | Confirmed - roster 2 has none. The display-name fallback is required. |

### James's identity

`user_id 78845084879437824` (`jmills06`) → `owner_id` → **`roster_id: 1`**,
team name **"Jake's Predecessor"**. Everything `"me"` keys off roster 1.

Week 1 pairings by `matchup_id`: **1 v 6**, 2 v 7, 3 v 5, 4 v 8.

### Avatars

Resolution order:

1. `metadata.avatar` - full custom upload URL on `sleepercdn.com/uploads/`.
   Present for **5 of 8** (rosters 1, 4, 5, 6, 7).
2. `avatar` - a hash, rendered `https://sleepercdn.com/avatars/thumbs/{hash}`.
   Present for all 8.
3. Initials.

With that precedence the **initials fallback never fires in this league**.
Caveat: the `avatar` hashes are not unique - two hashes are shared across five
users, so they are Sleeper defaults, not personal images. The three rosters
that fall through to step 2 do not collide with each other, so no two teams
render the same picture.

### FAAB - answers an open question from section 11

**Yes.** `waiver_type: 2`, `waiver_budget: 200` (not $100 like ESPN),
`waiver_clear_days: 2`, `waiver_day_of_week: 2`. Every roster carries
`waiver_budget_used`. A budget block on the Sleeper IDLE board is viable.

### Per-player points come free - no stats endpoint needed

`/matchups/{week}` returns **both** `starters_points` (float array parallel to
`starters`) and `players_points` (per-player map including bench).

`points` equals the sum of `starters_points`. Verified on roster 1: starters
sum 22.2, `points` 22.2, bench players scoring 6.7 and 4.1 correctly excluded.

This fully satisfies the LIVE board with no call to Sleeper's undocumented
stats endpoint. The section 10 decision to avoid it costs nothing.

Bench totals must be `sum(players_points) - sum(starters_points)`, **excluding
taxi and IR players** or the number will be wrong.

### Transactions - usable, but week 1 is misleading

36 transactions, all `type: "free_agent"`, all `status: "complete"`.

- **`metadata` is null on every one.** No display text. Rendering "Team claimed
  Player" requires the player-ID lookup from `collect_players.py`. The moves
  block is blocked on that file.
- Many are **drops with `adds: null`** - dynasty offseason cuts. The renderer
  needs add-only, drop-only, and add+drop cases.
- Timestamps run back weeks before the season. Sleeper files all dynasty
  offseason activity under `leg: 1`, so week 1's "latest moves" shows stale
  offseason cuts. Sort by `created` descending and cap the list.
- **No waiver claims and no failed claims exist yet**, so the "includes failed
  waiver claims" warning is unverified. Keep the status filter regardless.

### winners_bracket is populated and cannot be trusted

At week 1, before any game has finished, `/winners_bracket` returns a complete
4-team bracket with concrete roster IDs in round 1 (`m1: 8 v 3`, `m2: 4 v 7`),
plus a final (`p: 1`) and third-place game (`p: 3`).

This cannot be real 2026 seeding. Either carried over from the previous dynasty
league or pre-seeded from all-zero standings.

**Gate any bracket use on `week >= playoff_week_start` (15).** Reading it
earlier renders a fabricated playoff picture. Re-check in week 15.
`losers_bracket` gets the same treatment.

Also in league `metadata`: `latest_league_winner_roster_id: "8"` - last
season's champion, a free defending-champ marker if wanted.

### Still unknown on Sleeper

| Unknown | Why still open |
|---|---|
| A `0` in `starters` meaning an empty slot | **Not observed.** All 8 rosters fully set. Keep the dashed-border empty row handling, but it is untested. |
| `fpts_against` recombination | The `fpts_against` keys are **absent** from roster settings right now. Presumably appear once games score. Re-check after week 1. |
| `week` vs `display_week` divergence | Both read 1. Cannot be observed until a week completes. |
| Streak computation | Needs two completed weeks to test the walk. |
| `/v1/players/nfl` shape | Skipped (opt-in). Needed before the moves block renders. |

---

## ESPN - section 6 table fully re-verified

League `1529795`, season 2026. `scoringPeriodId=1`, `currentMatchupPeriod=1`,
`latestScoringPeriod=1`.

### Every claimed fact held

| Fact | Handoff | Observed |
|---|---|---|
| League name | ZFL | ZFL |
| Teams | 12 | 12 |
| Team IDs sparse | 1,2,3,5,7,9,11,12,13,14,15,16 | identical |
| Starting slots | 10 | 10 |
| Slot layout | QB1 RB2 WR2 TE1 FLEX1 OP1 D/ST1 K1 | `lineupSlotCounts` `{0:1, 2:2, 4:2, 6:1, 7:1, 16:1, 17:1, 23:1}` - exactly that |
| Bench / IR | 6 / 1 | `{20:6, 21:1}` |
| Regular season | 14 matchup periods | `matchupPeriodCount: 14` |
| Playoffs | 7 of 12 | `playoffTeamCount: 7` |
| Scoring | H2H points | `scoringType: H2H_POINTS` |
| FAAB | $100 | `acquisitionBudget: 100` |
| Public? | No | `isPublic: False` |
| James's team | 9, "Forced Rankings", BELL | id 9, name "Forced Rankings", abbrev BELL |

### RESOLVED: which view returns per-player live points

**`view=mBoxscore`.** The path is:

```
schedule[].home|away
  .rosterForCurrentScoringPeriod.entries[]
    .lineupSlotId          -> which grid row
    .playerPoolEntry.player.fullName
    .playerPoolEntry.player.proTeamId
    .playerPoolEntry.player.stats[].appliedTotal
```

This was the single biggest ESPN unknown and it is closed. Three roster
variants are offered - `rosterForCurrentScoringPeriod`,
`rosterForMatchupPeriod`, `rosterForMatchupPeriodDelayed`. Use
`rosterForCurrentScoringPeriod`; with 1-week matchup periods the first two
should agree, and `Delayed` is ESPN's lagged copy.

**Important caveat.** In this pre-kickoff capture the only stat entry present
is `statSourceId: 1`, which is the **projection**, not actual points. Bijan
Robinson's `appliedTotal: 19.31` is a projected score.

The collector must select on `statSourceId`: **0 = actual, 1 = projected**,
both filtered to `statSplitTypeId: 1` and the right `scoringPeriodId`. The
projected path is observed. **The actual-points path (`statSourceId: 0`) is
inferred and must be confirmed during a live Sunday** before the LIVE board is
trusted.

This is also where the contract's ESPN-only `proj` field comes from.

**New requirement not in the handoff:** `proTeamId` is a **numeric ID** (1 =
ATL), not an abbreviation. The contract's `"t": "PHI"` needs a proTeamId →
abbreviation map. 32 stable entries, so hardcoding is fine.

**Second new requirement:** ESPN gives slot **counts**, not an ordered slot
list. Sleeper's `roster_positions` is an ordered array; ESPN's
`lineupSlotCounts` is a dict. **The collector must impose the row order
itself** so both boards render the same sequence. Suggested order:
QB, RB, RB, WR, WR, TE, FLEX, OP, D/ST, K.

### RESOLVED: totalProjectedPointsLive populates before kickoff

From `mMatchupScore`, per side:

```
totalPoints: 0.0        totalPointsLive: 0.0
totalProjectedPoints: 133.797   totalProjectedPointsLive: 133.797
winProbability: 0.48    adjustment: 0.0   tiebreak: 0.0
```

So `totalProjectedPointsLive` **is** populated pre-kickoff, not only during
games. Whether it diverges from `totalProjectedPoints` once games start is
still unverified - a Sunday check.

`totalPointsLive` is the live team score for the hero and matchup strip.

**Bonus, not in the data contract:** `winProbability` is available per side.
Worth considering for the hero, in the same spirit as `playoffPct`. Not
adopted - a design call for James.

### RESOLVED: custom team logos require auth

This is the one finding that forces work rather than just informing it.

| Host | Cookie-free probe |
|---|---|
| `g.espncdn.com` | **200** |
| `mystique-api.fantasy.espn.com` | **401** |

The board loads images client-side with no cookies, so mystique logos **will
not load**. The handoff's contingency applies: **the collector must mirror
those images into the repo.**

It is not just James's team. **4 of 12 teams** use mystique uploads - team IDs
**2, 9, 13, 14** - including James's own (team 9), which appears in the hero,
the standings and the matchup strip. The other 8 are `g.espncdn.com` vector
art, of which 2 are ESPN default logos.

### RESOLVED: how to retrieve transactions

`view=mTransactions2` **with no `x-fantasy-filter` header at all**: 200,
118KB, `transactions` array of **254** records.

The same call **with** an `x-fantasy-filter` header returned **HTTP 400**. The
filtered variant has been removed from `discover.py`; filter client-side
instead. The handoff's suggestion to drop the ESPN moves block if transactions
proved unreliable is not needed.

Record shape:

```jsonc
{ "type": "DRAFT", "status": "EXECUTED", "isPending": false,
  "teamId": 1, "bidAmount": 0, "proposedDate": 1788218649946,
  "scoringPeriodId": 1,
  "items": [ { "type": "DRAFT", "playerId": 3121422,
               "fromTeamId": 0, "toTeamId": 1,
               "fromLineupSlotId": -1, "toLineupSlotId": 23 } ] }
```

Notes for the moves block:

- **254 records are draft-dominated** - a 12-team draft is ~192 picks. Filter
  out `type: "DRAFT"` and sort by `proposedDate` descending.
- `playerId` is numeric with **no name in the payload**. Names are available
  from the roster views already being fetched
  (`playerPoolEntry.player.fullName`), so build the id → name map from
  `mBoxscore`/`mRoster` rather than adding an endpoint.
- `bidAmount` gives FAAB spend per claim, and `isPending` / `status`
  distinguish executed from pending.

### Team names need normalisation

Raw names include a double space ("Mousa  Baiz") and trailing whitespace
("QB Central  "). Collapse whitespace and trim in the collector or the
standings table will look broken.

### Stacked vs separate views

The handoff warns that combining views can return different results than
calling them separately. **No divergence was observed**, but this was not
tested exhaustively:

- `mBoxscore` and `mBoxscore&scoringPeriodId=1` are **byte-identical**
  (305,541), as are `mRoster` and `mRoster&scoringPeriodId=1` (1,497,833).
  Passing `scoringPeriodId` changes nothing while it already equals the
  current period. Whether it matters for a **past** week is untested.
- The combined calls returned supersets, consistent with a simple union.

Treat the warning as unproven rather than disproven, and re-check if a
combined call ever produces a surprising value.

### Still unknown on ESPN

| Unknown | Why still open |
|---|---|
| Per-player **actual** points (`statSourceId: 0`) | Only the projected entry exists pre-kickoff. **Confirm on a live Sunday.** Highest-priority remaining item. |
| Whether `totalProjectedPointsLive` diverges from `totalProjectedPoints` in-game | Identical pre-kickoff. Sunday check. |
| Whether `scoringPeriodId` matters for a past week | Untested - week 1 is the current period. |
| `leagueHistory` shape | Captured (41KB, 2025) but not reviewed. Out of scope for v1. |

---

## Impact on the build

Before `config/leagues.json` or any collector is written:

1. **Sleeper lineup grid is 10 rows, two FLEX, no K.** The 9-row assumption is
   dead. Both boards are 10 rows.
2. `roster_id: 1` is James on Sleeper; team `9` on ESPN.
3. `playoffCut` is **4** for Sleeper, **7** for ESPN.
4. Taxi and IR players must be excluded from Sleeper bench totals.
5. The Sleeper moves block depends on `collect_players.py` landing first
   (transaction `metadata` is null).
6. Sleeper bracket endpoints are gated on week 15.
7. A FAAB budget block ($200 Sleeper / $100 ESPN) is worth adding to IDLE.
8. **`collect_espn.py` must mirror 4 mystique logos into the repo.** They 401
   for the board. This is new mandatory work.
9. ESPN needs a proTeamId → abbreviation map and a hardcoded slot display
   order, neither of which the handoff anticipated.
10. ESPN transactions are fetched unfiltered and filtered client-side; drop
    `DRAFT` records.
11. Trim and collapse whitespace in ESPN team names.
12. **Re-run discovery during a live Sunday window** to confirm
    `statSourceId: 0` carries actual per-player points. The LIVE ESPN board
    should not be trusted until that is observed.
