# SQL Hit List – Assumptions

The query in `solution.sql` is built on the following assumptions:

### Source data
- `plays IS NULL` means the song was scheduled but not actually played — treated as `0`.
- `(artist, song_name)` uniquely identifies a song (two artists with the same song title are two different songs).

### Timeframe
- "During 2020" is applied to the whole analysis: `avg_daily_play_count`, `longest_consecutive_days`, and `is_one_hit_wonder` are all computed from 2020 data only, not lifetime history.
- If the extra metrics should instead reflect all-time activity, drop the date filter from `daily_song_totals` and apply the 2020 filter only on the final top-10 selection.

### Definitions
- **Daily play count** = sum of `plays` across all stations for that song on that day.
- **Heavily rotated day** = daily play count `>= 15` (threshold is inclusive).
- **Longest consecutive streak** = longest run of calendar-consecutive days each with `>= 15` plays. A day with `< 15` plays (including 0 / NULL) breaks the streak.
- **One-hit wonder** = the artist has exactly **one** song with at least one heavily-rotated day in 2020.

### Tie-breaking for the top 10
Ordering is:
1. `heavily_rotated_days` DESC
2. `avg_daily_play_count` DESC
3. `artist` ASC, `song_name` ASC  *(deterministic alphabetical fallback)*

If more than 10 songs are still tied at the boundary, the alphabetical fallback picks the winners arbitrarily. If a business rule should instead return **all ties** (11+ rows), replace `LIMIT 10` with a `RANK()`-based filter (`WHERE rnk <= 10`).
