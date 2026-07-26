# flightmap

GPS flight log to a single self-contained HTML page. No map tiles, no network,
no API key.

```
$ python3 flightmap.py --demo -o flight.html
400 fixes, 2.02km over 1.7min -> flight.html
```

The track is drawn in a local equirectangular projection with equal aspect, so
it is not stretched, and coloured by ground speed. The altitude profile sits
underneath sharing the same horizontal axis — distance along track, not time —
so a climb and the turn that caused it line up visually.

Hovering either chart highlights the same fix on both, with a readout of time,
distance, altitude, speed, and climb rate. That link between the two views is
the point of the page.

## Stats

Duration, distance, max speed, max altitude, max distance from home, best climb
rate. Speed and climb are computed from the surrounding fixes rather than the
preceding one, which halves the noise on a jittery log.

## Input

CSV with latitude and longitude; altitude and time are optional. Column names
are matched loosely (`lat`/`latitude`, `lon`/`lng`/`longitude`, `alt`/`elev`/
`height`, `time`/`ts`/`timestamp`). Absolute timestamps, `HH:MM:SS`, and plain
seconds all parse. Unparseable rows are skipped rather than aborting the run —
a log with a few corrupt lines is still worth looking at.

If there is no time column, fixes are treated as one per second, so speeds
become relative rather than absolute.

Stdlib only. Tests: `python3 -m pytest test_flightmap.py` (24 tests)

## Not handled

No basemap, so the track floats without geographic context. Adding tiles would
mean a network dependency and an API key, which would cost more than it gives
for a quick post-flight look.
