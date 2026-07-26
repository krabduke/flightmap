import math
import re

import pytest

from flightmap import Fix, Track, haversine, load_csv, ramp_colour, render_html, synthetic


def straight(n=10, step_deg=0.001, alt=50.0, dt=1.0):
    return Track([Fix(i * dt, 42.0 + i * step_deg, 11.0, alt) for i in range(n)])


def test_haversine_zero():
    f = Fix(0, 42.0, 11.0, 0)
    assert haversine(f, f) == 0.0


def test_haversine_known_distance():
    d = haversine(Fix(0, 42.0, 11.0, 0), Fix(0, 43.0, 11.0, 0))
    assert 110_000 < d < 112_000


def test_cumulative_distance_is_monotonic():
    cum = straight(20).cumulative
    assert cum[0] == 0.0
    assert all(b >= a for a, b in zip(cum, cum[1:]))


def test_total_distance_matches_segments():
    t = straight(5)
    manual = sum(haversine(a, b) for a, b in zip(t.fixes, t.fixes[1:]))
    assert t.distance_m == pytest.approx(manual)


def test_duration():
    assert straight(11, dt=2.0).duration_s == 20.0


def test_speed_of_stationary_track_is_zero():
    t = Track([Fix(i, 42.0, 11.0, 50.0) for i in range(10)])
    assert max(t.speeds()) == 0.0


def test_speed_is_positive_when_moving():
    assert min(straight(10).speeds()) > 0


def test_speed_matches_expected_magnitude():
    # 0.001 deg latitude per second is about 111 m/s.
    speeds = straight(10, step_deg=0.001, dt=1.0).speeds()
    assert 105 < max(speeds) < 118


def test_climb_rate_zero_on_level_flight():
    assert all(abs(c) < 1e-9 for c in straight(10).climb_rates())


def test_climb_rate_positive_when_ascending():
    t = Track([Fix(i, 42.0, 11.0, 50.0 + i * 2) for i in range(10)])
    assert min(t.climb_rates()) > 1.5


def test_single_fix_track_has_no_speed():
    t = Track([Fix(0, 42.0, 11.0, 50.0)])
    assert t.speeds() == [0.0]
    assert t.duration_s == 0.0


def test_max_distance_from_home():
    t = straight(11, step_deg=0.001)
    assert t.max_distance_from_home() == pytest.approx(haversine(t.fixes[0], t.fixes[-1]))


def test_bounds_cover_all_fixes():
    t = synthetic(100)
    lo_lat, hi_lat, lo_lon, hi_lon = t.bounds()
    assert all(lo_lat <= f.lat <= hi_lat and lo_lon <= f.lon <= hi_lon for f in t.fixes)


def test_ramp_returns_a_colour_at_every_point():
    for v in (0, 5, 10, 15, 20):
        assert ramp_colour(v, 0, 20).startswith("#")


def test_ramp_handles_degenerate_range():
    assert ramp_colour(5, 5, 5).startswith("#")


def test_ramp_endpoints_differ():
    assert ramp_colour(0, 0, 20) != ramp_colour(20, 0, 20)


# ------------------------------------------------------------------- output

def test_html_is_selfcontained():
    out = render_html(synthetic(80))
    assert out.startswith("<!DOCTYPE html>")
    assert not re.search(r'(src|href)\s*=\s*["\']https?://', out)


def test_html_has_both_charts():
    assert render_html(synthetic(80)).count("<svg") == 2


def test_html_draws_one_segment_per_gap():
    # Track segments are the only lines with a round cap; grid lines are not.
    track = synthetic(40)
    assert render_html(track).count('stroke-linecap="round"') == track.n - 1


def test_title_is_escaped():
    out = render_html(synthetic(20), "<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


# -------------------------------------------------------------------- input

def test_csv_needs_coordinates(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("time,altitude\n0,50\n1,51\n")
    with pytest.raises(SystemExit, match="latitude"):
        load_csv(bad)


def test_csv_too_short(tmp_path):
    short = tmp_path / "short.csv"
    short.write_text("time,lat,lon,alt\n0,42.0,11.0,50\n")
    with pytest.raises(SystemExit, match="fewer than two"):
        load_csv(short)


def test_csv_roundtrip(tmp_path):
    good = tmp_path / "log.csv"
    rows = ["time,latitude,longitude,altitude"]
    for i in range(30):
        rows.append(f"{i},{42.0 + i * 0.0001},{11.0 + i * 0.0001},{50 + i}")
    good.write_text("\n".join(rows))
    track = load_csv(good)
    assert track.n == 30
    assert track.duration_s == 29.0
    assert track.distance_m > 0


def test_csv_tolerates_bad_rows(tmp_path):
    messy = tmp_path / "messy.csv"
    messy.write_text(
        "time,lat,lon,alt\n0,42.0,11.0,50\nbroken,row,here,x\n2,42.001,11.001,52\n"
    )
    assert load_csv(messy).n == 2
