# NFL Survivor Pool Optimizer

`survivor_optimizer.ipynb` is a Jupyter notebook — you edit a config cell
and re-run it each week, rather than passing command-line flags. It's the
one you'll actually sit with and interact with, so a notebook fits better
than a script.

`fetch_odds.py` and `fetch_pick_pcts.py` are plain scripts — they do one
thing (fetch data, write a CSV) with nothing to inspect in between, so a
script is simpler to run and easier to automate later if you want to.

`herding_calibration.ipynb` is a diagnostic notebook — it tests the
fallback pick-share model against real data and is how the current
`HERDING_STRENGTH` default was actually derived, not guessed. See "Fetching
pick percentages" and the equity-mode section below for details.

## Quick start

```
pip install pandas numpy scipy requests lxml

# Fetch this week's DraftKings odds automatically (see "Fetching odds" below):
export ODDS_API_KEY=your_key_here
python fetch_odds.py --out odds.csv

# Fetch real pick-percentage data for the current week (see "Fetching pick
# percentages" below):
python fetch_pick_pcts.py --week 1 --year 2026 --out picks.csv

# Open survivor_optimizer.ipynb, set ODDS_CSV = "odds.csv" (and PICKS_CSV =
# "picks.csv" if using equity mode) in the config cell, then run it.
```

State (teams used, current week) is saved to `survivor_state.json` and picked
back up automatically on the next run.

## Fetching odds automatically

**Naming note first, because it matters:** there are two different, unrelated
services with confusingly similar names — `theoddsapi.com` (no hyphens) and
`the-odds-api.com` (hyphenated). `fetch_odds.py` deliberately points at the
hyphenated one (`api.the-odds-api.com`) — it's the long-established service
with a public GitHub org and SDKs in Python/Node/PHP/Rust. If odds fetching
ever mysteriously stops authenticating, check you're still pointed at the
hyphenated domain before anything else — that's exactly what happened during
development of this script.

DraftKings itself has no public API — no developer portal, no self-serve
key, no documentation. `fetch_odds.py` uses the aggregator above, which
licenses DraftKings' odds among 50+ books and exposes them through a
documented, self-serve REST API.

1. Get a key at https://the-odds-api.com — check their site for current
   tiers/pricing.
2. `export ODDS_API_KEY=your_key_here` (or pass `--api-key` directly).
3. Run `python fetch_odds.py --out odds.csv`.

**Week bucketing uses a verified date table, not a formula.** Games are
matched to NFL week numbers using `WEEK_START_DATES_2026`, a hardcoded list
of each week's real start date, sourced from the league's official schedule
and cross-checked against independent listings — not calculated from a
single anchor date. This matters: a real NFL season isn't evenly spaced.
Both the season opener and Thanksgiving week start a day early (Wednesday
instead of the usual Thursday), and a fixed "every week is exactly 7 days"
formula silently mislabels every week after the first one that breaks that
assumption — which is exactly what happened during development of this
script, and is worth knowing about if you're troubleshooting odd results.
If you ever spot a mismatch for some other week (an international game, a
schedule change), pass `--week-starts your_dates.json` with a corrected
18-date list rather than trying to patch a formula back in — or for a future
season, generate a fresh 18-date list from that year's schedule.

**One important expectation-setter:** this will *not* return all 18 weeks of
games in one call, even though DraftKings may have distant "look-ahead"
prices floating around somewhere. Individual game moneylines are typically
only posted a week or two before kickoff — the response will just contain
whatever's currently live, and future weeks will show up as you re-run the
script closer to those games. That's fine; it's exactly what the rolling
workflow below is built around.

**Games that have already kicked off are excluded entirely, not just
filtered by week.** Once a game starts, its moneyline stops being a
pre-game prediction and becomes a live, in-game line reflecting the
current score instead — mixing that into the same file as every other
game's real pre-game odds would silently corrupt the comparison, so
`games_to_rows` drops it. This also covers what happens once a game
*ends*: the same check excludes it too, regardless of what the raw API
itself does with concluded games (return a stale final line, drop it,
anything else) — this is controlled directly rather than assumed. If a
week's last remaining game has started, that week may show fewer than the
usual number of teams; that's correct, not a bug — you can no longer
newly pick into a game that's already underway anyway.

Real pick-percentage and availability data for equity mode come from
`fetch_pick_pcts.py` and your pool platform's own report, respectively —
see "Fetching pick percentages automatically" below.

## The weekly workflow

