"""
Fetch current NFL odds for all remaining weeks via 
https://the-odds-api.com and write them into a .csv file.
"""

# ----------------------------------------------------------------------
# IMPORTS
# ----------------------------------------------------------------------
import argparse
import csv
import json
import math
import re
from datetime import date, datetime, timezone
from io import StringIO
from zoneinfo import ZoneInfo
import requests
import sys
import pandas as pd

# ----------------------------------------------------------------------
# ARGUMENTS
# ----------------------------------------------------------------------
# If running from VSCode interface instead of terminal, arguments can be
# adjusted here
if len(sys.argv) == 1: 
    sys.argv += ["--output", "odds.csv", "--api-key", "73cfcfe9cc68459198ac3ab9a7eac496"]

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
# The site used to pull live odds from
API = "https://api.the-odds-api.com/v4"

# The start date of each week of the NFL season to ensure odds of each game are 
# pulled and classified correctly
WEEK_START_DATES = [
    date(2026, 9, 9),    # Week 1  -- Wed (Season Opener)f
    date(2026, 9, 17),   # Week 2  -- Thu
    date(2026, 9, 24),   # Week 3  -- Thu
    date(2026, 10, 1),   # Week 4  -- Thu
    date(2026, 10, 8),   # Week 5  -- Thu
    date(2026, 10, 15),  # Week 6  -- Thu
    date(2026, 10, 22),  # Week 7  -- Thu
    date(2026, 10, 29),  # Week 8  -- Thu
    date(2026, 11, 5),   # Week 9  -- Thu
    date(2026, 11, 12),  # Week 10 -- Thu
    date(2026, 11, 19),  # Week 11 -- Thu
    date(2026, 11, 25),  # Week 12 -- Wed (Thanksgiving Eve)
    date(2026, 12, 3),   # Week 13 -- Thu
    date(2026, 12, 10),  # Week 14 -- Thu
    date(2026, 12, 17),  # Week 15 -- Thu
    date(2026, 12, 24),  # Week 16 -- Thu
    date(2026, 12, 31),  # Week 17 -- Thu
    date(2027, 1, 7),    # Week 18 -- Thu
]

# Maps full team names to abbreviations to connect with other sources (pick distribution percentages)
TEAM_CODES = {
    "Buffalo Bills": "BUF", "Miami Dolphins": "MIA", "New England Patriots": "NE", "New York Jets": "NYJ",
    "Baltimore Ravens": "BAL", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Pittsburgh Steelers": "PIT",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Tennessee Titans": "TEN",
    "Denver Broncos": "DEN", "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Dallas Cowboys": "DAL", "New York Giants": "NYG", "Philadelphia Eagles": "PHI", "Washington Commanders": "WSH",
    "Chicago Bears": "CHI", "Detroit Lions": "DET", "Green Bay Packers": "GB", "Minnesota Vikings": "MIN",
    "Atlanta Falcons": "ATL", "Carolina Panthers": "CAR", "New Orleans Saints": "NO", "Tampa Bay Buccaneers": "TB",
    "Arizona Cardinals": "ARI", "Los Angeles Rams": "LAR", "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA",
}

# ----------------------------------------------------------------------
# WEEK CLASSIFICATION
# ----------------------------------------------------------------------
def assign_game_week(start_time, week_start_dates=WEEK_START_DATES):
    # Bin each game into its correct week designation based on its scheduled
    # start date/time (based on Eastern timezone)

    # Convert start date/time to Eastern timezone
    game_date = datetime.fromisoformat(start_time.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).date()
    # Assigns NFL week to each game based on where on the weekly calendar the
    # game is scheduled for
    for i in range(len(week_start_dates) - 1):
        if week_start_dates[i] <= game_date < week_start_dates[i + 1]:
            return i + 1
    if game_date >= week_start_dates[-1]:
        return len(week_start_dates)
    else:
        return -1

