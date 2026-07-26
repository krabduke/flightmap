#!/usr/bin/env python3
"""Turn a GPS flight log into a single self-contained HTML page.

No map tiles, no network, no API key. The track is drawn in a local projection
with speed encoded along it, and the altitude profile sits underneath sharing
the same axis, so a climb and the turn that caused it line up visually.

Input is CSV with time, lat, lon, and altitude. Column names are matched loosely
because every logger names them differently.
"""
from __future__ import annotations

import argparse
import csv
import html
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

EARTH_RADIUS_M = 6_371_000.0

# Drafting-film palette: a survey drawing, not a dashboard.
FILM = "#E9ECE7"
GRID = "#D3D9CF"
INK = "#2A312B"
MUTED = "#7C857A"
SPEED_RAMP = ["#46708C", "#5F8A88", "#8FA070", "#C08A3E", "#A8443A"]


@dataclass(frozen=True)
class Fix:
    ts: float          # seconds since log start
    lat: float
    lon: float
    alt_m: float


@dataclass
class Track:
    fixes: list[Fix]
    _distances: list[float] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._distances = [0.0]
        for a, b in zip(self.fixes, self.fixes[1:]):
            self._distances.append(self._distances[-1] + haversine(a, b))

    @property
    def n(self) -> int:
        return len(self.fixes)

    @property
    def duration_s(self) -> float:
        return self.fixes[-1].ts - self.fixes[0].ts if self.n > 1 else 0.0

    @property
    def distance_m(self) -> float:
        return self._distances[-1] if self._distances else 0.0

    @property
    def cumulative(self) -> list[float]:
        return self._distances

    def speeds(self) -> list[float]:
        """Ground speed in m/s at each fix, from the surrounding segments."""
        if self.n < 2:
            return [0.0] * self.n
        out = []
        for i, fix in enumerate(self.fixes):
            j = max(0, i - 1)
            k = min(self.n - 1, i + 1)
            dt = self.fixes[k].ts - self.fixes[j].ts
            dd = self._distances[k] - self._distances[j]
            out.append(dd / dt if dt > 0 else 0.0)
        return out

    def climb_rates(self) -> list[float]:
        """Vertical speed in m/s at each fix."""
        if self.n < 2:
            return [0.0] * self.n
        out = []
        for i in range(self.n):
            j = max(0, i - 1)
            k = min(self.n - 1, i + 1)
            dt = self.fixes[k].ts - self.fixes[j].ts
            out.append((self.fixes[k].alt_m - self.fixes[j].alt_m) / dt if dt > 0 else 0.0)
        return out

    def home(self) -> Fix:
        return self.fixes[0]

    def max_distance_from_home(self) -> float:
        h = self.home()
        return max(haversine(h, f) for f in self.fixes)

    def bounds(self) -> tuple[float, float, float, float]:
        lats = [f.lat for f in self.fixes]
        lons = [f.lon for f in self.fixes]
        return min(lats), max(lats), min(lons), max(lons)


def haversine(a: Fix, b: Fix) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp = p2 - p1
    dl = math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def ramp_colour(value: float, lo: float, hi: float) -> str:
    if hi <= lo:
        return SPEED_RAMP[0]
    t = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    idx = min(int(t * (len(SPEED_RAMP) - 1)), len(SPEED_RAMP) - 2)
    return SPEED_RAMP[idx if t * (len(SPEED_RAMP) - 1) - idx < 0.5 else idx + 1]


