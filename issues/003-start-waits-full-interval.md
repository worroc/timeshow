# 003: Start does not change the wallpaper; first change comes one interval later

## Status: Resolved

Implemented for GUI Start and worker/tray resume. Starting enables the schedule,
refreshes an empty photo list, and switches once immediately. Ordinary failures
keep scheduling enabled; exhausted collections pause. Automated checks cover
immediate switching, pause, errors, and exhaustion. Released in
[v0.1.1](https://github.com/worroc/timeshow/releases/tag/v0.1.1).
Native scheduling validation remains tracked in the
[Ubuntu validation issue](https://github.com/worroc/timeshow/issues/3).

## Observed

On first use (Ubuntu, GNOME, Wayland): pressed **Start**. Nothing happened.
The wallpaper changed only after pressing **Next**.

Evidence from the test machine (interval set to 1 minute,
`journalctl --user -u timeshow.timer -u timeshow.service`):

```
15:45:52 Started timeshow.timer - Timeshow user wallpaper timer.   <- Start pressed
15:46:53 Starting timeshow.service - Switch Timeshow wallpaper once...   <- first switch, +1 interval
15:46:54 Finished timeshow.service ...
15:47:54 Starting timeshow.service ...
```

The worker runs succeed (no `Failed`, no error output). The only problem is the
delay before the first switch. With the default 60-minute interval, the user
waits an hour and thinks Start is broken.

## Cause

`MainWindow.toggle()` (`gui/window.py`) only calls
`self.scheduler.enable(interval)` and sets `running = True`. It never switches
the wallpaper itself.

`Scheduler.enable()` (`scheduling.py`) writes the timer with
`OnActiveSec={interval}s` and `OnUnitActiveSec={interval}s`, then restarts it.
So the first worker `tick` runs one full interval after Start.
The Windows path is the same: `schtasks /SC MINUTE /MO <n>` first fires after
`n` minutes.

The tray "resume" action (`worker.py` `perform(... "resume")`) has the same
behaviour.

## Proposed fix

When rotation goes from paused to running, switch once right away, then let the
timer continue:

1. In `toggle()`, in the "start" branch, after `scheduler.enable(...)` and
   saving `running = True`, run the same switch as **Next**
   (`self._switch("next")`, then `self._display`). That updates `last_switch`,
   so the timer's next `tick` waits a full interval from now.
2. In `worker.py`, action `resume`: after `scheduler.enable(...)` call
   `player.next()` as well (refresh first if `state["images"]` is empty, like
   `tick` does).
3. If the immediate switch fails (network, empty album), keep `running = True`
   and show the error. The timer will retry on the next tick. Do not roll back
   the schedule.
4. If `CollectionExhausted` is raised, use the existing handling (pause and tell
   the user).

Alternative (not preferred): `OnActiveSec=1s` in the timer. It needs no GUI
change, but it does not cover Windows and hides failures from the user.

## Tests

- `toggle()` from paused: scheduler enabled **and** one switch performed;
  `last_switch` updated.
- `toggle()` from running: scheduler disabled, no switch.
- `worker --action resume`: enables the scheduler and switches once.
- Immediate switch raises `PhotosError`: `running` stays `True`, error shown.

## Check

Set the interval to 60 minutes. Press **Start**. The wallpaper changes within a
few seconds. The next change comes 60 minutes later.
