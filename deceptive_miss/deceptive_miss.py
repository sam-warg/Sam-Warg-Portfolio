"""
deceptive_miss.py
---------------------
This module is a library, not a script -- see deceptive_miss_analysis.ipynb for the
narrative walkthrough.
"""

# ----------------------------------------------------------------------
# IMPORTS
# ----------------------------------------------------------------------
from datetime import date, timedelta
import numpy as np
import pandas as pd
from pybaseball import statcast

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
# 2026 regular season began March 25 and runs through Sept 27. 
# SEASON_END defaults to "yesterday" rather than a fixed date until
# the regular season ends. Then, explicitly pass Sept 27 for SEASON_END.
SEASON_START = "2026-03-25"
SEASON_END = (date.today() - timedelta(days=1)).isoformat()

# The point where Statcast reports vx0/vy0/vz0/ax/ay/az for every pitcher
# rather than each pitcher's own release point
Y0 = 50.0

# The middle of home plate's depth (8.5"), which is where ABS judges a pitch
Y_PLATE = (17 / 12) / 2

# Half of the width of home plate
PLATE_HALF_WIDTH = (17 / 12) / 2

# Radius of the baseball
BALL_RADIUS = 1.45 / 12                        

# How many points to sample along each pitch's flight
N_SAMPLES = 100     

# The percentile that determines the cutoff for which pitches looked like a strike
# long enough to be classified as a deceptive miss
THRESHOLD_PERCENTILE = 90

# The minimum amount of zone-missing pitches a pitch type needs before it gets its
# own analysis
MIN_PITCH_TYPE_COUNT = 100   

# The columns needed from Statcast data
NEEDED_COLS = [
    "game_date", "player_name", "pitcher", "batter", "pitch_type",
    "description", "type", "zone",   
    "balls", "strikes", "stand", "p_throws",
    "plate_x", "plate_z",
    "sz_top", "sz_bot",
    "vx0", "vy0", "vz0", "ax", "ay", "az",
    "release_pos_x", "release_pos_y", "release_pos_z",
]

# The outcomes that contribute to chase rate
SWING_DESCRIPTIONS = {
    "hit_into_play", "foul", "swinging_strike", "swinging_strike_blocked",
    "foul_tip", "foul_bunt", "missed_bunt", "bunt_foul_tip",
}


# ----------------------------------------------------------------------
# DATA LOADING
# ----------------------------------------------------------------------
def load_pitches(season_start=SEASON_START, season_end=SEASON_END):
    # Load the full season as a clean, ready-to-use dataframe
    pitches = statcast(start_dt=season_start, end_dt=season_end)
    pitches = pitches[NEEDED_COLS].copy()
    pitches = pitches.dropna(subset=[
        "plate_x", "plate_z", "sz_top", "sz_bot",
        "vx0", "vy0", "vz0", "ax", "ay", "az",
    ])
    return pitches


# ----------------------------------------------------------------------
# ZONE CLASSIFICATION
# ----------------------------------------------------------------------
def classify_zone_miss(df):
    # This function classifies all pitches thrown as either a strike or ball.
    # Based on the new ABS strike zone guidelines, if any part of the ball 
    # touches any part of the strike zone, it is a strike. The strike zone is
    # a rectangle, whose demensions are represented by sz_top/sz_bot/plate-width.

    # This finds the nearest point from the center of the ball, where it 
    # actually crossed the plate, to the strike zone both vertically and 
    # horizontally. If the ball already falls within, the closest point is 
    # the same as the ball's center. If not, closest is assigned the edge of 
    # the ball. If the ball is outside the zone in both directions, it's 
    # nearest point will be to the corner. 
    closest_x = df["plate_x"].clip(lower=-PLATE_HALF_WIDTH, upper=PLATE_HALF_WIDTH)
    closest_z = df["plate_z"].clip(lower=df["sz_bot"], upper=df["sz_top"])

    # Pythagorean distance from the ball's real center, at the point of crossing,
    # to the nearest point of the strike zone. This is 0 if the ball is already 
    # inside the zone.
    dist = ((df["plate_x"] - closest_x) ** 2 + (df["plate_z"] - closest_z) ** 2) ** 0.5

    # is_strike_abs is a binary variable that signifies if a ball is in the
    # ABS strike zone or not. Since any part of the ball can touch the zone
    # to be considered a strike, not just the center, if the Pythagorean
    # distance is less than the radius of the ball, then the ball is touching
    # the zone. missed_zone is just the inverse; if a pitch is not a strike,
    # it is a ball.
    df["dist_from_zone"] = dist
    df["is_strike_abs"] = dist <= BALL_RADIUS
    df["missed_zone"] = ~df["is_strike_abs"]
    return df

