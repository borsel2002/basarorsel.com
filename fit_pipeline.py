#!/usr/bin/env python3
"""
build.py — full pipeline: raw .fit files -> deploy-ready index.html

    python3 build.py [--fit-dir DIR] [--out FILE]

Every number on the site is computed here. Nothing is typed by hand.
Drop new .fit files into the fit directory and re-run; the site updates.

FIT dir resolution order: --fit-dir flag > $FIT_DIR > ./fit > parent dir
(the parent-dir default matches a HealthFit iCloud export folder, where
this project lives in a `website/` subfolder next to the .fit files).
"""
import os, sys, json, glob, argparse, datetime, collections, math
from multiprocessing import Pool

try:
    import fitdecode
except ImportError:
    sys.exit("fitdecode missing — run: pip install -r requirements.txt")

HERE = os.path.dirname(os.path.abspath(__file__))

SESSION_KEYS = [
    "sport", "sub_sport", "start_time", "total_timer_time", "total_elapsed_time",
    "total_distance", "total_calories", "avg_heart_rate", "max_heart_rate",
    "avg_speed", "max_speed", "enhanced_avg_speed", "enhanced_max_speed",
    "total_ascent", "total_descent", "avg_cadence", "avg_running_cadence",
    "avg_power", "max_power", "total_strides", "min_heart_rate", "num_laps",
]


SEMI = 180.0 / 2 ** 31  # FIT semicircles -> degrees


SPLIT_TARGETS = {"k1": 1000.0, "k5": 5000.0, "k10": 10000.0, "hm": 21097.5}
# plausibility floor: any window faster than this pace is GPS junk, not sport
MIN_PACE_S_PER_KM = {"k1": 150, "k5": 165, "k10": 175, "hm": 185}


def best_windows(ts, ds):
    """Fastest rolling window per target distance. Two-pointer, O(n) each."""
    out = {}
    for key, target in SPLIT_TARGETS.items():
        if not ds or ds[-1] < target:
            continue
        best, i = None, 0
        for j in range(len(ds)):
            while ds[j] - ds[i] >= target:
                dt = ts[j] - ts[i]
                if best is None or dt < best:
                    best = dt
                i += 1
        if best and best >= MIN_PACE_S_PER_KM[key] * target / 1000:
            out[key] = round(best)
    return out


def decoupling(ts, spd, hr):
    """Aerobic decoupling: efficiency (speed/HR) first half vs second half, %.
    Positive = HR drifted for the same pace. Under ~5 percent = coupled."""
    if len(ts) < 60 or len(hr) < 0.8 * len(ts):
        return None
    mid_t = ts[0] + (ts[-1] - ts[0]) / 2
    a_s = a_h = b_s = b_h = an = bn = 0
    for i in range(len(ts)):
        if not spd[i] or not hr[i]:
            continue
        if ts[i] <= mid_t:
            a_s += spd[i]; a_h += hr[i]; an += 1
        else:
            b_s += spd[i]; b_h += hr[i]; bn += 1
    if an < 30 or bn < 30 or not a_h or not b_h or not b_s:
        return None
    ef1 = (a_s / an) / (a_h / an)
    ef2 = (b_s / bn) / (b_h / bn)
    return round((ef1 / ef2 - 1) * 100, 1) if ef2 else None


def detect_breakpoints(records):
    """Likely stops: speed <0.5 m/s for >120s; gaps >30s break evidence.

    Records are (lat, lon, epoch seconds, speed or None). Distance fallback
    uses consecutive fixes; never infer a stop across missing GPS coverage.
    """
    out, slow = [], []
    def finish():
        if len(slow) > 1 and slow[-1][2] - slow[0][2] > 120:
            out.append({'lat': sum(p[0] for p in slow)/len(slow),
                        'lon': sum(p[1] for p in slow)/len(slow),
                        'duration_s': round(slow[-1][2]-slow[0][2])})
    for i, p in enumerate(records):
        prev = records[i-1] if i else None
        gap = p[2]-prev[2] if prev else None
        if gap is not None and not 0 < gap <= 30:
            # Gap breaks evidence: flush, then evaluate this point on its own
            # explicit speed only — never derive speed across missing coverage.
            finish(); slow = []
            speed = p[3]
            if speed is not None and speed < 0.5:
                slow.append(p)
            continue
        speed = p[3]
        if speed is None and prev and gap:
            dy = math.radians(p[0]-prev[0])
            dx = math.radians(p[1]-prev[1])*math.cos(math.radians((p[0]+prev[0])/2))
            speed = math.hypot(dx, dy)*6371000/gap
        if speed is not None and speed < 0.5:
            if not slow and prev and p[3] is None:
                slow.append(prev)
            slow.append(p)
        else:
            finish(); slow = []
    finish()
    return out