def load_csv(path: Path) -> Track:
    fixes: list[Fix] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise SystemExit(f"{path}: no header row")
        cols = {(f or "").strip().lower(): (f or "") for f in reader.fieldnames}

        def find(*names: str) -> str | None:
            for want in names:
                for key, original in cols.items():
                    if want in key:
                        return original
            return None

        lat_c, lon_c = find("lat"), find("lon", "lng")
        alt_c = find("alt", "elev", "height")
        time_c = find("time", "ts", "timestamp", "seconds")
        if not lat_c or not lon_c:
            raise SystemExit(f"{path}: need latitude and longitude columns")

        t0 = None
        for i, row in enumerate(reader):
            try:
                lat, lon = float(row[lat_c]), float(row[lon_c])
                alt = float(row[alt_c]) if alt_c and row.get(alt_c) else 0.0
                ts = _parse_time(row[time_c]) if time_c and row.get(time_c) else float(i)
            except (ValueError, TypeError, KeyError):
                continue
            if t0 is None:
                t0 = ts
            fixes.append(Fix(ts - t0, lat, lon, alt))

    if len(fixes) < 2:
        raise SystemExit(f"{path}: fewer than two usable fixes")
    return Track(fixes)


def _parse_time(raw: str) -> float:
    raw = raw.strip()
    try:
        return float(raw)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).timestamp()
        except ValueError:
            continue
    raise ValueError(f"unrecognised time: {raw!r}")


def synthetic(n: int = 400, seed: int = 3) -> Track:
    """A plausible figure-eight with altitude variation."""
    import random
    rng = random.Random(seed)
    fixes = []
    lat0, lon0 = 42.5800, 11.5300
    for i in range(n):
        t = i / 4.0
        u = i / n * 2 * math.pi * 2
        lat = lat0 + 0.0016 * math.sin(u) + rng.gauss(0, 2e-6)
        lon = lon0 + 0.0022 * math.sin(u / 2) * math.cos(u / 2) * 2 + rng.gauss(0, 2e-6)
        alt = 45 + 28 * math.sin(u / 1.6) + rng.gauss(0, 0.6)
        fixes.append(Fix(t, lat, lon, max(0.0, alt)))
    return Track(fixes)