# ----------------------------------------------------------------------
# RETRIEVE ODDS
# ----------------------------------------------------------------------
def fetch_odds(api_key):
    # Makes API request (using DraftKings as bookmaker because they provide
    # odds for all future games)
    resp = requests.get(
        f"{API}/sports/americanfootball_nfl/odds",
        params={
            "apiKey": api_key,
            "regions": "us",
            "markets": "h2h",
            "oddsFormat": "american",
            "bookmakers": "draftkings",
        },
        timeout=15,
    )

    resp.raise_for_status()

    # Prints how many API requests this key has remaining on the free trial
    # Only 500 are provided per month
    req_remaining = resp.headers.get("x-requests-remaining")
    if req_remaining is not None:
        print(f"API requests remaining: {req_remaining}")

    data = resp.json()

    return data

# ----------------------------------------------------------------------
# CONVERT RESPONSE TO .CSV
# ----------------------------------------------------------------------
def response_to_csv(games, grid, week_start_dates=WEEK_START_DATES):
    # Convert the API response JSON into .csv format. One row is present per
    # team (two per game) showing the week, their opponent, and their odds to
    # win. Once a game starts, that game's odds will not appear in this file
    # to avoid accidentally pulling live odds and since once a game starts, they
    # cannot be selected in a survivor pool.

    csv_rows = []
    current_time = datetime.now(timezone.utc)

    for game in games:
        game_start = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))
        # Excludes games that have already started. Games that have been completed in the past
        # will not have odds, but live games will and are dropped here. 
        if game_start <= current_time:
            continue

        # If the game occurs before the regular season begins (likely a preseason game)
        # or ends (likely a playoff game), it is skipped and note included in the 
        # resulting .csv file.
        game_week = assign_game_week(game["commence_time"], week_start_dates)
        if not (1 <= game_week <= len(week_start_dates)):
            continue 

        # Checks if the JSON response for a game has a bookmaker of DraftKings and a market of h2h 
        # (moneyline). If so, those teams' abbreviations are retrieved and the week, team, opponent,
        # moneyline, and source of the odds are formatted to be converted to .csv later.
        bookmaker = None
        for b in game.get("bookmakers", []):
            if b.get("key") == "draftkings":
                bookmaker = b
                break
        market = None
        for m in bookmaker.get("markets", []):
            if m.get("key") == "h2h":
                market = m
                break

        # Replaces full team names with abbreviations
        outcome_a, outcome_b = market["outcomes"]
        team_a = TEAM_CODES.get(outcome_a["name"])
        team_b = TEAM_CODES.get(outcome_b["name"])

        # Structures .csv format
        csv_rows.append({"week": game_week, "team": team_a, "opponent": team_b, "moneyline": outcome_a["price"], "source": "draftkings"})
        csv_rows.append({"week": game_week, "team": team_b, "opponent": team_a, "moneyline": outcome_b["price"], "source": "draftkings"})

    # Since games can be missing from the-odds-api (whether retrieving just DraftKings 
    # odds or the entire schedule), this part determines which games are missing from
    # survivorgrid's full schedule. They will then be filled with survivorgrid odds 
    # later on.

    # Retrieves each week/team combination that has DraftKings odds
    has_odds = {(row["week"], row["team"]) for row in csv_rows}
    # This set stores games just to make sure they are not added twice and,
    # therefore, not given duplicate rows later on.
    already_added = set()
    # This list stores each week/team/opponent combination that does not have
    # DraftKings odds and will need to get their odds from survivorgrid
    missing_odds = []
    # Searches each team and each week they have a game from survivorgrid
    for team, weekly_games in grid.items():
        for week, (opponent, spread) in weekly_games.items():
            # If there are already DraftKings odds, skip this week/team pair
            if (week, team) in has_odds:
                continue
            # This ensures that team/opponent pairs are the same even if the 
            # order is flipped
            matchup = (week, frozenset({team, opponent}))
            # If the game was already added to the set, it is not added again
            if matchup in already_added:
                continue
            # If the game has not been added yet, it is added to the set. After 
            # this, it is known exactly which games are missing odds.
            already_added.add(matchup)

            # If the game is not in the-odds-api schedule, and only the survivorgrid schedule
            # shows the game, the game time is not known. This checks if the week has 
            # already started because if so, we can assume the survivorgrid odds are either live
            # or in the past, and those games can be dropped. DraftKings will have odds for the
            # games in the current week that have not already started/been played.
            # TODO: REVISIT THIS
            if week - 1 < len(week_start_dates) and current_time.date() >= week_start_dates[week - 1]:
                continue

            missing_odds.append((week, team, opponent))

    return csv_rows, missing_odds