def load_routine_rules(path=None):
    import re
    from pathlib import Path
    from zoneinfo import ZoneInfo
    text = Path(path or os.path.join(HERE, 'routines.md')).read_text()
    blocks = re.findall(r'```json\s*\n(.*?)\n```', text, re.S)
    if len(blocks) != 1:
        raise ValueError('routines.md must contain exactly one JSON block')
    rules = json.loads(blocks[0])
    if rules['version'] != 1:
        raise ValueError('unsupported routine schema')
    ZoneInfo(rules['timezone'])
    datetime.date.fromisoformat(rules['historical_before'])
    for name, item in rules['routines'].items():
        if item['category'] not in ('strength', 'mobility') or not item['muscles']:
            raise ValueError('invalid routine: '+name)
        if any(not re.fullmatch(r'[a-z]+(?:-[a-z]+)*', m) for m in item['muscles']):
            raise ValueError('invalid muscle identifier')
    for category in ('strength', 'mobility'):
        for name in rules['historical'][category]:
            if rules['routines'][name]['category'] != category:
                raise ValueError('historical category mismatch')
    for entry in rules['sessions']:
        when = entry['when']
        if len(when) == 10:
            datetime.date.fromisoformat(when)
        elif datetime.datetime.fromisoformat(when).tzinfo is None:
            raise ValueError('routine timestamps require timezone')
        if not entry['routines'] or any(n not in rules['routines'] for n in entry['routines']):
            raise ValueError('unknown or empty routine')
    return rules


def muscle_summary(ws, rules):
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(rules['timezone'])
    def local(w):
        t = dt(w)
        if t.tzinfo is None:
            raise ValueError('workout timestamps require timezone for routine matching')
        return t.astimezone(zone)
    if not ws:
        return {'as_of': None, 'recent_from': None, 'unit': 'attributed sessions',
                'strength': {}, 'mobility': {}}
    end = max(local(w).date() for w in ws)
    start = end - datetime.timedelta(days=27)
    result = {'as_of': end.isoformat(), 'recent_from': start.isoformat(), 'unit':'attributed sessions'}
    for category in ('strength', 'mobility'):
        muscles = sorted({m for r in rules['routines'].values() if r['category']==category for m in r['muscles']})
        summary = {'all_time':dict.fromkeys(muscles,0), 'recent_28d':dict.fromkeys(muscles,0),
                   'matched_sessions':0, 'unmatched_sessions':0, 'historical_sessions':0, 'logged_sessions':0}
        for w in ws:
            if sport_category(w) != ('mind_and_body' if category=='mobility' else category):
                continue
            t = local(w)
            exact, dates = [], []
            for entry in rules['sessions']:
                when = entry['when']
                if len(when)==10 and when==t.date().isoformat(): dates.extend(entry['routines'])
                elif len(when)>10 and datetime.datetime.fromisoformat(when)==t: exact.extend(entry['routines'])
            names = exact or dates
            historical = not names and t.date().isoformat() < rules['historical_before']
            if historical: names = rules['historical'][category]
            assigned = {m for n in names if rules['routines'][n]['category']==category for m in rules['routines'][n]['muscles']}
            if not assigned:
                summary['unmatched_sessions'] += 1
                continue
            summary['matched_sessions'] += 1
            summary['historical_sessions' if historical else 'logged_sessions'] += 1
            for m in assigned:
                summary['all_time'][m] += 1
                if start <= t.date() <= end: summary['recent_28d'][m] += 1
        result[category] = summary
    return result