# ----------------------------------------------------------------------
# THE METRIC: pct_looks_like_strike
# ----------------------------------------------------------------------
def time_to_reach_y(vy0, ay, y_start, y_target):
    # Time (s) for a pitch to travel from a start point (usually y0--50ft 
    # from the plate--to an end point using Statcast's constant-acceleration 
    # kinematic model: y(t) = y_start + vy0*t + 0.5*ay*t^2
    #
    # We want the t at which y(t) == y_target. Rearranged into the standard
    # quadratic form  0.5*ay*t^2 + vy0*t + (y_start - y_target) = 0, this is
    # just the quadratic formula, t = (-b +/- sqrt(b^2 - 4ac)) / 2a, with
    # a=0.5*ay, b=vy0, c=(y_start - y_target).

    # vy0 is the pitch's downrange velocity, ay is the pitch's downrange acceleration
    disc = vy0 ** 2 - 2 * ay * (y_start - y_target)   # this is b^2 - 4ac
    disc = np.clip(disc, 0, None)
    # We are returning the earlier of the two solutions since that is the one where
    # the ball is still heading toward the plate.
    yt = (-vy0 - np.sqrt(disc)) / ay
    return yt


def calc_proj_strike_pct(df, n_samples=N_SAMPLES):
    # For each pitch, how often did it look like a strike? 
    # This function samples points across the full pitch flight
    # At each point, it projects the ball's current velocity
    # forward in a straight line to the plate and check whether 
    # that projected point would touch the zone. It then returns 
    # the fraction of samples where it would be a strike.

    # sideways velocity at Y0 in ft/s
    vx0 = df["vx0"].to_numpy() 
    # downrange velocity at Y0 in ft/s  
    vy0 = df["vy0"].to_numpy()   
    # vertical velocity at Y0 in ft/s
    vz0 = df["vz0"].to_numpy()
    # sideways acceleration in ft/s^2
    ax = df["ax"].to_numpy()     
    # downrange deceleration in ft/s^2
    ay = df["ay"].to_numpy()     
    # vertical acceleration in ft/s^2
    az = df["az"].to_numpy()     
    # X-coordinate of the center of the ball where it crosses the plate in feet
    plate_x = df["plate_x"].to_numpy()   
    # Z-coordinate of the center of the ball where it crosses the plate in feet
    plate_z = df["plate_z"].to_numpy()   
    # Top of strike zone in feet
    sz_top = df["sz_top"].to_numpy()
    # Bottom of strike zone in feet     
    sz_bot = df["sz_bot"].to_numpy()     

    # Calculates how long it takes for the pitch to get from its starting point to the plate
    t_plate = time_to_reach_y(vy0, ay, Y0, Y_PLATE)
    # Calculates how long the sampling window should start from the release point--should be 0
    # since we are sampling the full flight path (starting at 50 ft from the plate where Statcast
    # begins tracking)
    t_start = time_to_reach_y(vy0, ay, Y0, Y0)

    # Solves for the ball's position (x- and z-coordinates) at Y0 using the position equation
    x0 = plate_x - vx0 * t_plate - 0.5 * ax * t_plate ** 2
    z0 = plate_z - vz0 * t_plate - 0.5 * az * t_plate ** 2

    # Produces individually spaced samples of actual timestamps of the ball's flight path,
    # which are the points where we will check if the pitch looks like a strike or not
    sample_pts = np.linspace(0, 1, n_samples)
    ts = t_start[:, None] + sample_pts[None, :] * (t_plate - t_start)[:, None]

    # Solves for the position of the ball at each of these 100 sample points using the position equation
    xs = x0[:, None] + vx0[:, None] * ts + 0.5 * ax[:, None] * ts ** 2
    zs = z0[:, None] + vz0[:, None] * ts + 0.5 * az[:, None] * ts ** 2
    ys = Y0 + vy0[:, None] * ts + 0.5 * ay[:, None] * ts ** 2

    # Finds the velocity of the ball at each of these 100 sample points by taking the derivative
    # of the position
    vxs = vx0[:, None] + ax[:, None] * ts
    vys = vy0[:, None] + ay[:, None] * ts
    vzs = vz0[:, None] + az[:, None] * ts

    # Solves for how long it would take for the pitch, at each sampled point, to cover 
    # the remaining distance to the plate if it stopped curving and traveled in a straight
    # line. Then, the position of the ball is projected at that distance using its current
    # position and velocity.
    dt_remaining = (Y_PLATE - ys) / vys
    x_proj = xs + vxs * dt_remaining
    z_proj = zs + vzs * dt_remaining

    # Similar to before, this finds the nearest point from the center of the ball, where 
    # it is projected to cross the plate, to the strike zone both vertically and 
    # horizontally. If the ball already falls within, the closest point is 
    # the same as the ball's center. If not, closest is assigned the edge of 
    # the ball. Then, it calculates the distance from the ball's center, at the projected
    # point of crossing, to the nearest point of the strike zone. This is 0 if the ball is 
    # already inside the zone. If the distance is less than or equal to the ball's radius,
    # it is projected to "look like a strike" at that sampled point. These steps are completed
    # for all sampled points.
    closest_x = np.clip(x_proj, -PLATE_HALF_WIDTH, PLATE_HALF_WIDTH)
    closest_z = np.clip(z_proj, sz_bot[:, None], sz_top[:, None])
    dist = np.sqrt((x_proj - closest_x) ** 2 + (z_proj - closest_z) ** 2)
    touching_sz = dist <= BALL_RADIUS   # (number_of_pitches x 100) grid of True/False

    # Return the fraction of sampled points that are projected as a strike as a percentage.
    return touching_sz.mean(axis=1)

