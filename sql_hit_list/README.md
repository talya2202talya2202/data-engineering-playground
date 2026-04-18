# SQL Hit List – Assumptions

The query in `solution.sql` is built on the following assumptions:

### Source data
- `plays IS NULL` — treated as `0`.
- `(artist, song_name)` uniquely identifies a song (two artists with the same song title are two different songs).

### Timeframe
- "During 2020" is applied to the whole analysis: `avg_daily_play_count`, `longest_consecutive_days`, and `is_one_hit_wonder` are all computed from 2020 data only, not lifetime history.
- If the extra metrics should instead reflect all-time activity, drop the date filter from `daily_song_totals` and apply the 2020 filter only on the final top-10 selection.

### Tie-breaking for the top 10
Ordering is:
1. `heavily_rotated_days` DESC
2. `avg_daily_play_count` DESC
3. `artist` ASC, `song_name` ASC  *(deterministic alphabetical fallback)*

If more than 10 songs are still tied at the boundary, the alphabetical fallback picks the winners arbitrarily. If a business rule should instead return **all ties** (11+ rows), replace `LIMIT 10` with a `RANK()`-based filter (`WHERE rnk <= 10`).
