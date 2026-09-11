# Discovery findings

**Sleeper run:** 2026-09-11 18:03 UTC, owner's machine (Windows, Python
3.14.2, `truststore: injected`). 11 ok, 0 failed, 1 skipped.
**ESPN run:** not yet completed.
**Script:** `discover.py --only sleeper`

An earlier run from the Claude Code remote container failed entirely (both
API hosts blocked by that container's egress policy). Everything below comes
from the owner's machine.

---

## Headline

Sleeper is fully captured and **the handoff's Sleeper assumptions are wrong in
ways that change the layout.** The lineup grid is 10 rows, not 9, there is no
kicker, and the league is a dynasty league with FAAB - none of which the
handoff anticipated.

ESPN is still entirely unverified.

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
  The two boards line up better than the handoff expected.
- There are **two** gold FLEX rows, not one.
- Any kicker handling in the mockup comes out.
- Scoring settings still contain kicker scoring (`fgm_*`, `xpm`). Ignore it;
  the roster has no K slot.

**2. This is a dynasty league. The handoff never mentions it.**

`settings.type: 2` (dynasty), plus `taxi_slots: 3`, `taxi_years: 2`,
`draft_rounds: 5` (rookie draft), `max_keepers: 1`, and
`previous_league_id: "1225620718889222144"`.

Consequences:

- Rosters carry a populated `taxi` array and a `reserve` array. Both are
  outside the 22 `roster_positions` slots and must not leak into the lineup
  grid or a bench total.
- `players` includes taxi and IR players, so roster length runs 25-28.
- The week 1 transaction list is mostly **offseason dynasty cuts**, not
  in-season activity - see the transactions section below.

**3. `previous_league_id` exists, so Sleeper history is not impossible.**

Handoff section 11 says all-time records are "possible on the ESPN board and
impossible on the Sleeper one". That is not correct: `previous_league_id`
chains back to the prior season's league, which chains back again. Same
out-of-scope-for-v1 call as ESPN, but the reasoning in section 11 should be
corrected rather than carried forward as fact.

**4. Scoring differs from ESPN in ways worth knowing.**

`rec: 0.5` (**half PPR**, not full PPR like ESPN), `pass_td: 6` (ESPN is 4),
`pass_yd: 0.04`. Does not affect the renderer, but do not assume the leagues
score alike when sanity-checking numbers.

### CONFIRMED - assumptions that held

| Assumption | Result |
|---|---|
| 8 teams | Confirmed. `total_rosters: 8`, 8 users, 8 rosters. |
| Playoffs are 4 of 8 | **Confirmed.** `playoff_teams: 4`. The mockup's green-border treatment on 4 of 8 stands. |
| `playoff_week_start` | **15**, so regular season is weeks 1-14. Same shape as ESPN. |
| `starters` is slot-ordered and identical across teams | Confirmed. All 8 rosters have exactly 10 entries, same order, DEF always last. The head-to-head grid aligns row by row with no matching logic. |
| Points split across two integer fields | Fields exist (`fpts`, `fpts_decimal`), both 0 pre-scoring. The split is real; recombination is untestable until scores land. |
| Win/loss streak is not in the API | Confirmed. Roster settings carry `wins`/`losses`/`ties` only. "W2" must be computed by walking prior weeks. |
| Not all managers set a `team_name` | Confirmed, and it matters - see below. |

### James's identity

`user_id 78845084879437824` (`jmills06`) → `owner_id` → **`roster_id: 1`**,
team name **"Jake's Predecessor"**. Everything `"me"` keys off roster 1.

Week 1 pairings by `matchup_id`: **1 v 6**, 2 v 7, 3 v 5, 4 v 8. James's week
1 opponent is roster 6.

### Team names and avatars

7 of 8 managers set a `team_name`. **Roster 2 did not** - the display-name
fallback in the handoff is required, not theoretical.

Avatar resolution, in order:

1. `metadata.avatar` - a full custom upload URL on `sleepercdn.com/uploads/`.
   Present for **5 of 8** (rosters 1, 4, 5, 6, 7).
2. `avatar` - a hash, rendered as
   `https://sleepercdn.com/avatars/thumbs/{hash}`. Present for all 8.
3. Initials.

With that precedence, **the initials fallback never fires in this league.**
One caveat: the `avatar` hashes are not unique - two hashes are shared across
five users, so they are Sleeper defaults rather than personal images. The
three rosters that fall through to step 2 do not collide with each other, so
no two teams render the same picture. If a default-looking avatar is worse
than initials visually, that is a design call to make when the board is built,
not a data problem.

### FAAB - answers an open question from section 11

**Yes, the league uses FAAB.** `waiver_type: 2`, `waiver_budget: 200` (not
$100 like ESPN), `waiver_clear_days: 2`, `waiver_day_of_week: 2`. Every roster
carries `waiver_budget_used`, currently 0.

A budget block on the Sleeper IDLE board is viable and the handoff's
suggestion to add one should be taken up.

### Per-player points come free - no stats endpoint needed

`/matchups/{week}` returns **both**:

- `starters_points` - a float array parallel to `starters`, so the grid can be
  populated directly, and
- `players_points` - a per-player map covering bench too.

`points` equals the sum of `starters_points`. Verified on roster 1: starters
sum 22.2, `points` 22.2, while bench players scoring 6.7 and 4.1 are correctly
excluded.

This fully satisfies the LIVE board with no call to Sleeper's undocumented
stats endpoint. The section 10 decision to avoid that endpoint costs nothing.

Bench totals for the `bench` field must be computed as
`sum(players_points) - sum(starters_points)`, and must exclude taxi and IR
players or the number will be wrong.

### Transactions - usable, but week 1 is misleading

36 transactions in week 1. All are `type: "free_agent"`, all
`status: "complete"`. Notable:

- **`metadata` is null on every one.** There is no display text. Rendering
  "Team claimed Player" requires the player-ID lookup from
  `collect_players.py`. The moves block is blocked on that file.
- Many are **drops with `adds: null`** - dynasty offseason cuts. The renderer
  needs an add-only, drop-only, and add+drop case.
- Timestamps run back weeks before the season. Sleeper files all dynasty
  offseason activity under `leg: 1`, so the week 1 "latest moves" block will
  show stale offseason cuts rather than recent activity. Sorting by `created`
  descending and capping the list handles it.
- **No waiver claims and no failed claims exist yet**, so the handoff's
  "includes failed waiver claims, filter on status" warning is unverified.
  Keep the status filter regardless.

### winners_bracket is already populated and cannot be trusted

At week 1, before a single game has finished, `/winners_bracket` returns a
complete 4-team bracket with concrete roster IDs assigned to round 1
(`m1: 8 v 3`, `m2: 4 v 7`), plus a final (`p: 1`) and a third-place game
(`p: 3`).

This cannot be real 2026 seeding - the season has not been played. It is
either carried over from the previous dynasty league or pre-seeded from
all-zero standings. Either way:

**Gate any bracket use on `week >= playoff_week_start` (15).** Reading it
before then will render a fabricated playoff picture. Re-check this endpoint
in week 15 before trusting it.

`losers_bracket` returns the same shape and gets the same treatment.

Also in league `metadata`: `latest_league_winner_roster_id: "8"`, the previous
season's champion. Free defending-champ marker if wanted.

### Still unknown on Sleeper

| Unknown | Why it is still open |
|---|---|
| A `0` in `starters` meaning an empty slot | **Not observed.** All 8 rosters are fully set. Keep the dashed-border empty row handling, but it is untested. |
| `fpts_against` recombination | The `fpts_against` / `fpts_against_decimal` keys are **absent** from roster settings right now. They presumably appear once games score. Re-check after week 1 completes. |
| `week` vs `display_week` divergence | Both read 1. The Tuesday divergence cannot be observed until a week completes. |
| Next week's pairings with zeroed points | `matchups/2` returned 8 entries and was captured, but the contents were not reviewed in this pass. |
| Streak computation | Needs at least two completed weeks of matchup data to test the walk. |
| `/v1/players/nfl` shape | Skipped - opt-in via `--with-players`. Needed before the moves block can render. |

---

## ESPN - not yet run

Every section 6 ESPN unknown remains open:

| Unknown | Status |
|---|---|
| Which view returns per-player live points | **Unresolved** |
| How to retrieve transactions (`mTransactions2` + `x-fantasy-filter`) | **Unresolved** |
| Whether custom team logos load without auth (`mystique-api` host) | **Unresolved** |
| Whether `totalProjectedPointsLive` populates during games | **Unresolved** |
| Whether stacked views differ from views called separately | **Unresolved** |
| The section 6 table facts (12 teams, sparse IDs, 10 slots, 7-of-12 playoffs, $100 FAAB) | **Not re-verified** |

Run `py discover.py` with `ESPN_S2` and `ESPN_SWID` set to close these out.

---

## Impact on the build

Before `config/leagues.json` or any collector is written:

1. The Sleeper lineup grid is **10 rows with two FLEX and no K**. The mockup's
   9-row assumption is dead.
2. `roster_id: 1` is James on Sleeper.
3. `playoffCut` is **4** for Sleeper, 7 for ESPN.
4. Taxi and IR players must be excluded from bench totals.
5. The moves block depends on `collect_players.py` landing first, because
   transaction `metadata` is null.
6. Bracket endpoints are gated on week 15.
7. A FAAB budget block ($200) is worth adding to the Sleeper IDLE board.