def render_html(track: Track, title: str = "flight") -> str:
    W, H_MAP, H_PROFILE, PAD = 860, 440, 180, 44
    speeds = track.speeds()
    climbs = track.climb_rates()
    cum = track.cumulative
    lo_s, hi_s = min(speeds), max(speeds) or 1.0
    min_lat, max_lat, min_lon, max_lon = track.bounds()

    # Equal-aspect local projection so the track is not stretched.
    mid_lat = (min_lat + max_lat) / 2
    x_scale = math.cos(math.radians(mid_lat))
    span_x = max((max_lon - min_lon) * x_scale, 1e-9)
    span_y = max(max_lat - min_lat, 1e-9)
    scale = min((W - PAD * 2) / span_x, (H_MAP - PAD * 2) / span_y)
    off_x = (W - span_x * scale) / 2
    off_y = (H_MAP - span_y * scale) / 2

    def mx(lon: float) -> float:
        return off_x + (lon - min_lon) * x_scale * scale

    def my(lat: float) -> float:
        return H_MAP - off_y - (lat - min_lat) * scale

    segments = []
    for i in range(track.n - 1):
        a, b = track.fixes[i], track.fixes[i + 1]
        colour = ramp_colour((speeds[i] + speeds[i + 1]) / 2, lo_s, hi_s)
        segments.append(
            f'<line x1="{mx(a.lon):.2f}" y1="{my(a.lat):.2f}" '
            f'x2="{mx(b.lon):.2f}" y2="{my(b.lat):.2f}" stroke="{colour}" '
            f'stroke-width="2.2" stroke-linecap="round"/>'
        )

    # Altitude profile, x = distance along the track.
    alts = [f.alt_m for f in track.fixes]
    lo_a, hi_a = min(alts), max(alts)
    span_a = (hi_a - lo_a) or 1.0
    total_d = track.distance_m or 1.0

    def px(d: float) -> float:
        return PAD + d / total_d * (W - PAD * 2)

    def py(a: float) -> float:
        return H_PROFILE - 30 - (a - lo_a) / span_a * (H_PROFILE - 60)

    profile = " ".join(f"{px(d):.2f},{py(a):.2f}" for d, a in zip(cum, alts))
    profile_fill = f"{PAD},{H_PROFILE - 30} {profile} {px(total_d):.2f},{H_PROFILE - 30}"

    grid = "".join(
        f'<line x1="{PAD}" y1="{py(lo_a + span_a * t):.1f}" x2="{W - PAD}" '
        f'y2="{py(lo_a + span_a * t):.1f}" stroke="{GRID}" stroke-width="1"/>'
        f'<text x="{PAD - 8}" y="{py(lo_a + span_a * t) + 4:.1f}" text-anchor="end" '
        f'fill="{MUTED}" font-size="10">{lo_a + span_a * t:.0f}m</text>'
        for t in (0, 0.5, 1.0)
    )

    legend = "".join(
        f'<rect x="{W - PAD - 120 + i * 22}" y="18" width="22" height="8" fill="{c}"/>'
        for i, c in enumerate(SPEED_RAMP)
    )

    points_js = ",".join(
        f"[{mx(f.lon):.1f},{my(f.lat):.1f},{px(d):.1f},{py(f.alt_m):.1f},"
        f"{s:.2f},{c:.2f},{f.alt_m:.1f},{f.ts:.1f},{d:.1f}]"
        for f, d, s, c in zip(track.fixes, cum, speeds, climbs)
    )

    stats = [
        ("duration", f"{track.duration_s / 60:.1f} min"),
        ("distance", f"{track.distance_m / 1000:.2f} km"),
        ("max speed", f"{max(speeds) * 3.6:.1f} km/h"),
        ("max altitude", f"{hi_a:.0f} m"),
        ("max from home", f"{track.max_distance_from_home():.0f} m"),
        ("best climb", f"{max(climbs):+.1f} m/s"),
    ]
    stat_cells = "".join(
        f'<div class="cell"><dt>{html.escape(k)}</dt><dd>{html.escape(v)}</dd></div>'
        for k, v in stats
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  :root {{ --film:{FILM}; --grid:{GRID}; --ink:{INK}; --muted:{MUTED}; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--film); color:var(--ink);
         font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
  .wrap {{ max-width:900px; margin:0 auto; padding:32px 20px 64px; }}
  .eyebrow {{ font-size:10px; letter-spacing:.24em; text-transform:uppercase;
             color:var(--muted); margin-bottom:10px; }}
  h1 {{ font-size:22px; font-weight:600; margin:0 0 26px; letter-spacing:-.01em; }}
  .readout {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(118px,1fr));
             gap:1px; background:var(--grid); border:1px solid var(--grid); margin-bottom:26px; }}
  .cell {{ background:var(--film); padding:11px 13px; }}
  .cell dt {{ font-size:9px; letter-spacing:.14em; text-transform:uppercase;
             color:var(--muted); margin-bottom:4px; }}
  .cell dd {{ margin:0; font-size:17px; font-variant-numeric:tabular-nums; }}
  figure {{ margin:0 0 4px; border:1px solid var(--grid); background:#EFF1EC; }}
  svg {{ display:block; width:100%; height:auto; }}
  .caption {{ font-size:10px; color:var(--muted); letter-spacing:.1em;
             text-transform:uppercase; margin:8px 2px 22px; }}
  #readout {{ position:sticky; bottom:0; background:var(--film);
             border-top:1px solid var(--grid); padding:10px 2px; font-size:12px;
             font-variant-numeric:tabular-nums; color:var(--muted); }}
  #readout b {{ color:var(--ink); font-weight:600; }}
