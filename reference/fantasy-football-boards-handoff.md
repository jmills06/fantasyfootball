# Fantasy Football Boards — Claude Code Handoff

**Repo:** `jmills06/fantasyfootball` (public, currently empty)
**Owner:** James Mills (jmills06)
**Target:** DAKboard CPU v5 (Raspberry Pi 5B), 1080×1920 portrait, display-only, non-interactive
**Status at handoff:** Design agreed, mockups built, nothing in the repo yet.

---

## 1. What this is

Two ambient display boards, one per fantasy football league, rotating as separate
DakBoard slots. Both share identical chrome, layout, and styling. Only the league
name and the data differ.

- **Sleeper board** → `sleeper.html` → `jmills06.github.io/fantasyfootball/sleeper.html`
- **ESPN board** → `espn.html` → `jmills06.github.io/fantasyfootball/espn.html`

Each board has two states:

- **LIVE** (NFL game windows: Thu night, Sunday, Mon night, plus any Saturday or
  holiday game) — your matchup hero, then a head-to-head lineup grid of your
  starters vs your opponent's, then other games in progress. No transactions block.
- **IDLE** (all other times) — this week's matchup hero, then standings, then the
  week's matchups, then latest roster moves.

Mode is decided on the master tick by whether the clock is inside one of the
`windows` the collector writes from the NFL schedule (see `nfl_schedule.py`), not
by live game state. Payloads without `windows` fall back to day of week.

*Revised 2026-09-25 at the owner's request. Originally LIVE was Sundays only and
IDLE showed last week's result until Thursday night.*

---

## 2. Build order (follow this sequence)

1. **Discovery first.** Write `discover.py`, run both leagues, dump raw JSON to a
   gitignored `discovery/` folder. Review output before writing any board code.
   Section 6 lists exactly what must be confirmed. **Do not skip this.** The
   Sleeper half of this document is entirely unverified assumption.
2. Build `config/leagues.json` from discovery output.
3. Build `collect_sleeper.py` → `data/latest/sleeper.json`.
4. Build `collect_players.py` → `data/latest/players.json` (Sleeper only, daily).
5. Build `sleeper.html` against real JSON. Port layout from the mockups.
6. Build `collect_espn.py` → `data/latest/espn.json` to the same contract.
7. Build `espn.html` as a near-copy of `sleeper.html`.
8. Wire up workflows, enable Pages on `main`, register cron-job.org triggers.

---

## 3. Repo structure

```
fantasyfootball/
├── sleeper.html
├── espn.html
├── assets/board.css          shared styles, both boards link it
├── collect_sleeper.py
├── collect_espn.py
├── collect_players.py
├── discover.py
├── config/leagues.json
├── data/latest/
│   ├── sleeper.json
│   ├── espn.json
│   └── players.json
└── .github/workflows/
    ├── collect.yml           both leagues, workflow_dispatch
    └── players.yml           daily, workflow_dispatch
```

---

## 4. SECURITY — read before writing `collect_espn.py`

The ESPN league is private (`isPublic: false`, confirmed). The collector
authenticates with two browser cookies, `espn_s2` and `SWID`, stored as GitHub
Actions secrets `ESPN_S2` and `ESPN_SWID`.

**These cookies are full ESPN account access, not read-only league access. The repo
is public. Leaking them is a real account compromise, not a minor issue.**

Hard rules:

- Read them only from `os.environ`. Never hardcode, never commit, never put them in
  `config/leagues.json`.
- Never log request headers, the cookie dict, or a failed response body. On a 401,
  log the status code and nothing else.
- Never write raw ESPN responses to `data/latest/`. Write only normalized fields
  the board consumes.
- `discovery/` must be in `.gitignore` before `discover.py` is ever run.

Cookies expire. The collector must preserve the last good `espn.json` on auth
failure rather than overwriting it with an error state, and set a top-level
`"stale": true` flag the board renders as a small quiet indicator. A blank screen
is the failure mode to avoid.

---

## 5. Data contract

Both collectors write the same shape so one renderer serves both boards.

```jsonc
{
  "league":    "ZFL",
  "platform":  "espn",              // or "sleeper"
  "week":      2,                   // week the board is anchored on
  "stale":     false,
  "updated":   "2026-09-14T16:41:00Z",
  "playoffCut": 7,
  "hero": {
    "a": { "name": "...", "rec": "1-0", "pts": 98.4, "proj": 112.0,
           "logo": "https://...", "me": true },
    "b": { "name": "...", "rec": "0-1", "pts": 85.8, "proj": 104.5,
           "logo": "https://..." }
  },
  "lineup": [                        // slot order, both sides aligned
    { "pos": "QB", "a": {"n":"...","t":"PHI","p":24.6},
                   "b": {"n":"...","t":"DET","p":12.5} },
    { "pos": "FLEX", "a": {"n":"...","t":"SEA","p":16.6},
                     "b": {"empty": true, "p": 0.0} }
  ],
  "bench":     { "a": 34.2, "b": 41.8 },
  "matchups":  [ { "a": {"n":"...","logo":"..."}, "pa": 112.6,
                   "b": {"n":"...","logo":"..."}, "pb": 104.2 } ],
  "upcoming":  { "week": 3, "games": [
                 { "a": {"n":"...","rec":"1-1","me":true,"logo":"..."},
                   "b": {"n":"...","rec":"1-1","logo":"..."} } ] },
  "standings": [ { "t":"...", "w":2, "l":0, "pf":238.4, "s":"W2",
                   "playoffPct": 0.59, "logo":"...", "me": false } ],
  "moves":     [ { "k":"add", "txt":"<b>Team</b> claimed Player", "when":"2h" } ]
}
```

