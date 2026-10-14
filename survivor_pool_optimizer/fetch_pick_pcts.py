"""
Fetch real NFL survivor pool pick distribution projections
via survivorgrid.com and write them into a .csv file.
"""

# ----------------------------------------------------------------------
# IMPORTS
# ----------------------------------------------------------------------
import argparse
import csv
import sys
from io import StringIO
import requests
import pandas as pd

# ----------------------------------------------------------------------
# ARGUMENTS
# ----------------------------------------------------------------------
# If running from VSCode interface instead of terminal, arguments can be
# adjusted here
if len(sys.argv) == 1: 
    sys.argv += ["--week", "2", "--year", "2026", "--output", "projected_pick_distribution.csv"]

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
# The site used to pull pick distribution projections from
URL = "https://www.survivorgrid.com/picks"

# The source that we are pulling the survivorgrid projections from.
# Other options included Yahoo, ESPN, and USA Football Pools. 
# Projected is a blend of those 3, so that is what is used here.
PROJ_SOURCE = "Projected"


# ----------------------------------------------------------------------
# NORMALIZATION
# ----------------------------------------------------------------------
def normalize_team(team):
    # Ensures team object only contains the team abbreviation.

    # Removes any leading/trailing whitespace and capitalizes team
    team = str(team).strip().upper()
    # Removes any trailing "(W)" or "(L)" that appears next to a team if 
    # they have past results for that week
    team = team.split(" ")[0] 
    return team


def normalize_whitespace(text):
    # survivorgrid produces text with irregular or non-breaking spaces.
    # This function splits text down to each individual string and rejoins
    # them together with only one space in between each.
    return " ".join(str(text).split())

# ----------------------------------------------------------------------
# RETRIEVE SURVIVORGRID WEBSITE
# ----------------------------------------------------------------------
def fetch_site(year, week):
    # Retrieves survivorgrid website which pick distribution will be pulled from

    # Makes HTML request to web scrape site
    url = f"{URL}/{year}/{week}"
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; survivor-pool-optimizer)"}, timeout=15)
    resp.raise_for_status()
    return resp.text

# ----------------------------------------------------------------------
# FIND COLUMN FROM TABLE
# ----------------------------------------------------------------------
def find_column(columns, name):
    # Walks through each column in table, normalizes their names to
    # prevent whitespace errors, and returns the one matching the name
    # passed in the function call
    for col in columns:
        if normalize_whitespace(col).startswith(name):
            return col
    return None

# ----------------------------------------------------------------------
# PARSE PROJECTED PICK DISTRIUBTION
# ----------------------------------------------------------------------
def parse_proj_pick_dist(html):
    # Finds correct table from HTML response, pulls each team and their projected
    # pick distribution, and formats each pair to be converted to a .csv.

    # Reads tables contained in the HTML page. Without specifying lxml as
    # the flavor, an error will be thrown.
    tables = pd.read_html(StringIO(html), flavor="lxml")

    # Finds the table that contains the data needed (teams and projected pick distributions)
    target, team_col, proj_col = None, None, None
    for df in tables:
        # Retrieves team column
        t_col = find_column(df.columns, "Team")
        # Retrieves pick distribution projection column
        p_col = find_column(df.columns, PROJ_SOURCE)
        # When the correct table is found that contains those columns,
        # it is set to our target table.
        if t_col is not None and p_col is not None:
            target, team_col, proj_col = df, t_col, p_col
            break

    # Using the target table, this pulls the team and pick distribution for each
    # row, converts the percentage to a decimal so it can be used in the calculations
    # in the optimizer notebook, and then adds each team and pick distribution to our
    # our list to be converted to .csv later on.
    csv_rows = []
    for _, row in target.iterrows():
        team = normalize_team(row[team_col])
        proj = normalize_whitespace(row[proj_col]).rstrip("%")
        csv_rows.append({"team": team, "proj_pick_dist": float(proj) / 100.0})
    return csv_rows

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    # This script runs with 3 arguments: the year and week to retrieve the projected pick distribution for
    # and an output path to write the .csv to 
    ap = argparse.ArgumentParser(description="Fetch survivorgrid's projected pick distribution and writes it to a .csv")
    ap.add_argument("--year", type=int, required=True, help="Year to fetch distribution for")
    ap.add_argument("--week", type=int, required=True, help="NFL week to fetch distribution for")
    ap.add_argument("--output", default="projected_pick_distribution.csv", help="output .csv path")
    args = ap.parse_args()

    # Returns survivorgrid wesbite for given year and week
    html = fetch_site(args.year, args.week)

    # Web scrape HTML response to get each team and its projected pick distribution
    csv_rows = parse_proj_pick_dist(html)
    if not csv_rows:
        raise SystemExit("No rows parsed. survivorgrid may not have data for this week yet "
                          "or the site's format changed.")

    # Adds a week column for each row
    for row in csv_rows:
        row["week"] = args.week
    # Sorts result in order by team
    csv_rows.sort(key=lambda x: x["team"])

    # Writes rows to .csv file to location provided in argument
    with open(args.output, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["week", "team", "proj_pick_dist"])
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"Wrote {len(csv_rows)} team(s) for week {args.week} to {args.output} ")

if __name__ == "__main__":
    main()