# ----------------------------------------------------------------------
# SURVIVORGRID BACKUP
# ----------------------------------------------------------------------
# For any game DraftKings doesn't have odds for, this retrieves the last
# available odds from survivorgrid.com. 

def fetch_site():
    # Retrieves survivorgrid website which odds will be pulled from
    
    # Makes HTML request to web scrape site
    resp = requests.get(
        "https://www.survivorgrid.com/",
        headers={"User-Agent": "Mozilla/5.0 (compatible; survivor-pool-optimizer)"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.text

def parse_spread(cell):
    # Pulls the numeric spread out of a cell.
    text = str(cell).strip().upper()
    components = text.split()
    # If there is no text or the team is on a BYE, return nothing
    if "BYE" in components:
        return None
    # If the game is a pick 'em, return 0 as the spread.
    if "PK" in components:
        return 0.0
    # If neither, we return the last part, which is the point spread
    return float(components[-1])

def parse_opponent(cell):
    # Pulls the opponent's team code out of a cell like "ARI -9.5", "@BUF +3",
    # or "(N)PHI +1.5" -- None for BYE weeks, matching parse_spread's convention.
    # Needed so the grid can double as a schedule reference, not just a source
    # of spreads -- without this, there'd be no way to know WHO a team missing
    # from DraftKings is actually playing.
    text = str(cell).strip().upper()
    components = text.split()
    if "BYE" in components:
        return None
    opponent = components[0]
    if opponent.startswith("@"):
        opponent = opponent[1:]
    if opponent.startswith("(N)"):
        opponent = opponent[3:]
    return opponent

def parse_grid(html, current_week):
    # Parses the grid page into a dictionary containing each team along with
    # their opponent and the point spread for each of their games each week

    # Reads tables contained in the HTML page. Without specifying lxml as
    # the flavor, an error will be thrown.
    tables = pd.read_html(StringIO(html), flavor="lxml")

    # Finds the table that contains the data needed (teams and spreads, which for week 1, 
    # are listed under the "1" column)
    target = None
    for df in tables:
        columns = [str(c).strip() for c in df.columns]
        if "Team" in columns and current_week in columns:
            target = df
            break
    if target is None:
        raise RuntimeError("Couldn't find the grid table on survivorgrid.com -- its layout may have changed.")

    # Grabs all columns of our target table
    target.columns = [str(c).strip() for c in target.columns]
    grid = {}
    for _, row in target.iterrows():
        # Grabs team from each row in grid
        team = str(row.get("Team", "")).strip().split()[0]
        # For each team and week of the NFL season, access the column
        # corresponding to that week and grab and parse the opponent + spread
        weekly_games = {}
        for week_num in range(1, 19):
            col = str(week_num)
            # Some weeks may not have a column yet -- skip rather than crash
            if col not in target.columns:
                continue
            spread = parse_spread(row[col])
            opponent = parse_opponent(row[col])
            # Skips bye weeks
            if spread is not None and opponent is not None:
                weekly_games[week_num] = (opponent, spread)
        grid[team] = weekly_games
    return grid

def spread_to_moneyline(spread):
    # Converts a point spread to a no-vig American moneyline via
    # Hal Stern's NFL win probability model, stating that scoring margins
    # follow a normal distribution with a spread of approximately 13.5 points.

    # Formula requires the favored team to have a positive spread, so the sign
    # must be flipped
    points_favored = -spread
    # Converts point spread to win probability
    win_prob = 0.5 * (1 + math.erf((points_favored / 13.5) / math.sqrt(2)))
    win_prob = min(max(win_prob, 0.001), 0.999)
    # Converts win probability to moneyline
    if win_prob > 0.5:
        return round(-100 * win_prob / (1 - win_prob))
    else:
        return round(100 * (1 - win_prob) / win_prob)

def fill_games_without_odds(missing_odds, grid):
    # For each game DraftKings does not have a line posted for, this looks
    # looks up the spread from survivorgrid (for both teams) and calculates
    # the moneyline for both sides. Anything survivorgrid doesn't have either
    # is returned separately, so it's visible rather than silently dropped.
    rows = []
    still_missing = []
    # For every game missing odds on DraftKings, retrieves the spread for that game
    # and calculates the moneyline for each team. 
    for week, home, away in missing_odds:
        home_spread = grid.get(home, {}).get(week)
        if home_spread is None:
            still_missing.append((week, home, away))
            continue
        home_spread = home_spread[1]  # grid now stores (opponent, spread) tuples
        home_ml = spread_to_moneyline(home_spread)
        away_ml = spread_to_moneyline(-home_spread)
        rows.append({"week": week, "team": home, "opponent": away, "moneyline": home_ml, "source": "survivorgrid_backup"})
        rows.append({"week": week, "team": away, "opponent": home, "moneyline": away_ml, "source": "survivorgrid_backup"})
    return rows, still_missing

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    # This script runs with 2 arguments: an output path to write the .csv to and an API key to 
    # request odds from the-odds-api.com.
    ap = argparse.ArgumentParser(description="Fetch DraftKings NFL odds for all remaining weeks and write them into a .csv file")
    ap.add_argument("--output", default="odds.csv", help="output .csv path")
    ap.add_argument("--api-key", default="73cfcfe9cc68459198ac3ab9a7eac496", help="API key to pull from https://api.the-odds-api.com/v4")
    ap.add_argument("--current-week", default="2", help="Current NFL week")
    args = ap.parse_args()

    # Makes API request
    games = fetch_odds(args.api_key)
    if not games:
        raise SystemExit("No NFL games returned. Season may not be listed or API key may be invalid.")

    # Fetches and parses the survivorgrid backup source UP FRONT now, since it's
    # needed for two things: the actual schedule cross-check inside
    # response_to_csv below, and filling in whatever's found missing afterward.
    # One fetch, reused for both, rather than fetching it twice.
    grid = parse_grid(fetch_site(), args.current_week)

    # Converts response to .csv format
    csv_rows, missing_odds = response_to_csv(games, grid, WEEK_START_DATES)

    # For any game DraftKings did not have odds posted for, retrieve odds from survivorgrid
    if missing_odds:
        sg_rows, still_missing = fill_games_without_odds(missing_odds, grid)
        # Add games that got odds from survivorgrid to rest of games in .csv format
        if sg_rows:
            csv_rows += sg_rows
            print(f"{len(sg_rows)//2} game(s)' odds came from survivorgrid instead of DraftKings:")
            for row in sg_rows:
                if row["team"] < row["opponent"]:
                    print(f"    week {row['week']}: {row['team']} vs {row['opponent']}")
        # Anything survivorgrid also didn't have is printed too, so it's visible
        # rather than silently absent from the final .csv
        if still_missing:
            print(f"{len(still_missing)} game(s) had no odds from DraftKings OR survivorgrid:")
            for week, home, away in still_missing:
                print(f"    week {week}: {home} vs {away}")

    # Writes rows to .csv file to location provided in argument
    csv_rows.sort(key=lambda x: (x["week"], x["team"]))
    with open(args.output, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["week", "team", "opponent", "moneyline", "source"])
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"Wrote {len(csv_rows)} rows ({len(csv_rows)//2} games) to {args.output}. Weeks covered: {sorted({r["week"] for r in csv_rows})}")

if __name__ == "__main__":
    main()
