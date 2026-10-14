# Deceptive Miss

**Which pitchers throw the most balls that look like strikes?**

A pitch-quality metric built on 2026 MLB Statcast data. For every pitch that 
misses the zone, the **projected strike percentage** measures how much of its flight 
that it looked like it would cross the plate as a strike. A **deceptive miss**, derived
from that, is one whose projected strike percentage exceeds a data-driven threshold,
meaning the pitch looked like a strike for a large majority of the flight before 
finishing outside of the strike zone.

## The Idea

For every pitch that ends up a ball, sample points along its full flight and ask, at
each instant: if this pitch stopped breaking or dropping right now and continued in 
a straight line, would it land in the ABS strike zone? Then, identify the pitches that
answer "yes" to this question the most often.

A fastball that starts outside the zone, stays there, and finishes outside the zone is
a lot less likely to generate a chase from the batter than a breaking ball that starts
out looking like it will be a strike down the center of the plate but then breaks far
outside. It is important, and a skill, for pitchers to be able to get swings even when
they do not throw a strike, and that is what these statistics aim to quantify.

## How It Works

- The code takes all pitches during the 2026 MLB season and calculates which ones miss 
the new, defined ABS strike zone.

- It then calculates how long of the pitch's flight it is projected to be a strike using
physics, as the Statcast data provides, at 50 ft from home plate, the velocity and 
acceleration of the ball in all three directions along with its position. From there, it
uses the position equation to solve for the ball's position at 100 different sample points
until it crosses the plate. At each of those points, if the ball were to head in a straight
line to home plate, that point is considered to be of a projected strike position. The 
percentage of those in the 100 point sample determines the projected strike percentage. 

- From there, a threshold is set to a percentile of the season's distribution of pitches
(currently set at the 90th). All pitches above that threshold for how long they are 
projected to be a strike are classified as a deceptive miss.

- Finally, some verification steps are completed to prove the significance of these metrics. 
Both the projected strike percentage and deceptive miss statistics are analyzed using chase
rates to prove that:
    1. As projected strike percentage increases, so does chase rate
    2. Deceptive misses have a higher chase rate than non-deceptive misses
For both, a simple test shows the relationship between the metrics and chase rate, but a second
test, controlling for distance a pitch is from the strike zone, is also shown to debunk the 
argument that there is only a higher chase rate because more deceptive pitches are likely to 
finish closer to the strike zone.

## Project Structure

- `deceptive_miss.py`:  
All functions necessary to load the data, calculate the metrics, build the leaderboards, and 
validate the predictive power.

- `deceptive_miss_analysis.ipynb`:
Imports the function module and runs the pipeline end-to-end, displaying relevant outputs and
explaining findings at each step. Also, all leaderboards and plots are displayed here.

- `requirements.txt`


## Running It

Built and tested in VS Code with the Jupyter extension, but nothing is VS Code-specific.

1. Install dependencies:
pip install -r `requirements.txt`

2. If in VS Code (or another code editor): Open `deceptive_miss_analysis.ipynb` and 
run all cells top to bottom.

If running from a terminal: `jupyter notebook deceptive_miss_analysis.ipynb`

3. Ensure `deceptive_miss.py` exists in the same folder as `deceptive_miss_analysis.ipynb`,
or else the functions cannot be imported.

## Known Limitations/Future Enhancements

- No model of batter pitch-type recognition:
This is a geometric representation of deception, not what a batter actually perceives.
If a batter identifies a curveball out of the hand and adjusts accordingly, they may
not be fooled on a pitch that this statistic would label as deceptive. A pitcher that
tips their pitches would still score well on this metric.

- The percentile threshold is a choice:
This threshold was determined by analyzing the entire pitch distribution. The 90th
percentile was chosen so that the majority of misses are not deceptive, but also so
that there is a large enough sample size to draw conclusions from the leaderboard.
In the future, this could be tuned to produce even more meaningful results.