# ----------------------------------------------------------------------
# LEADERBOARDS
# ----------------------------------------------------------------------
def add_deceptive_miss_overall(misses, percentile=THRESHOLD_PERCENTILE):
    # Determines which pitches are considered a deceptive miss and which are not

    # Calculates the threshold value where the cutoff boundary is set at
    threshold_value = misses["proj_strike_pct"].quantile(percentile / 100)
    # Any pitch that looks like a strike for a percentage of time greater than that threshold 
    # value is classified as a deceptive miss.
    misses["deceptive_miss_overall"] = misses["proj_strike_pct"] >= threshold_value
    return misses, threshold_value


def build_leaderboard_overall(misses):
    # Creates leaderboard to showcase each pitcher and their total misses (balls that do
    # not land in the ABS strike zone), their deceptive misses, how often their overall
    # misses look like a strike on average, how often their deceptive misses look like a 
    # strike on average, and the percentage of their misses that are deceptive misses.
    misses["deceptive_pct"] = misses["proj_strike_pct"].where(
            misses["deceptive_miss_overall"]
        )
    # one group of rows per pitcher
    leaderboard = misses.groupby(["pitcher", "player_name"]).agg(   
            zone_misses=("deceptive_miss_overall", "size"),      # total misses (rows)
            deceptive_misses=("deceptive_miss_overall", "sum"),  # True counts as 1, so
                                                                    # summing a boolean
                                                                    # column counts how
                                                                    # many were flagged
            avg_proj_strike_pct=("proj_strike_pct", "mean"),
            avg_proj_strike_pct_dec=("deceptive_pct", "mean")  # NaN if a pitcher has
                                                                # zero deceptive misses
        )
    
    leaderboard["deceptive_miss_rate"] = leaderboard["deceptive_misses"] / leaderboard["zone_misses"]
    leaderboard = leaderboard[["zone_misses", "deceptive_misses", "deceptive_miss_rate", 
                               "avg_proj_strike_pct", "avg_proj_strike_pct_dec"]]
    leaderboard = leaderboard.sort_values("deceptive_misses", ascending=False)
    return leaderboard

