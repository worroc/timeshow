# 004: Date filters on the Settings tab are not clear

## Fix status

Implemented in a separate Filters tab, as requested by the user. From/To calendar
pickers have Clear buttons and No limit states. Help explains inclusive bounds
and undated photos. Saved match counts are shown. Filtering and displayed dates
use local time. Reversed ranges are rejected before saving. Interval suffix is
min. Automated checks cover saving, clearing, bounds, local dates, counts, and
half-screen layouts. Ready for Ubuntu retest.

## Observed

Settings tab (screenshot from Ubuntu, default window width):

```
Change every            [ 1 minutes      ]
Framing                 [ Fill screen (crop) v ]
Taken on/after (UTC)    [ YYYY-MM-DD, opt… ]
Taken on/before (UTC)   [ YYYY-MM-DD, opt… ]
[            Save settings             ]
```

A user cannot tell what the two "Taken" rows do.

## Problems

1. **No context.** Nothing says these rows are a photo filter. "Taken on/after"
   reads like a broken sentence. There is no group title.
2. **Placeholder is cut off.** "YYYY-MM-DD, opt…" — the word "optional" is
   hidden at normal width.
3. **UTC is confusing.** Users think in their local date. `Player.eligible()`
   (`player.py`) turns `capture_time_ms` into a UTC date. A photo taken late
   evening in Israel can count as the next day.
4. **Hidden rule: photos with no capture date disappear.** In `eligible()`, if
   any date is set, images with `capture_time_ms is None` are skipped. The UI
   does not say so. The user may lose most of an album and not know why.
5. **Inclusive or not?** The code includes both end days
   (`day < after` / `day > before` are rejected). The UI does not say so.
6. **Free text, late validation.** Plain `QLineEdit`. A bad date is reported
   only after **Save settings** (`Player.configure`).
7. **No result feedback.** After saving, the user does not see how many photos
   match the filter.
8. Minor, same form: the spin box shows "1 minutes" (suffix is always plural).

## Proposed change (`gui/window.py`, `_settings_tab()`)

1. Put the two dates in a `QGroupBox("Only photos taken between")` with rows
   **From** and **To**. Add a short help line under it:
   "Both days included. Leave empty for no limit. Photos without a date are
   skipped while a limit is set."
2. Use `QDateEdit` with `setCalendarPopup(True)` and a "no limit" state
   (e.g. a checkbox per row, or `setSpecialValueText("No limit")` with the
   minimum date as the empty value). This removes free-text errors and the
   cut-off placeholder. Keep the stored format `YYYY-MM-DD` / `""`, so
   `settings.json` and `Player.configure()` do not change.
3. Compare in **local** time: in `eligible()` use
   `datetime.fromtimestamp(ts / 1000).date()` (local zone) instead of UTC.
   Drop "(UTC)" from the labels. Also use local time for the date shown in
   image info (`window.py`, the `strftime("%Y-%m-%d")` near line 437), so both
   agree. Note this in the README as a behaviour change.
4. Reject **From** later than **To** at save time, with a clear message.
5. After saving, show the match count, e.g. "312 of 1,040 photos match
   (85 have no date)". `len(player.eligible())` already gives the first number.
6. Spin box: suffix " min", or switch between " minute" / " minutes" on
   `valueChanged`.
7. Update `README.md` ("Set the interval, framing, and optional capture-date
   range") and `src/timeshow/gui/README.md`.

## Tests

- `eligible()`: both bounds inclusive; undated photos skipped only while a
  bound is set; local-date boundary (a timestamp near midnight UTC falls on the
  local day).
- Settings: From > To is rejected; empty = no limit, saved as `""`.
- After save, the match-count label shows the expected numbers.

## Check

Open Settings at the default window size. The filter reads as one clear group,
nothing is cut off, a date can be picked from a calendar, and after **Save
settings** the number of matching photos is shown.