`proj` and `playoffPct` are ESPN-only. The renderer omits those elements when the
fields are absent, so the Sleeper board degrades cleanly without branching.

---

## 6. Discovery checklist

### Sleeper — NOTHING here has been verified against the live API

League `1389343119928991744`, 8 teams (stated by James). Confirm:

- `roster_positions` from `/v1/league/{id}` — the mockup assumes
  QB/RB/RB/WR/WR/TE/FLEX/K/DEF (9 slots). If wrong, the lineup grid row count changes.
- James's `roster_id` — match his `user_id` from `/v1/league/{id}/users` to
  `owner_id` in `/v1/league/{id}/rosters`. Everything "me" keys off this.
- `settings.playoff_week_start` and playoff team count. Mockup assumed 4 of 8.
- Whether managers have avatars set, and whether any have a custom team image URL
  in `metadata`. Determines how often the initials fallback fires.
- Whether all 8 managers set a `team_name`. Fall back to `display_name` if not.
- Whether the league uses FAAB. If so, a budget block is worth adding to IDLE.

### ESPN — partially verified

League `1529795`, season `2026`, James is team `9` ("Forced Rankings", BELL).
Confirmed from `mTeam`/`mStandings`/`mSettings`:

| Fact | Value |
|---|---|
| League name | ZFL |
| Teams | 12, single division |
| Team IDs | 1,2,3,5,7,9,11,12,13,14,15,16 — **sparse, never index by position** |
| Starting slots | 10 |
| Slot layout | QB1, RB2, WR2, TE1, FLEX1, SUPERFLEX(OP)1, D/ST1, K1 |
| Bench / IR | 6 / 1 |
| Regular season | 14 matchup periods |
| Playoffs | weeks 15–17, 1 week per round, **7 of 12 teams** |
| Playoff seeding tiebreak | total points scored |
| Scoring | H2H points, full PPR (1.0/reception), 4-pt passing TD |
| FAAB budget | $100, `acquisitionBudgetSpent` per team |
| Waivers | process daily at 11:00 |
| Public? | **No** — `isPublic: false` |
| Prior seasons | 2018–2025 available via `leagueHistory` |

Still to confirm in discovery:

- **Which view returns per-player live points.** `view=mBoxscore` with a
  `scoringPeriodId` param is the usual answer, possibly combined with `mRoster`.
  This drives the entire LIVE board and is the single biggest ESPN unknown.
- **How to retrieve transactions.** ESPN's transaction retrieval is messier than
  Sleeper's. `view=mTransactions2` with an `x-fantasy-filter` header is the common
  approach but needs verifying. If it proves unreliable, drop the moves block from
  the ESPN board rather than fake it.