1. Run `fetch_odds.py` to refresh `odds.csv` with current lines.
2. Open `survivor_optimizer.ipynb`, set `ODDS_CSV = "odds.csv"`, and run it.
   It solves the assignment problem across **every remaining week**, not
   just this one — that's what makes the current week's recommendation
   correct (it already accounts for how much you'll need each team later).
3. Only act on the top row (`<-- THIS WEEK'S PICK`). Treat the rest of the
   printed plan as a reference, not a commitment.
4. After you make your real pick, set `LOCK = "TEAM"` and re-run once, then
   set it back to `None`.
5. Next week, repeat from step 1 with fresh odds.

## How the state file actually works

`survivor_state.json` is just a plain file on disk that gets read at the
start of each run and written to when you set `LOCK` (and when you set
`DOUBLE_WEEKS`). It's the only thing carrying memory between separate runs
of the notebook — there's no database, no shared memory, nothing else
involved.

**Multiple pools share one file, distinguished by `POOL_NAME`.** Each
pool's data (used teams, current week, double-pick weeks) is stored under
its own name inside the same JSON file — set `POOL_NAME = "family"` for
one pool and `POOL_NAME = "work"` for another, both pointing at the same
`STATE_FILE`, and they stay completely independent. Nothing needs to be
created ahead of time; the first `LOCK` (or `DOUBLE_WEEKS`) for a given
pool name creates its entry automatically. If you mistype a pool name in a
file that already has other pools in it, you'll get a warning listing the
pool names that actually exist, rather than silently looking like a fresh
season with no progress.

**One important note on write timing:** just running the notebook to see a
recommendation never writes anything — only `LOCK` and `DOUBLE_WEEKS`
actually save. So switching `POOL_NAME` to preview a pool you haven't
touched yet is completely safe; it won't create an entry for it until you
actually lock a pick or set its double-pick weeks.

**On using the same team in multiple pools:** that's not a conflict to
avoid — it's usually correct. Each pool is a separate competition with a
separate prize; "don't reuse a team" is scoped to one pool's season, not
across every pool you're in. If a team is your best pick, it's your best
pick everywhere you're allowed to take it.

## The math, briefly

Surviving the pool means winning every single week you play. Your season
survival probability is the **product** of the win probabilities of your 18
picks. Maximizing a product is the same as maximizing a sum of logs, so:

- Build a matrix of `log(win probability)` for every (week, team) pair, with
  bye weeks and already-used teams excluded.
- Find the set of one-team-per-week picks (no team repeated) that maximizes
  the total. This is a weighted bipartite matching problem — the classic
  **assignment problem** — solved exactly via the Hungarian algorithm
  (`scipy.optimize.linear_sum_assignment`), not by heuristics or brute force.

This is provably better than picking the highest-probability team each week
greedily, because greedy has no way to account for a team's value in a
*future* week. On the included synthetic example (`sample_odds.csv`), greedy
gets 38.9% survival probability; the optimal plan gets 49.6%, using the exact
same players, just sequenced correctly.
## `MODE = "equity"` (real pot-splitting math, not a tunable heuristic)

If your pool is winner-take-all and could end with multiple survivors
splitting the pot, pure survival-probability maximization isn't the full
story — a slightly lower-probability pick that fewer other entrants are
also taking can raise your *expected pot share* even though it's a worse
bet in isolation. Equity mode optimizes for that directly.

### The actual math

If you pick team X and it wins, you split the pot with everyone else who
also survived. Let `p_X` = win probability, `f_X` = the fraction of the
still-alive field also picking X this week, and `S = sum(f_Y * p_Y)` summed
over every team playing that week (the field's aggregate expected survival
rate this week — a property of the whole slate, not of any single pick).
Your expected pot share from picking X works out to:

```
value(X)  proportional to  p_X / (S + f_X * (1 - p_X))
```

That's derived directly from pot-splitting mechanics, not a tunable ratio.
Two boundary cases confirm the shape is right:
- **Nobody else picks X** (`f_X → 0`): value → `p_X / S` — full, undiluted
  credit for your win probability, scaled by how much of the *rest* of the
  field is expected to survive around you.
- **The whole field converges on X** (`f_X → 1`): value → `p_X` — matches
  "everyone splits together." (The external pot-size scaling that would
  turn this into an actual dollar figure is a constant multiplier across
  every candidate pick in a given week, so it can't change which team is
  best — only the payout's absolute size — and is correctly left out.)

For a double-pick week, both picks need to hit, so the field's aggregate
survival rate for that week is `S**2` instead of `S`. Real pick-percentage
data is essentially always per-team, not per-combination, so the dilution
term is approximated per-team rather than solved exactly for the specific
pair — a reasonable approximation given the data that actually exists in
practice, but worth knowing about.

### The fallback model (when a team/week has no real `--picks` data)

You'll rarely have real percentages for every team in every remaining week
— realistically only the current week (see `fetch_pick_pcts.py` below).
Every other week's estimate combines three independently-verified factors:

1. **Herding** — `win_prob ** herding_strength`, favorites assumed more
   popular. `HERDING_STRENGTH` (default 8.0 — not a guess; see
   `herding_calibration.ipynb` for how this was empirically derived from
   real 2026 Week 1 data, with a held-out validation check confirming it's
   not just overfit to that one dataset) is yours to adjust; it's an
   exponent, so it can only ever concentrate the estimate *more* sharply
   onto favorites as it increases — it can never flip the relationship the
   way the old weighted-ratio design could.
2. **Availability** — a team already used by most of the field *cannot* be
   picked by most of the field, no matter how attractive it looks. Ignoring
   this can predict literally impossible pick shares (a real example this
   tool once produced: 40% predicted share for a team only 30% of the pool
   could still choose). `AVAILABILITY_CSV` takes a current-week snapshot
   (`team,availability_pct`) from your pool platform; every week after that
   is *projected forward* by subtracting each week's predicted usage from
   the week before.
3. **Future-value urgency** — a team that's *also* strong in many other
   remaining weeks is less urgent to use right now, since a savvy player
   can save it for later; a team whose strength is a one-off this week has
   no such reason to wait. Approximated as `win_prob_this_week /
   (win_prob_this_week + average win_prob across this team's other
   remaining weeks)`. No separate tunable — always on.

### Where pool size actually matters (and where it doesn't)

Once you know the real pick distribution, **pool size doesn't change which
team is best** — it cancels out of the ranking entirely; only the shape of
`f_Y` across teams does. `POOL_SIZE` is therefore purely informational —
it prints a projected pool-size / field-survival-rate trajectory table
alongside your picks (projected forward from your current, real
remaining-entries count using modeled field survival rates), but it does
**not** adjust which team gets recommended.

There used to be a `fade_threshold` mechanism here that faded the equity
correction back toward pure survival-maximization as the projected pool
shrank — this was removed. It rested on the assumption that a full pool
wipeout is a disaster worth protecting against, which isn't true for every
pool: if your pool pays out **last team standing** (whoever survives
longest wins, even if that's short of the full season) rather than
requiring survival all the way to week 18, a projected wipeout isn't a
disaster — it's the normal way the format resolves, and staying
differentiated from a correlated pack is exactly what helps you outlast it.
Simulation confirmed this directly: decorrelating from the field, at equal
win probability, costs nothing in expectation and converts a guaranteed
partial split into a real shot at the whole pot. If your pool's payout rule
is different, this tradeoff may not apply the same way — worth thinking
through against your specific pool's actual rules rather than assuming.

## `herding_calibration.ipynb` (how the default was actually derived)

`HERDING_STRENGTH` used to default to 2.0 — a reasonable-looking guess with
no real backing. It's now 8.0, and this notebook is the reason why, not
just an assertion. It exists to answer one question properly: does the
fallback model's blind guess actually resemble real crowd behavior, and
what value of `herding_strength` fits best?

**Why this is possible without waiting for future weeks.** Real pick
percentages only exist for the current week (see above) — but that's
enough. Feed the model your real *current-week* percentages, run the
fallback blind against the same week pretending it doesn't have them, and
compare. No future data required.

**Why a raw comparison isn't enough on its own.** Sweeping a range of
`herding_strength` values and reporting whichever one best matches the real
data is circular — searching for the minimum of an error curve and then
reporting that minimum as "evidence" doesn't prove anything, since a search
is guaranteed to find *something* with low error against whatever it
searched over. The notebook does a second, real check: it repeatedly splits
the teams into two random halves, picks the best-fitting value using only
one half, then scores that same choice against the *other* half — data it
never saw during the search. If the same value keeps winning against teams
it wasn't fit to, across many random splits, that's genuine evidence, not
a curve-fitting artifact.

Run this any week you have real percentages (current default, `h=8`, was
derived from real Week 1 2026 data — 86% of 50 held-out splits landed on
`h=7` or `h=8`, with a median generalization ratio of 1.26x). Re-running it
in later weeks either reinforces that value or gives real grounds to change
it — this is meant to be an ongoing check, not a one-time record.

## Fetching pick percentages automatically

`fetch_pick_pcts.py` pulls real consensus pick percentages from
survivorgrid.com — a small, fan-run survivor-strategy site whose stated
purpose is exactly this. It's a plain server-rendered HTML table (no JS
rendering, no bot-hardened platform):

```
python fetch_pick_pcts.py --week 5 --year 2026 --out picks.csv
```

The page shows four percentage columns — Yahoo, ESPN, USA Football Pools,
and survivorgrid's own blended "Projected" estimate. This defaults to
Projected; override with `--source yahoo|espn|usa` for one platform's
number specifically.

**Same expectation-setter as the odds data:** this can only ever return
real numbers for the *current* week (maybe next) — pick percentages for a
week that hasn't opened yet don't exist anywhere, for the same structural
reason lines aren't posted far in advance. Every week beyond that falls
back to the three-factor model above when you run `survivor_optimizer.ipynb`
in equity mode.

Team code note: survivorgrid uses `WSH` for Washington; this project uses
`WAS` everywhere else — normalized automatically.

## Double-pick weeks

Some pools require picking TWO teams in certain weeks — both must win, or
you're eliminated (both still permanently used, same as any other pick).
Configure which weeks in the config cell:
```
DOUBLE_WEEKS = [12, 15]
```
This is saved into state the moment you run the notebook with a non-empty
list, so you only need to set it once — leave it in place, or change it
anytime the contest's rules do.

**No new math is needed for this.** A double-pick week is represented
internally as two "slots" that both need a team, both using that week's
odds. Since the assignment algorithm can never assign the same team to two
slots, it automatically finds the best *two distinct* teams for that week —
same Hungarian-algorithm solve, just a couple of extra rows in the matrix.
Survival probability for that week is the product of both teams' win
probabilities (treating the two games as independent, a reasonable
assumption for two unrelated NFL games).

Locking a double-pick week takes two comma-separated teams instead of one:
```
LOCK = "BUF,KC"
```
The notebook checks the count against whether that week is configured as
double-pick and errors clearly if it doesn't match.

**One safety check worth knowing about:** if a double-pick week's two
*recommended* teams happen to be playing each other, at most one of them
can actually win — that pairing can never survive. This is normal-case
impossible (the joint probability of two head-to-head teams both winning is
almost always worse than picking two unrelated favorites) but becomes
possible in extreme scarcity — e.g. very late season with almost no unused
teams left playing that week. The notebook detects this and prints an
explicit warning rather than silently recommending a guaranteed loss; if
you ever see it, lock one of the two teams to something else by hand.

## File formats

**Odds** (`ODDS_CSV`) — two rows per game, one per team:
```
week,team,opponent,moneyline
1,BUF,ARI,-250
1,ARI,BUF,210
```
American odds. The notebook de-vigs each game by normalizing both teams'
implied probabilities to sum to 100% (standard multiplicative method). A
team simply absent from a given week is treated as being on a bye.

**Pick popularity** (`PICKS_CSV`, optional, for equity mode):
```
week,team,pick_pct
1,BUF,0.34
```
As a fraction (0–1) or percentage (0–100) — either is auto-detected. Real
data where you can get it (see `fetch_pick_pcts.py`); rows missing for a
team/week fall back to the three-factor estimation model described above.

**Availability** (`AVAILABILITY_CSV`, optional, for equity mode):
```
team,availability_pct
BUF,0.62
```
What fraction of the still-alive field still has each team unused, as of
right now — a snapshot, not a per-week file, since it's a real-world fact
about the current moment. Many pool platforms show this directly. Not
required; without it, every team is assumed fully available, which
reproduces the old behavior.

## Notes / known limitations

- Ties are treated as a loss (standard survivor rule); this isn't modeled
  separately since NFL moneylines are two-way and already price it in.
- The de-vig method is the simple multiplicative one. It's standard and
  good enough here — more elaborate methods (e.g. Shin's method) exist if
  you want to refine it further, but won't change picks much.
- Feasibility (a live team available every remaining week) is essentially
  guaranteed with 32 teams and ≤18 weeks; the notebook will warn you if it
  ever can't find one rather than silently failing.
- `load_odds()` guards against messy input: duplicate (week, team) rows
  (e.g. from combining more than one fetch into one file) are flagged with
  the exact conflicting values and resolved by keeping the last occurrence;
  any row left with a mismatched partner as a side effect of that cleanup
  gets dropped rather than silently producing an impossible win probability.
  These warnings mean your odds file actually has a data problem worth
  tracking down — they'll keep reappearing on a messy file no matter how
  many times you re-run it, since re-running can't fix the file itself. If
  you hit this, the most reliable fix is usually a completely fresh
  `fetch_odds.py` run rather than trying to patch the existing CSV.