def add_deceptive_miss_by_pitch_type(misses, percentile=THRESHOLD_PERCENTILE,
                                min_count=MIN_PITCH_TYPE_COUNT):
    # Determines which pitches are considered a deceptive miss and which are not 
    # only compared to their own pitch type. Sliders, for example, have more 
    # lateral and downward movement than a fastball, so they will naturally be
    # much more deceptive. By making the threshold pitch-type specific, though, 
    # each pitch is judge according to ones with similar movement profiles, leveling
    # the playing field and capturing the most deceptive of each pitch type.


    # Only keep pitch types with enough pitches to garner a real sample size
    type_counts = misses["pitch_type"].value_counts()
    valid_types = type_counts[type_counts >= min_count].index
    by_type = misses[misses["pitch_type"].isin(valid_types)].copy()

    # Calculates the threshold value where the cutoff boundary is set at, 
    # similar to above, but grouped by each pitch type.  
    thresholds = (by_type.groupby("pitch_type")["proj_strike_pct"].quantile(percentile / 100))
    by_type["threshold_by_type"] = by_type["pitch_type"].map(thresholds)

    # Also like before, any pitch that looks like a strike for a percentage 
    # of time greater than that threshold value is classified as a deceptive miss
    # for that pitch type
    by_type["deceptive_miss_by_type"] = (
        by_type["proj_strike_pct"] >= by_type["threshold_by_type"]
    )

    # Collapses the thresholds down to just one per pitch type to make summary cleaner
    thresholds = by_type.groupby("pitch_type")["threshold_by_type"].first()
    return by_type, thresholds


def build_leaderboard_by_pitch_type(by_type):
    # Creates leaderboard to showcase each pitcher and, AGGREGATED BY THEIR PITCH TYPES,
    # their total misses (balls that do not land in the ABS strike zone), their deceptive 
    # misses, how often their overall misses look like a strike on average, and the 
    # percentage of their misses that are deceptive misses.
    by_type["deceptive_pct"] = by_type["proj_strike_pct"].where(
        by_type["deceptive_miss_by_type"]
    )

    leaderboard = by_type.groupby(["pitcher", "player_name", "pitch_type"]).agg(
                zone_misses=("deceptive_miss_by_type", "size"),
                deceptive_misses=("deceptive_miss_by_type", "sum"),
                avg_proj_strike_pct=("proj_strike_pct", "mean"),
                avg_proj_strike_pct_dec=("deceptive_pct", "mean")
            )

    leaderboard["deceptive_miss_rate"] = leaderboard["deceptive_misses"] / leaderboard["zone_misses"]
    leaderboard = leaderboard[["zone_misses", "deceptive_misses", "deceptive_miss_rate", 
                               "avg_proj_strike_pct", "avg_proj_strike_pct_dec"]]
    leaderboard = leaderboard.sort_values(["pitch_type", "deceptive_misses"], ascending=[True,False])
    return leaderboard

# ----------------------------------------------------------------------
# VALIDATION
# ----------------------------------------------------------------------
def add_swing_outcomes(df):
    # Creates a boolean variable that indicates if a batter swung at a 
    # pitch or not (used to calculate chase rate) and a boolean variable
    # that indicates if a pitch was a called strike or not. 
    df["swung"] = df["description"].isin(SWING_DESCRIPTIONS)
    df["called_strike"] = df["description"] == "called_strike"
    return df

