-- Aggregate plays per song per day in 2020; NULL plays count as 0.
WITH daily_song_totals AS (
    SELECT
        day,
        artist,
        song_name,
        SUM(COALESCE(plays, 0)) AS daily_play_count
    FROM daily_song_plays
    WHERE day >= DATE '2020-01-01'
      AND day <  DATE '2021-01-01'
    GROUP BY 1, 2, 3
),

-- Average daily plays and number of heavily-rotated days (>= 15 plays) per song.
song_metrics AS (
    SELECT
        artist,
        song_name,
        AVG(daily_play_count * 1.0)                             AS avg_daily_play_count,
        SUM(CASE WHEN daily_play_count >= 15 THEN 1 ELSE 0 END) AS heavily_rotated_days
    FROM daily_song_totals
    GROUP BY 1, 2
),

-- Keep only the heavily-rotated days.
heavy_days AS (
    SELECT artist, song_name, day
    FROM daily_song_totals
    WHERE daily_play_count >= 15
),

-- Gaps-and-islands: day - row_number() is constant within a consecutive streak.
heavy_days_with_groups AS (
    SELECT
        artist,
        song_name,
        day,
        day - (ROW_NUMBER() OVER (
            PARTITION BY artist, song_name
            ORDER BY day
        ) * INTERVAL 1 DAY) AS grp
    FROM heavy_days
),

-- Length of each consecutive heavy-rotation streak.
heavy_day_streaks AS (
    SELECT
        artist,
        song_name,
        grp,
        COUNT(*) AS streak_len
    FROM heavy_days_with_groups
    GROUP BY 1, 2, 3
),

-- Longest consecutive heavy-rotation streak per song.
longest_streak_per_song AS (
    SELECT
        artist,
        song_name,
        MAX(streak_len) AS longest_consecutive_days
    FROM heavy_day_streaks
    GROUP BY 1, 2
),

-- Number of heavily-rotated songs per artist (for one-hit-wonder flag).
artist_hit_counts AS (
    SELECT
        artist,
        COUNT(*) AS heavy_hit_song_count
    FROM song_metrics
    WHERE heavily_rotated_days > 0
    GROUP BY 1
)

SELECT
    sm.artist,
    sm.song_name,
    sm.heavily_rotated_days,
    ROUND(sm.avg_daily_play_count, 2)           AS avg_daily_play_count,
    COALESCE(ls.longest_consecutive_days, 0)    AS longest_consecutive_days,
    CASE WHEN ahc.heavy_hit_song_count = 1
         THEN 'Yes' ELSE 'No' END               AS is_one_hit_wonder
FROM song_metrics sm
LEFT JOIN longest_streak_per_song ls
       ON sm.artist = ls.artist
      AND sm.song_name = ls.song_name
LEFT JOIN artist_hit_counts ahc
       ON sm.artist = ahc.artist
WHERE sm.heavily_rotated_days > 0
ORDER BY
    sm.heavily_rotated_days DESC,
    sm.avg_daily_play_count DESC,
    sm.artist,
    sm.song_name
LIMIT 10;