</style></head>
<body><div class="wrap">
  <p class="eyebrow">Flight log</p>
  <h1>{html.escape(title)}</h1>

  <dl class="readout">{stat_cells}</dl>

  <figure><svg viewBox="0 0 {W} {H_MAP}" xmlns="http://www.w3.org/2000/svg">
    <g>{"".join(segments)}</g>
    <circle cx="{mx(track.fixes[0].lon):.1f}" cy="{my(track.fixes[0].lat):.1f}" r="5"
            fill="none" stroke="{INK}" stroke-width="1.5"/>
    <text x="{mx(track.fixes[0].lon) + 9:.1f}" y="{my(track.fixes[0].lat) + 4:.1f}"
          fill="{INK}" font-size="10">home</text>
    <circle id="mapdot" r="4" fill="{INK}" opacity="0"/>
    {legend}
    <text x="{W - PAD - 128}" y="25" text-anchor="end" fill="{MUTED}" font-size="9">slow</text>
    <text x="{W - PAD + 4}" y="25" fill="{MUTED}" font-size="9">fast</text>
  </svg></figure>
  <p class="caption">plan view &#183; colour is ground speed</p>

  <figure><svg viewBox="0 0 {W} {H_PROFILE}" xmlns="http://www.w3.org/2000/svg">
    {grid}
    <polygon points="{profile_fill}" fill="{INK}" opacity="0.07"/>
    <polyline points="{profile}" fill="none" stroke="{INK}" stroke-width="1.6"/>
    <line id="cursor" y1="10" y2="{H_PROFILE - 30}" stroke="{INK}" stroke-width="1" opacity="0"/>
    <circle id="profdot" r="4" fill="{INK}" opacity="0"/>
  </svg></figure>
  <p class="caption">altitude against distance along track</p>

  <div id="readout">move over either chart to inspect the track</div>
</div>
<script>
const P = [{points_js}];
const mapSvg = document.querySelectorAll("svg")[0];
const profSvg = document.querySelectorAll("svg")[1];
const mapdot = document.getElementById("mapdot");
const profdot = document.getElementById("profdot");
const cursor = document.getElementById("cursor");
const out = document.getElementById("readout");

function svgPoint(svg, e) {{
  const r = svg.getBoundingClientRect();
  const vb = svg.viewBox.baseVal;
  return [(e.clientX - r.left) / r.width * vb.width, (e.clientY - r.top) / r.height * vb.height];
}}

function highlight(i) {{
  const p = P[i];
  mapdot.setAttribute("cx", p[0]); mapdot.setAttribute("cy", p[1]); mapdot.setAttribute("opacity", 1);
  profdot.setAttribute("cx", p[2]); profdot.setAttribute("cy", p[3]); profdot.setAttribute("opacity", 1);
  cursor.setAttribute("x1", p[2]); cursor.setAttribute("x2", p[2]); cursor.setAttribute("opacity", 0.4);
  out.innerHTML = "t <b>" + p[7].toFixed(1) + "s</b> &#183; " +
    (p[8] / 1000).toFixed(2) + "km along &#183; alt <b>" + p[6].toFixed(0) + "m</b> &#183; " +
    "speed <b>" + (p[4] * 3.6).toFixed(1) + "km/h</b> &#183; climb <b>" + p[5].toFixed(1) + "m/s</b>";
}}

function nearest(x, y, ix, iy) {{
  let best = 0, bd = Infinity;
  for (let i = 0; i < P.length; i++) {{
    const d = (P[i][ix] - x) ** 2 + (iy === null ? 0 : (P[i][iy] - y) ** 2);
    if (d < bd) {{ bd = d; best = i; }}
  }}
  return best;
}}

mapSvg.addEventListener("pointermove", e => {{
  const [x, y] = svgPoint(mapSvg, e); highlight(nearest(x, y, 0, 1));
}});
profSvg.addEventListener("pointermove", e => {{
  const [x] = svgPoint(profSvg, e); highlight(nearest(x, 0, 2, null));
}});
</script></body></html>"""


def main() -> None:
    p = argparse.ArgumentParser(description="GPS flight log to a single HTML page.")
    p.add_argument("csv", type=Path, nargs="?")
    p.add_argument("--demo", action="store_true")
    p.add_argument("-o", "--out", type=Path, default=Path("flight.html"))
    args = p.parse_args()

    track = synthetic() if (args.demo or not args.csv) else load_csv(args.csv)
    title = "synthetic flight" if (args.demo or not args.csv) else args.csv.stem
    args.out.write_text(render_html(track, title), encoding="utf-8")

    print(f"{track.n:,} fixes, {track.distance_m / 1000:.2f}km over "
          f"{track.duration_s / 60:.1f}min -> {args.out}")


if __name__ == "__main__":
    main()