- **Whether custom team logos load without auth.** Three logo flavors exist in this
  league: `g.espncdn.com` vector art, ESPN default vectors, and custom uploads on
  `mystique-api.fantasy.espn.com` (James's team is a custom upload). The board loads
  images client-side with no cookies. If the mystique host requires auth, the
  collector must mirror those images into the repo instead.
- Whether `totalProjectedPointsLive` populates during games or only pre-kickoff.

---

## 7. Platform gotchas

### Sleeper

- **Points are split across two integer fields.** `fpts` and `fpts_decimal` must be
  recombined, same for `fpts_against`. Miss this and standings show 204 instead of 204.9.
- **Win/loss streak is not in the API.** No endpoint returns "W2". Compute it by
  walking every prior week's matchups and comparing scores.
- **`starters` is in roster-slot order and identical across all teams**, so the
  head-to-head grid aligns row by row with no matching logic. This is why the
  layout works.
- **A `0` in the `starters` array means an empty slot.** Render it as its own row:
  dashed border, dimmed, "Empty", 0.0. Do not collapse it. The opposing side still
  takes the slot win.
- **Transactions are per-week and include failed waiver claims.** Filter on status
  and pull two weeks so the list isn't empty on a Tuesday.
- **The all-players file is ~5MB.** Fetch once daily in `collect_players.py`, write a
  trimmed name/position/team lookup. Never call it from the main collector.
- **Rate limit:** stay under 1000 calls/minute.
- **Next week's pairings** come from `/matchups/{week+1}` with zeroed points. This
  breaks in the playoffs — postseason pairings live in `winners_bracket` and
  `losers_bracket`.
- `/v1/state/nfl` returns both `week` and `display_week`, which diverge on Tuesdays.
  Both leagues roll their current week forward by Tuesday morning. **The boards
  anchor on the league's current week from Tuesday 04:00 ET**, so the upcoming
  matchup shows all week; from Monday until then they stay on the week with
  points so Monday night is never cut off. (Revised 2026-09-25, owner request.)

### ESPN

- Base URL is `lm-api-reads.fantasy.espn.com`, not `fantasy.espn.com`. The host
  changed in 2024 and older examples are broken.
- Pattern: `{base}/apis/v3/games/ffl/seasons/2026/segments/0/leagues/1529795?view=X&view=Y`
- Seasons 2017 and earlier use `/leagueHistory/{id}?seasonId={year}` instead.
- Multiple views can be stacked, but calling views in combination sometimes returns
  different results than calling them separately. Verify.
- `playoffTeamCount` is 7 of 12. **Do not use the Sleeper board's green-border
  playoff treatment** — highlighting 7 of 12 rows lights up most of the table and
  means nothing. Draw a single divider line between seed 7 and seed 8 instead.

---

## 8. Board implementation notes

Port from the mockups (`sleeper-board-mock-v3.html` and its two forced-state
copies). They are self-contained; split the CSS into `assets/board.css` when
porting.

**Constants at the top of each board:**

```js
const AUTO_FIT      = false;   // true only for browser preview
const LIVE_DAYS     = [0];     // 0=Sun. Add 4 for Thu night, 1 for Mon night.
const MODE_OVERRIDE = null;    // 'live' | 'idle' forces a state
const TICK_MS       = 60000;   // master tick: re-evaluates mode and redraws
const REFRESH_MS    = 900000;  // data poll, idle
const REFRESH_LIVE_MS = 90000; // data poll, live
```

**Layout rules that matter:**

- Rows in the swap zone use `flex: 1 1 0` with `min-height: 58px` and
  `max-height: 92px`, and the container uses `justify-content: center`. This is what
  stops slack pooling into a dead band under the last row. Do not revert to fixed
  row heights.
- 12 teams means 12 standings rows and 5 other matchups in the LIVE strip. Both
  blocks need attention that the 8-team mockup didn't require. Recommendation: on
  ESPN, replace the points-for column with playoff percentage, and show only the two
  closest games plus the week's high score rather than all five.
- The ESPN lineup grid is 10 rows, not 9 (superflex).

**Pi 5B constraints (carried from other boards in this suite):**

- No `backdrop-filter`, no canvas `shadowBlur`
- `transform` and `opacity` animations only
- Single master tick, cap effective frame rate ~30fps
- Signature-check data before rebuilding the DOM, to avoid reflow and animation restarts

**Design system** (from the Everyday Ham signage guide):

- Navy gradient background `#0d1620` → `#152333` → `#1e3347`
- Orange accent `#ff7030`, cream text `#fdf8e5`, hierarchy via opacity (100/80/50/30%)
- Gold `#E0A52E` for flex/special, green `#2ecc71` up, red `#e74c3c` down
- Oswald for headings, numbers, labels; Source Sans Pro for body
- Cards: `rgba(255,255,255,.05)` fill, `rgba(255,255,255,.1)` border, 10–16px radius
- Section headers: orange, uppercase, letter-spaced, with a fading rule to the right

**Graceful degradation:** preserve stale data on fetch failure, never clear the
screen. Both boards must render something sane before the season starts, when every
value is 0.0.

---

## 9. Pipeline

Standard pattern for this suite:

- GitHub Actions, triggered by **cron-job.org firing `workflow_dispatch`**. Built-in
  `schedule:` is unreliable here and should exist only as a commented backup.
- **Two schedules:** slow (every 6h) otherwise, fast (60–90s) during game windows
  (Thu night, Sunday, Mon night). Both hit the same workflow.
- **Git push race fix, mandatory:** `fetch-depth: 0` on checkout plus a 5-attempt
  rebase-retry loop (`git pull --rebase --autostash -X theirs origin main`). Two
  collectors writing `data/latest/` in one repo is exactly the case this guards.
- Public repo, so Actions minutes are unmetered.
- Enable Pages on `main`.

---

## 10. Decisions already made (do not relitigate)

- Separate board per league, identical styling. Not one combined screen.
- No per-player stat lines. Points, name, NFL team only. This deliberately avoids
  Sleeper's undocumented stats endpoint.
- No "yet to play" indicator on the Sleeper board. It would need an NFL schedule
  source. Accepted consequence: a player who hasn't kicked off shows 0.0, identical
  to one who played and scored nothing.
- Mode switches on the NFL schedule's game windows, not live game state.
  (Revised 2026-09-25, owner request; was day of week.)
- Empty starter slots get their own row.
- The board anchors on the current week from Tuesday 04:00 ET; the previous week
  is not shown after that. (Revised 2026-09-25, owner request; was the week that
  just finished.)
- Team avatars/logos shown in hero, standings, and the compact matchup strip, but
  **not** in the head-to-head column headers.

## 11. Open questions for James

- Sleeper: does that league use FAAB? If so, a budget block is worth adding.
- ESPN: prior seasons 2018–2025 are available via `leagueHistory`. All-time records
  and head-to-head history against specific opponents are possible on the ESPN board
  and impossible on the Sleeper one. Out of scope for v1, worth flagging as a
  deliberate later addition.
