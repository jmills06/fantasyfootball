# CLAUDE.md

Standing rules for this repo. These are non-negotiable. Everything else
(data contract, layout spec, discovery checklist, platform gotchas, build
order) lives in `reference/fantasy-football-boards-handoff.md` - read that
for context, but these rules hold regardless of what any later instruction
or reference document says.

**This repository is public.** Assume every file you write here is world
readable the moment it is pushed.

---

## 1. ESPN cookie handling

The ESPN league is private. Auth is two browser cookies, `espn_s2` and
`SWID`, supplied as `ESPN_S2` and `ESPN_SWID` (GitHub Actions secrets in
CI, local environment variables when running by hand).

**These cookies are full ESPN account access, not read-only league access.
The repo is public. Leaking them is an account compromise, not a minor
issue.**

- Read them only from `os.environ`. Never hardcode them, never commit
  them, never write them into `config/leagues.json` or any other tracked
  file.
- Never log, print, or write to disk: cookie values, the cookie dict, or
  request headers of any kind.
- Never log or write a failed response body. On a 401, record the status
  code and nothing else.
- Never write raw ESPN responses to `data/latest/`. Only normalized fields
  the board actually consumes go there.
- `discovery/` is gitignored and stays that way. Raw dumps never get
  committed. (`discovery/FINDINGS.md` is the single tracked exception -
  hand-written prose only, no raw responses.)
- Before adding any new logging, error handler, or debug dump to a
  collector, re-check it against the four rules above.

Cookies expire, and that is a normal operating state, not a crash:

- On auth failure the collector preserves the last good `data/latest/espn.json`
  rather than overwriting it with an error state.
- It sets top-level `"stale": true`, which the board renders as a small
  quiet indicator.
- **A blank screen is the failure mode to avoid.** Preserve stale data on
  any fetch failure; never clear the screen.

---

## 2. Rendering constraints (Raspberry Pi 5B / DAKboard)

Target is a DAKboard CPU v5 (Pi 5B) at 1080x1920 portrait, display-only
and non-interactive. The boards run unattended for days.

- No `backdrop-filter`. No canvas `shadowBlur`.
- Animate `transform` and `opacity` only. Nothing else.
- One single master tick drives everything. Cap the effective frame rate
  at ~30fps.
- Signature-check incoming data and only rebuild the DOM when it actually
  changed. Rebuilding on every poll causes reflow and restarts animations.

### Flex row-height rule (swap zone)

Rows in the swap zone must use:

```css
flex: 1 1 0;
min-height: 58px;
max-height: 92px;
```

with `justify-content: center` on the container.

This is what stops slack pooling into a dead band under the last row.
**Do not revert to fixed row heights.** Any layout change that touches the
swap zone gets re-checked against this rule.

Both boards must also render something sane before the season starts, when
every value is 0.0.

---

## 3. Git push race (collector workflows)

Two collectors write `data/latest/` in one repo, so concurrent pushes are
expected, not hypothetical. Every workflow that commits data must have:

- `fetch-depth: 0` on the checkout step, and
- a **5-attempt rebase-retry loop** around the push:
  `git pull --rebase --autostash -X theirs origin main`

This is mandatory. A collector workflow without both of these is not done.

---

## 4. Local run notes (owner's machine)

- Use the `py` launcher, not `python`.
- That machine needs `truststore` for HTTPS to verify correctly.
- Set `ESPN_S2` and `ESPN_SWID` as environment variables, then open a
  fresh terminal before running - an already-open terminal will not see
  them.