def parse_file(path):
    """Extract session summary, GPS trace, best splits and decoupling."""
    d = {"file": os.path.basename(path)}
    pts, ts, ds, hrs, spds, alts = [], [], [], [], [], []
    gps_records = []
    try:
        with fitdecode.FitReader(path, check_crc=fitdecode.CrcCheck.DISABLED) as fr:
            for frame in fr:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                if frame.name == "record":
                    try:
                        lat = frame.get_value("position_lat", fallback=None)
                        lon = frame.get_value("position_long", fallback=None)
                        t = frame.get_value("timestamp", fallback=None)
                        dist = frame.get_value("distance", fallback=None)
                        hr = frame.get_value("heart_rate", fallback=None)
                        spd = frame.get_value("enhanced_speed", fallback=None)
                        if spd is None:
                            spd = frame.get_value("speed", fallback=None)
                    except Exception:
                        continue
                    if lat is not None and lon is not None:
                        pts.append((lat * SEMI, lon * SEMI))
                        if t is not None:
                            gps_records.append((lat * SEMI, lon * SEMI, t.timestamp(), spd))
                    if t is not None and dist is not None:
                        try:
                            alt = (frame.get_value("enhanced_altitude", fallback=None)
                                   or frame.get_value("altitude", fallback=None))
                        except Exception:
                            alt = None
                        ts.append(t.timestamp())
                        ds.append(dist)
                        hrs.append(hr or 0)
                        spds.append(spd or 0)
                        alts.append(alt)
                elif frame.name == "session" and "sport" not in d:
                    for f in frame.fields:
                        if f.name in SESSION_KEYS and f.value is not None:
                            d[f.name] = str(f.value) if isinstance(f.value, datetime.datetime) else f.value
    except Exception as e:
        d["error"] = str(e)
    d["breakpoints"] = detect_breakpoints(gps_records)
    if pts:
        d["pts"] = pts  # preserve corners; simplify only after cluster projection
    if ts:
        d["best"] = best_windows(ts, ds)
        if d.get("total_timer_time", 0) >= 2400:  # decoupling only means something ≥40 min
            dec = decoupling(ts, spds, hrs)
            if dec is not None:
                d["dec"] = dec
        # elevation profile for half-marathon-plus efforts and hikes: ~120 samples by distance
        if ds[-1] >= 21000 or d.get("sport") == "hiking":
            prof = [(ds[i], alts[i]) for i in range(len(ds)) if alts[i] is not None]
            if len(prof) > 20:
                step = max(1, len(prof) // 120)
                d["elev"] = [[round(p[0] / 1000, 2), round(p[1], 1)] for p in prof[::step]]
    return d


# ---------- GPS route processing ------------------------------------------

def rdp(points, tol):
    """Ramer–Douglas–Peucker line simplification (iterative)."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1e-12
        dmax, idx = 0.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            dist = abs(dx * (ay - py) - dy * (ax - px)) / norm
            if dist > dmax:
                dmax, idx = dist, i
        if dmax > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def build_routes(ws, min_traces=3):
    """Cluster GPS traces by location and render each cluster as SVG paths."""
    traces = []
    for w in ws:
        pts = w.get("pts")
        if not pts or len(pts) < 4:
            continue
        traces.append({"pts": pts, "sport": w.get("sport", "other"),
                       "km": w.get("total_distance", 0) / 1000,
                       "cx": pts[0][1], "cy": pts[0][0],
                       "breakpoints": w.get("breakpoints", []),
                       "lat0": pts[0][0], "lon0": pts[0][1]})
    if not traces:
        return {"clusters": [], "other": {"n": 0, "km": 0}}

    # greedy clustering on trace centroids (~4 km radius, running centroid)
    clusters = []
    for t in traces:
        best = None
        for c in clusters:
            dd = math.hypot((c["cx"] - t["cx"])*math.cos(math.radians((c["cy"]+t["cy"])/2)), c["cy"] - t["cy"])
            if dd < 0.035 and (best is None or dd < best[0]):
                best = (dd, c)
        if best:
            c = best[1]
            c["tr"].append(t)
            n = len(c["tr"])
            c["cx"] += (t["cx"] - c["cx"]) / n
            c["cy"] += (t["cy"] - c["cy"]) / n
        else:
            clusters.append({"cx": t["cx"], "cy": t["cy"], "tr": [t]})

    clusters.sort(key=lambda c: -sum(t["km"] for t in c["tr"]))
    shown = [c for c in clusters if len(c["tr"]) >= min_traces][:4]
    rest = [c for c in clusters if c not in shown]

    def pct(vals, lo, hi):
        v = sorted(vals)
        return v[int(lo * (len(v) - 1))], v[int(hi * (len(v) - 1))]

    out = []
    for c in shown:
        clat = math.cos(math.radians(c["cy"]))
        for t in c["tr"]:
            g = 0.00005  # ~5.5m in the local projected plane
            snapped = [(round(lon*clat/g)*g, round(lat/g)*g) for lat, lon in t["pts"]]
            flat = [p for i,p in enumerate(snapped) if i == 0 or p != snapped[i-1]]
            t["xy"] = rdp(flat, 0.00002)
        c["tr"] = [t for t in c["tr"] if len(t.get("xy", [])) >= 2]
        if not c["tr"]:
            continue
        xs = [x for t in c["tr"] for x, _ in t["xy"]]
        ys = [y for t in c["tr"] for _, y in t["xy"]]
        # percentile bbox: one stray point-to-point route must not blow up
        # the canvas; SVG clips anything outside the viewBox anyway
        x0, x1 = pct(xs, 0.01, 0.99)
        y0, y1 = pct(ys, 0.01, 0.99)
        pad = max(x1 - x0, y1 - y0, 1e-4) * 0.06
        x0, x1, y0, y1 = x0 - pad, x1 + pad, y0 - pad, y1 + pad
        W = 1000.0
        H = max(240, min(1000, round(W * (y1 - y0) / (x1 - x0))))
        sx, sy = W / (x1 - x0), H / (y1 - y0)
        s = min(sx, sy)
        ox = (W - (x1 - x0) * s) / 2
        oy = (H - (y1 - y0) * s) / 2
        paths, breakpoints = [], []
        for t in c["tr"]:
            for stop in t["breakpoints"]:
                breakpoints.append({"x":round(ox+(stop["lon"]*clat-x0)*s,1),
                                    "y":round(oy+(y1-stop["lat"])*s,1),
                                    "duration_s":stop["duration_s"]})
            coords = [(ox + (x - x0) * s, oy + (y1 - y) * s) for x, y in t["xy"]]
            dstr = "M" + "L".join(f"{x:.0f} {y:.0f}" for x, y in coords)
            paths.append({"d": dstr, "s": t["sport"]})
        # label: mean start coordinate, engineer-style
        lat = sum(t["lat0"] for t in c["tr"]) / len(c["tr"])
        lon = sum(t["lon0"] for t in c["tr"]) / len(c["tr"])
        label = f"{abs(lat):.2f}°{'N' if lat >= 0 else 'S'} {abs(lon):.2f}°{'E' if lon >= 0 else 'W'}"
        out.append({"label": label, "n": len(c["tr"]),
                    "km": round(sum(t["km"] for t in c["tr"]), 1),
                    "w": round(W), "h": round(H), "paths": paths, "breakpoints": breakpoints})
    other = {"n": sum(len(c["tr"]) for c in rest),
             "km": round(sum(t["km"] for c in rest for t in c["tr"]), 1)}
    return {"clusters": out, "other": other,
            "breakpoint_count": sum(len(w.get("breakpoints", [])) for w in ws),
            "breakpoint_method": "Likely stops / break points: speed <0.5 m/s for >120s; GPS gaps >30s excluded"}


def swim_routes(ws):
    """One map per swim; never infer pool/open water from GPS presence."""
    sessions = []
    for w in ws:
        sub = w.get('sub_sport')
        kind = ('Pool' if sub == 'lap_swimming' else
                'Open-water' if sub == 'open_water' or w.get('sport') == 'open_water_swimming'
                else 'Swim type not recorded')
        pts = w.get('pts') or []
        usable = [p for p in pts if len(p) == 2 and all(math.isfinite(v) for v in p)
                  and -90 <= p[0] <= 90 and -180 <= p[1] <= 180 and p != (0, 0) and p != [0, 0]]
        maps = []
        if kind != 'Pool' and len(usable) >= 4:
            maps = build_routes([dict(w, pts=usable)], min_traces=1)['clusters']
        if maps:
            status = None
        elif kind == 'Pool' and pts:
            status = 'Pool session: GPS trace not displayed'
        elif not pts:
            status = 'no GPS trace recorded'
        else:
            status = 'no usable GPS trace recorded'
        sessions.append({'date': dt(w).date().isoformat(), 'kind': kind,
                         'km': None if w.get('total_distance') is None else round(w['total_distance']/1000, 3),
                         'map': maps[0] if maps else None, 'status': status})
    return sessions


def hike_routes(ws):
    """One map per hike; simplified projected GPS, no basemap."""
    sessions = []
    for w in ws:
        pts = w.get('pts') or []
        usable = [p for p in pts if len(p) == 2 and all(math.isfinite(v) for v in p)
                  and -90 <= p[0] <= 90 and -180 <= p[1] <= 180 and p != (0, 0) and p != [0, 0]]
        maps = build_routes([dict(w, pts=usable)], min_traces=1)['clusters'] if len(usable) >= 4 else []
        sessions.append({'date': dt(w).date().isoformat(),
                         'km': None if w.get('total_distance') is None else round(w['total_distance']/1000, 3),
                         'ascent_m': w.get('total_ascent'),
                         'map': maps[0] if maps else None,
                         'status': None if maps else ('no GPS trace recorded' if not pts else 'no usable GPS trace recorded')})
    return sessions


def dt(w):
    return datetime.datetime.fromisoformat(w["start_time"])


def pace(w):
    s = w.get("enhanced_avg_speed") or w.get("avg_speed")
    return round(1000 / s / 60, 3) if s else None


def sport_category(w):
    """Exclusive display groups; retain original FIT sport labels separately."""
    sport = str(w.get("sport") or "unknown")
    sub = str(w.get("sub_sport") or "")
    if sub in ("strength_training", "strength"):
        return "strength"
    mind = {"fitness_equipment", "yoga", "flexibility", "flexibility_training",
            "pilates", "mind_and_body"}
    if sport in mind or sub in mind:
        return "mind_and_body"
    if "training" in sport:
        return "strength"
    if sport in ("swimming", "open_water_swimming"):
        return "swimming"
    return 'other' if sport in ('generic', 'unknown', 'other') else sport


def sport_summary(ws, sessions=False):
    """Sum recorded session fields only. Null is unrecorded, not zero.

    Coverage accompanies each sum so partial recordings are never presented as
    complete measurements. Duration is timer time, not elapsed wall-clock time.
    """
    fields = {"hours": ("total_timer_time", 3600),
              "km": ("total_distance", 1000), "ascent_m": ("total_ascent", 1)}
    out = {"count": len(ws), "recorded": {}}
    for key, (field, divisor) in fields.items():
        values = [w[field] for w in ws if w.get(field) is not None]
        out["recorded"][key] = len(values)
        out[key] = round(sum(values) / divisor, 3) if values else None
    if sessions:
        out["sessions"] = [
            {"date": dt(w).date().isoformat(),
             "km": round(w["total_distance"] / 1000, 3) if w.get("total_distance") is not None else None,
             "ascent_m": w.get("total_ascent"), "duration_s": w.get("total_timer_time")}
            for w in ws]
    return out


def discipline_summary(ws):
    """Recorded receipts; calendar periods use Europe/Istanbul, including ISO weeks.

    Pace uses paired positive distance/timer measurements, never separate totals.
    Best ties retain every date; missing measurements never compete as zero.
    """
    from zoneinfo import ZoneInfo
    zone = ZoneInfo('Europe/Istanbul')
    out = sport_summary(ws)
    rows = []
    for w in ws:
        distance, seconds = w.get('total_distance'), w.get('total_timer_time')
        rows.append(dict(date=dt(w).astimezone(zone).date().isoformat(),
                         start_time=w['start_time'], sport=w.get('sport'), sub_sport=w.get('sub_sport'),
                         km=distance / 1000 if distance is not None else None,
                         duration_s=seconds, ascent_m=w.get('total_ascent'),
                         pace_s_100m=seconds * 100 / distance
                         if distance is not None and distance > 0 and seconds is not None and seconds > 0 else None))
    out['sessions'] = sorted(rows, key=lambda r: r['start_time'])
    out['timezone'] = 'Europe/Istanbul'
    paired = [r for r in rows if r['pace_s_100m'] is not None]
    out['pace_recorded'] = len(paired)
    out['pace_s_100m'] = (sum(r['duration_s'] for r in paired) / sum(r['km'] for r in paired) / 10) if paired else None
    def best(items, field, smallest=False):
        eligible = [r for r in items if r.get(field) is not None]
        if not eligible:
            return None
        value = (min if smallest else max)(r[field] for r in eligible)
        return {'value': value, 'dates': [r['date'] for r in eligible if r[field] == value],
                'recorded': len(eligible), 'total': len(items),
                'winning_coverage': [{'date': r['date'], 'recorded': r['recorded'][field], 'total': r['count']}
                                     for r in eligible if r[field] == value and 'recorded' in r and field in r['recorded']]}
    periods = {}
    for period in ('weekly', 'monthly', 'daily'):
        groups = collections.defaultdict(list)
        for row in rows:
            day = datetime.date.fromisoformat(row['date'])
            key = ((day - datetime.timedelta(days=day.weekday())).isoformat() if period == 'weekly'
                   else day.strftime('%Y-%m') if period == 'monthly' else day.isoformat())
            groups[key].append(row)
        periods[period] = []
        for date, group in sorted(groups.items()):
            entry = {'date': date, 'count': len(group), 'recorded': {}}
            for field in ('duration_s', 'km', 'ascent_m'):
                vals = [r[field] for r in group if r[field] is not None]
                entry[field] = sum(vals) if vals else None
                entry['recorded'][field] = len(vals)
            periods[period].append(entry)
    out.update(periods)
    out['bests'] = {'longest_distance': best(rows, 'km'), 'longest_session': best(rows, 'duration_s'),
                    'fastest_pace': best(rows, 'pace_s_100m', True),
                    'biggest_ascent': best(rows, 'ascent_m'),
                    'biggest_ascent_day': best(periods['daily'], 'ascent_m'),
                    'most_sessions_week': best(periods['weekly'], 'count'),
                    'most_sessions_month': best(periods['monthly'], 'count')}
    return out


def aggregate(parsed):
    # Dedupe: the same workout often exists from several sync apps.
    # Same start_time + sport -> keep the record with the most fields.
    by_start = {}
    score = lambda w: ("pts" in w, len(w))  # prefer records that carry a GPS trace
    for w in parsed:
        if "error" in w or "start_time" not in w:
            continue
        k = (w["start_time"], w.get("sport"))
        if k not in by_start or score(w) > score(by_start[k]):
            by_start[k] = w
    ws = sorted(by_start.values(), key=lambda w: w["start_time"])
    if not ws:
        sys.exit("no parsable workouts found")

    runs = [w for w in ws if w.get("sport") == "running"]
    walks = [w for w in ws if w.get("sport") == "walking"]
    strength = [w for w in ws if sport_category(w) == "strength"]
    mind = [w for w in ws if sport_category(w) == "mind_and_body"]
    hikes = [w for w in ws if w.get("sport") == "hiking"]
    swims = [w for w in ws if w.get("sport") in ("swimming", "open_water_swimming")]
    groups = collections.defaultdict(list)
    for w in ws:
        groups[(sport_category(w), str(w.get("sport") or "unknown"))].append(w)
    sports = [dict(category=category, sport=sport,
                   sub_sports=sorted({str(w["sub_sport"]) for w in items if w.get("sub_sport")}),
                   **sport_summary(items))
              for (category, sport), items in sorted(groups.items())]
    assert sum(s["count"] for s in sports) == len(ws)

    run_pts = [{"d": dt(w).strftime("%Y-%m-%d"), "km": round(w.get("total_distance", 0) / 1000, 2),
                "pace": pace(w), "hr": w.get("avg_heart_rate"),
                "min": round(w.get("total_timer_time", 0) / 60, 1)}
               for w in runs if w.get("total_distance", 0) > 500]

    # monthly volume
    mon = collections.defaultdict(lambda: {"km": 0.0, "n": 0})
    for w in runs:
        m = dt(w).strftime("%Y-%m")
        mon[m]["km"] += w.get("total_distance", 0) / 1000
        mon[m]["n"] += 1
    monthly = [{"m": m, "km": round(v["km"], 1), "n": v["n"]} for m, v in sorted(mon.items())]

    # weekly volume, zero-filled so gaps stay visible — the data does not hide
    wk = collections.defaultdict(float)
    for w in runs:
        y, wn, _ = dt(w).isocalendar()
        wk[(y, wn)] += w.get("total_distance", 0) / 1000
    weekly = []
    if wk:
        cur = datetime.date.fromisocalendar(*min(wk), 1)
        end = datetime.date.fromisocalendar(*max(wk), 1)
        while cur <= end:
            y, wn, _ = cur.isocalendar()
            weekly.append({"w": f"{y}-W{wn:02d}", "km": round(wk.get((y, wn), 0), 1)})
            cur += datetime.timedelta(days=7)

    # quarterly aerobic efficiency
    q = collections.defaultdict(lambda: {"p": [], "h": []})
    for w in runs:
        key = f"{dt(w).year}-Q{(dt(w).month - 1) // 3 + 1}"
        if pace(w):
            q[key]["p"].append(pace(w))
        if w.get("avg_heart_rate"):
            q[key]["h"].append(w["avg_heart_rate"])
    quarterly = [{"q": k, "pace": round(sum(v["p"]) / len(v["p"]), 2),
                  "hr": round(sum(v["h"]) / len(v["h"]))}
                 for k, v in sorted(q.items()) if v["p"] and v["h"]]

    # PRs — all computed
    longest = max(runs, key=lambda w: w.get("total_distance", 0))
    r5 = [w for w in runs if w.get("total_distance", 0) >= 5000]
    r21 = sorted([w for w in runs if w.get("total_distance", 0) >= 21000], key=lambda w: w["start_time"])
    big_wk = max(((k, v) for k, v in wk.items()), key=lambda kv: kv[1])
    big_mon = max(monthly, key=lambda m: m["km"])
    prs = {
        "longest_km": round(longest["total_distance"] / 1000, 2),
        "longest_date": dt(longest).strftime("%Y-%m-%d"),
        "biggest_week_km": round(big_wk[1], 1), "biggest_week": f"{big_wk[0][0]}-W{big_wk[0][1]:02d}",
        "biggest_month_km": big_mon["km"], "biggest_month": big_mon["m"],
        "max_hr": max((w.get("max_heart_rate", 0) for w in runs), default=0),
    }
    if r5:
        f5 = min(r5, key=pace)
        prs["fastest_5k_pace"] = pace(f5)
        prs["fastest_5k_date"] = dt(f5).strftime("%Y-%m-%d")
    if r21:
        fhm = min(r21, key=pace)
        prs["fastest_hm"] = {"km": round(fhm["total_distance"] / 1000, 2),
                             "date": dt(fhm).strftime("%Y-%m-%d"),
                             "min": round(fhm["total_timer_time"] / 60),
                             "pace": pace(fhm), "hr": fhm.get("avg_heart_rate")}
    def elev_gain(elev):
        """Ascent from an elevation profile: moving-average smoothing first,
        so GPS altitude noise doesn't masquerade as climbing."""
        if not elev or len(elev) < 10:
            return None
        a = [p[1] for p in elev]
        k = 5
        sm = [sum(a[max(0, i - k // 2):i + k // 2 + 1]) / len(a[max(0, i - k // 2):i + k // 2 + 1])
              for i in range(len(a))]
        return round(sum(max(0.0, sm[i + 1] - sm[i]) for i in range(len(sm) - 1)))

    hm_list = [{"d": dt(w).strftime("%Y-%m-%d"), "km": round(w["total_distance"] / 1000, 2),
                "min": round(w["total_timer_time"] / 60), "pace": pace(w),
                "hr": w.get("avg_heart_rate"),
                "gain": w.get("total_ascent") or elev_gain(w.get("elev")),
                "elev": w.get("elev")} for w in r21]

    # Swim-day marker, not proof of a completed triathlon or a bike leg.
    tri = None

    if swims:
        day = dt(swims[-1]).date()
        items = [{"s": (w.get("sport") or "").replace("_", " "),
                  "km": round(w.get("total_distance", 0) / 1000, 2),
                  "min": round(w.get("total_timer_time", 0) / 60)}
                 for w in ws if dt(w).date() == day]
        tri = {"date": day.isoformat(), "items": items}

    # true best splits: fastest rolling 1k/5k/10k/HM window ever recorded
    best = {}
    for w in runs:
        for k, sec in (w.get("best") or {}).items():
            if k not in best or sec < best[k]["s"]:
                best[k] = {"s": sec, "d": dt(w).strftime("%Y-%m-%d")}

    # aerobic decoupling per qualifying run (≥40 min with HR)
    dec_pts = [{"d": dt(w).strftime("%Y-%m-%d"), "v": w["dec"],
                "km": round(w.get("total_distance", 0) / 1000, 1)}
               for w in runs if "dec" in w]

    # training load: Banister TRIMP per session -> CTL/ATL/TSB.
    # HRmax = highest HR ever recorded here; HRrest = 60 (assumed, stated).
    hr_max = max((w.get("max_heart_rate", 0) for w in ws), default=190)
    hr_rest = 60
    daily = collections.defaultdict(float)
    for w in ws:
        ahr, tmin = w.get("avg_heart_rate"), w.get("total_timer_time", 0) / 60
        if ahr and tmin and ahr > hr_rest:
            hrr = min((ahr - hr_rest) / (hr_max - hr_rest), 1.0)
            daily[dt(w).date()] += tmin * hrr * 0.64 * math.exp(1.92 * hrr)
    load = []
    if daily and runs:
        ctl = atl = 0.0
        k42, k7 = 1 - math.exp(-1 / 42), 1 - math.exp(-1 / 7)
        day = dt(runs[0]).date()
        end = max(daily)
        while day <= end:
            trimp = daily.get(day, 0.0)
            ctl += (trimp - ctl) * k42
            atl += (trimp - atl) * k7
            load.append({"d": day.isoformat(), "c": round(ctl, 1),
                         "a": round(atl, 1), "t": round(ctl - atl, 1)})
            day += datetime.timedelta(days=1)

    # longest gap between training days — full disclosure, computed.
    # Measured from the first run onward (the continuous training era),
    # so sparse pre-history logging doesn't masquerade as a training gap.
    era_start = dt(runs[0]).date() if runs else None
    days = sorted({dt(w).date() for w in ws if era_start is None or dt(w).date() >= era_start})
    gap = {"days": 0}
    for a, b in zip(days, days[1:]):
        if (b - a).days > gap["days"]:
            gap = {"days": (b - a).days, "from": a.isoformat(), "to": b.isoformat()}

    return {
        "generated": datetime.date.today().isoformat(),
        "meta": {"files": len(parsed), "unique": len(ws)},
        "sports": sports,
        "disciplines": {name: discipline_summary(items) for name, items in
                        (("mountaineering", hikes), ("swim", swims), ("strength", strength),
                         ("mobility", mind))} | {"swim_run": sport_summary(swims + runs)},
        "muscle_load": muscle_summary(ws, load_routine_rules()),
        "routine_method": "Muscle exposure inferred by matching workout timestamps/dates against routines.md; historical sessions use the approved routine union. Programmatic estimate, not biometric measurement.",
        "hiking": sport_summary(hikes, sessions=True),
        "swim": sport_summary(swims, sessions=True),
        "swim_routes": swim_routes(swims),
        "hike_routes": hike_routes(hikes),
        "hike_profiles": [{"d": dt(w).strftime("%Y-%m-%d"), "elev": w.get("elev")}
                          for w in hikes if w.get("elev")],
        "totals": {
            "workouts": len(ws),
            "hours": round(sum(w.get("total_timer_time", 0) for w in ws) / 3600),
            "kcal": sum(w.get("total_calories", 0) for w in ws),
            "run_km": round(sum(w.get("total_distance", 0) for w in runs) / 1000, 1),
            "run_n": len(runs),
            "run_h": round(sum(w.get("total_timer_time", 0) for w in runs) / 3600, 1),
            "walk_km": round(sum(w.get("total_distance", 0) for w in walks) / 1000),
            "walk_n": len(walks),
            "strength_n": len(strength),
            "strength_h": round(sum(w.get("total_timer_time", 0) for w in strength) / 3600, 1),
            "mind_n": len(mind),
            "ascent_m": round(sum(w.get("total_ascent", 0) for w in runs)),
            "first_run": dt(runs[0]).strftime("%Y-%m") if runs else None,
        },
        "prs": prs, "quarterly": quarterly, "monthly": monthly, "weekly": weekly,
        "runs": run_pts, "hm": hm_list, "tri_day": tri, "gap": gap,
        "routes": build_routes(ws),
        "best": best, "dec": dec_pts, "load": load,
        "hr": {"max": hr_max, "rest_assumed": hr_rest},
    }