def validate_proj_strike_pct(df, bins=10):
    # Groups pitches by projected strike percentage and calculates chase
    # rate and called strike rate by bin.
    df["bin_proj_strike_pct"] = pd.cut(df["proj_strike_pct"], bins=bins)
    return df.groupby("bin_proj_strike_pct", observed=True).agg(
        total_pitches=("swung", "size"),
        chase_rate=("swung", "mean"),
        called_strike_rate=("called_strike", "mean"),
    )

def validate_proj_strike_pct_dist(df, n_bins=5):
    # Bins pitches by the distance they finish from the strike zone
    # (only for ones with a projected strike percentage that is not 0 to prevent
    # skewed data). Then, grouping by those distance bins, it calculates the 
    # chase rate for pitches above and below the median projected strike percentage 
    # for that group. 

    # Retrieves distances of pitches from strike zone but only for pitches whose projected strike
    # percentage is greater than 0
    nonzero = df[df["proj_strike_pct"] > 0]
    # Cuts into 5 equal-sized bins
    nonzero["bin_dist_from_zone"] = pd.qcut(
        nonzero["dist_from_zone"], q=n_bins, duplicates="drop"
    )
    # Calculates the median projected strike percentage for each bin
    median_by_bin = (
        nonzero.groupby("bin_dist_from_zone")["proj_strike_pct"]
        .transform("median")
    )
    # Classifies if a pitch's projected strike percentage is above or below the median
    # for that group
    nonzero["proj_strike_pct_group"] = np.where(
        nonzero["proj_strike_pct"] >= median_by_bin,
        "above_proj_strike_pct_med", "below_proj_strike_pct_med",
    )
    # Creates the pivot table
    return (
        nonzero.groupby(["bin_dist_from_zone", "proj_strike_pct_group"])
        .agg(total_pitches=("swung", "size"), chase_rate=("swung", "mean"))
        .reset_index()
        .pivot(index="bin_dist_from_zone", columns="proj_strike_pct_group", values="chase_rate")
    )

def validate_deceptive_miss(df):
    # Groups pitches by whether they are a deceptive miss or not and calculates 
    # chase rate and called strike rate by bin.
    return df.groupby("deceptive_miss_overall").agg(
        total_pitches=("swung", "size"),
        chase_rate=("swung", "mean"),
        called_strike_rate=("called_strike", "mean"),
    )

def validate_deceptive_miss_dist(df, n_bins=5, percentile=0.95):
    # Bins pitches by the distance they finish from the strike zone (only for ones 
    # that are a deceptive miss to prevent skewed data). Then, grouping by those 
    # distance bins, it calculates the chase rate for pitches that are and are not
    # deceptive misses for that group. 
    
    # Retrieves distances of pitches from strike zone but only for pitches that are a deceptive miss. Then, the 95th
    # quantile is calcualated to remove outliers. This value is used as the max distance from zone our analysis will
    # inspect
    max_deceptive_dist = df.loc[df["deceptive_miss_overall"], "dist_from_zone"].quantile(percentile)
    within_dist_range = df[df["dist_from_zone"] <= max_deceptive_dist]

    # Bins all pitches that fall within our distance from strike zone range
    within_dist_range["distance_bin"] = pd.qcut(within_dist_range["dist_from_zone"], q=n_bins, duplicates="drop")

    # Grouping by distance from strike zone bins, averages chase rates to compare deceptive misses to
    # non-deceptive misses
    grouped = (
        within_dist_range.groupby(["distance_bin", "deceptive_miss_overall"], observed=True)
        .agg(n=("swung", "size"), chase_rate=("swung", "mean"))
        .reset_index()
    )
    # Creates the pivot table
    validation_table = grouped.pivot(index="distance_bin", columns="deceptive_miss_overall", values="chase_rate")
    validation_table.rename(columns={False: "Non-Deceptive Miss", True: "Deceptive Miss"})
    return validation_table, max_deceptive_dist