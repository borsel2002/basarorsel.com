#!/usr/bin/env python3
"""Render one self-contained HTML file. No dependencies for snapshot builds.

python3 build_site.py
python3 build_site.py --fit-dir /path/to/HealthFit/exports  # requires fitdecode
"""
import argparse
import base64
import json
from pathlib import Path
from html import escape

HERE = Path(__file__).resolve().parent


def number(value):
    return '—' if value is None else f'{value:,.3f}'.rstrip('0').rstrip('.')


def metric(summary, key):
    value = number(summary[key])
    recorded = summary['recorded'][key]
    if 0 < recorded < summary['count']:
        value += f' ({recorded}/{summary["count"]} recorded)'
    return value


def table(headers, rows):
    return ('<div class="chart-scroll" tabindex="0" role="region" aria-label="Recorded data table"><table><thead><tr>' +
            ''.join(f'<th scope="col">{escape(h)}</th>' for h in headers) +
            '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(
                f'<td>{escape(str(v))}</td>' for v in row) + '</tr>' for row in rows) +
            '</tbody></table></div>')


def discipline_log(summary, ascent=False):
    cards = [(str(summary['count']), 'sessions'), (metric(summary, 'km'), 'recorded km'),
             (metric(summary, 'hours'), 'timer hours')]
    if ascent:
        cards.append((metric(summary, 'ascent_m'), 'recorded ascent / m'))
    html = '<div class="kpis">' + ''.join(
        f'<div class="s"><div class="v">{v}</div><div class="k">{k}</div></div>'
        for v, k in cards) + '</div>'
    rows = []
    for s in summary['sessions']:
        sec = s['duration_s']
        duration = '—' if sec is None else f'{int(round(sec))//3600}:{int(round(sec))%3600//60:02d}:{int(round(sec))%60:02d}'
        rows.append([s['date'], number(s['km'])] +
                    ([number(s['ascent_m'])] if ascent else []) + [duration])
    return html + table(['Date', 'km'] + (['Ascent / m'] if ascent else []) + ['Timer / h:mm:ss'], rows)



def receipt_number(value):
    return 'No data recorded' if value is None else number(value)


def receipt_metric(summary, key):
    return 'No data recorded' if summary[key] is None else metric(summary, key)


def receipt_time(seconds):
    if seconds is None:
        return 'No data recorded'
    seconds = round(seconds)
    return f'{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'


def swim_pace(seconds):
    if seconds is None:
        return 'No data recorded'
    seconds = round(seconds)
    return f'{seconds // 60}:{seconds % 60:02d} /100 m'


def receipt_chart(rows, field, label):
    measured = [r for r in rows if r[field] is not None]
    if not measured:
        return '<p class="sub">No data recorded for ' + escape(label) + '.</p>'
    width, height = max(640, len(rows) * 22), 180
    maximum = max(r[field] for r in measured) or 1
    svg = f'<div class="chart-scroll" tabindex="0" role="region" aria-label="{escape(label)} chart"><svg style="min-width:{width}px;width:100%;height:220px" viewBox="0 0 {width} 220" role="img"><title>{escape(label)}; exact values in the table below</title>'
    for i, row in enumerate(rows):
        x = 10 + i * (width - 20) / len(rows)
        value = row[field]
        title = escape(row['date'] + ': ' + receipt_number(value))
        if value is None:
            svg += f'<text x="{x}" y="190" fill="currentColor"><title>{title}</title>?</text>'
        else:
            h = value / maximum * height
            svg += f'<rect x="{x}" y="{190-h}" width="12" height="{h}" fill="currentColor"><title>{title}</title></rect>'
    return svg + '</svg></div><p class="sub">Chronological bars; ? means no measurement. Exact dates and values follow.</p>'


def discipline_receipts(summary, kind):
    if not summary:
        return '<p>No data recorded.</p>'
    endurance = kind in ('mountaineering', 'swim')
    cards = [('Sessions', str(summary['count']) if summary['count'] else 'No data recorded'),
             ('Timer hours', receipt_metric(summary, 'hours'))]
    if endurance:
        cards.append(('Distance / km', receipt_metric(summary, 'km')))
    if kind == 'mountaineering':
        cards.append(('Total elevation gained / m', receipt_metric(summary, 'ascent_m')))
    if kind == 'swim':
        cards.append(('Pace / timer time', swim_pace(summary['pace_s_100m'])))
    html = table(['Recorded volume', 'Value'], cards)
    html += '<p class="sub">Dates and calendar periods: Europe/Istanbul. Durations are timer time, excluding pauses. Partial totals identify measurement coverage.</p>'
    if kind == 'swim':
        html += f'<p class="sub">Distance-weighted pace uses paired positive distance and timer time: {summary["pace_recorded"]}/{summary["count"]} sessions. Pool and open-water conditions are not equivalent; this is whole-session pace, not a fastest split.</p>'
    html += '<h4>Recorded bests</h4><p class="sub">Bests in this export, not current fitness or certified results. All tied dates are listed. Missing measurements are excluded; partial-day ascent is a recorded sum.</p>'
    specs = [('longest_session', 'Longest session', receipt_time)]
    if endurance:
        specs.append(('longest_distance', 'Longest hike / km' if kind == 'mountaineering' else 'Longest swim / km', receipt_number))
    if kind == 'mountaineering':
        specs += [('biggest_ascent', 'Biggest session ascent / m', receipt_number), ('biggest_ascent_day', 'Biggest ascent day / m', receipt_number)]
    if kind == 'swim':
        specs.append(('fastest_pace', 'Fastest whole-session pace', swim_pace))
    if not endurance:
        specs += [('most_sessions_week', 'Most sessions / week starting Monday', receipt_number), ('most_sessions_month', 'Most sessions / calendar month', receipt_number)]
    best_rows = []
    for key, label, formatter in specs:
        b = summary['bests'][key]
        best_rows.append([label, formatter(b['value']) if b else 'No data recorded',
                          (', '.join(b['dates']) + ''.join(f' [{c["date"]}: {c["recorded"]}/{c["total"]} sessions measured]' for c in b.get('winning_coverage', []))) if b else 'No data recorded',
                          f'{b["recorded"]}/{b["total"]}' if b else 'No data recorded'])
    html += table(['Best', 'Value', 'Date / period (all ties)', 'Measured / eligible'], best_rows)
    html += '<h4>Training over time</h4>'
    if kind == 'mountaineering':
        html += receipt_chart(summary['sessions'], 'ascent_m', 'Per-session ascent / m')
    else:
        html += receipt_chart(summary['monthly'], 'duration_s', 'Monthly timer seconds')
    html += table(['Month', 'Sessions', 'Timer hours (coverage)'], [
        [r['date'], r['count'], receipt_number(r['duration_s'] / 3600 if r['duration_s'] is not None else None) + f' ({r["recorded"]["duration_s"]}/{r["count"]} recorded)']
        for r in summary['monthly']])
    html += '<h4>Session receipts</h4>'
    headers = ['Date', 'FIT sport', 'FIT sub-sport', 'Timer / h:mm:ss']
    if endurance:
        headers += ['km', 'Ascent / m' if kind == 'mountaineering' else 'Pace / min:sec per 100 m']
    rows = []
    for r in summary['sessions']:
        row = [r['date'], r['sport'] or 'No data recorded', r['sub_sport'] or 'No data recorded', receipt_time(r['duration_s'])]
        if endurance:
            row += [receipt_number(r['km']), receipt_number(r['ascent_m']) if kind == 'mountaineering' else swim_pace(r['pace_s_100m'])]
        rows.append(row)
    return html + (table(headers, rows) if rows else '<p>No data recorded for this discipline.</p>')

def hike_maps_and_profiles(data):
    html = '<h4>Hike maps / recorded GPS</h4><p class="sub">Simplified, projected GPS traces; no basemap, not for navigation. Sessions without GPS say "no GPS trace recorded".</p><div class="swim-maps">'
    if not data.get('hike_routes'):
        html += '<p class="sub">No hike GPS data recorded.</p>'
    for session in data.get('hike_routes', []):
        label = f"{session['date']} · {number(session['km'])} km · {receipt_number(session['ascent_m'])} m ascent"
        html += '<figure class="swim-map"><figcaption>' + escape(label) + '</figcaption>'
        m = session['map']
        if m:
            html += f'<svg viewBox="0 0 {m["w"]} {m["h"]}" role="img" aria-label="{escape(label)}"><title>{escape(label)}</title>'
            html += ''.join(f'<path d="{escape(p["d"])}"/>' for p in m['paths']) + '</svg>'
        else:
            html += '<p class="sub">' + escape(session['status']) + '</p>'
        html += '</figure>'
    html += '</div>'
    profiles = data.get('hike_profiles', [])
    if profiles:
        html += '<h4>Hike elevation profiles</h4><p class="sub">Watch-derived altitude by distance; can contain GPS altitude error.</p><div id="hikeElevProfiles">'
        for h in profiles:
            if not h.get('elev') or len(h['elev']) < 2:
                continue
            W, H = 440, 56
            xs = [p[0] for p in h['elev']]
            ys = [p[1] for p in h['elev']]
            xmin, xmax = min(xs), max(xs)
            ymin, ymax = min(ys), max(ys)
            xr = (xmax - xmin) or 1
            yr = (ymax - ymin) or 1
            pts = ' '.join(f"{10 + (x - xmin) / xr * (W - 20)},{H - 8 - (y - ymin) / yr * (H - 16)}" for x, y in h['elev'])
            html += f'<div class="ep"><div class="cap"><span>{escape(h["d"])}</span><span>{ymin:.0f}–{ymax:.0f} m</span></div><svg viewBox="0 0 {W} {H}" role="img" aria-label="Elevation profile {escape(h["d"])}"><polyline class="line" points="{pts}"/></svg></div>'
        html += '</div>'
    return html


def achievements(data):
    """Unified all-discipline bests, computed from the FIT export only."""
    prs = data.get('prs', {})
    best = data.get('best', {})
    disc = data.get('disciplines', {})
    rows = []
    def add(label, value, date):
        if value is None:
            return
        rows.append([label, value, date])

    # Running
    if best.get('k1'): add('Fastest 1 km', f"{best['k1']['s']} s", best['k1']['d'])
    if best.get('k5'): add('Fastest 5 km', f"{best['k5']['s']} s", best['k5']['d'])
    if best.get('k10'): add('Fastest 10 km', f"{best['k10']['s']} s", best['k10']['d'])
    if best.get('hm'): add('Fastest half marathon', f"{best['hm']['s']} s", best['hm']['d'])
    if prs.get('longest_km'): add('Longest run', f"{prs['longest_km']} km", prs.get('longest_date'))
    if prs.get('biggest_week_km'): add('Biggest running week', f"{prs['biggest_week_km']} km", prs.get('biggest_week'))
    if prs.get('biggest_month_km'): add('Biggest running month', f"{prs['biggest_month_km']} km", prs.get('biggest_month'))
    if prs.get('max_hr'): add('Highest recorded heart rate', f"{prs['max_hr']} bpm", '—')

    # Mountaineering
    m = disc.get('mountaineering', {}).get('bests', {})
    if m.get('biggest_ascent'): add('Biggest single-session ascent', f"{m['biggest_ascent']['value']} m", ', '.join(m['biggest_ascent']['dates']))
    if m.get('biggest_ascent_day'): add('Biggest ascent day', f"{m['biggest_ascent_day']['value']} m", ', '.join(m['biggest_ascent_day']['dates']))
    if m.get('longest_distance'): add('Longest hike', f"{round(m['longest_distance']['value'],2)} km", ', '.join(m['longest_distance']['dates']))

    # Swim
    s = disc.get('swim', {}).get('bests', {})
    if s.get('longest_distance'): add('Longest swim', f"{round(s['longest_distance']['value'],2)} km", ', '.join(s['longest_distance']['dates']))
    if s.get('fastest_pace'): add('Fastest swim pace', f"{round(s['fastest_pace']['value'],1)} s/100m", ', '.join(s['fastest_pace']['dates']))

    # Strength / mobility frequency
    st = disc.get('strength', {}).get('bests', {})
    if st.get('most_sessions_week'): add('Most strength sessions in a week', f"{st['most_sessions_week']['value']}", ', '.join(st['most_sessions_week']['dates']))
    if st.get('most_sessions_month'): add('Most strength sessions in a month', f"{st['most_sessions_month']['value']}", ', '.join(st['most_sessions_month']['dates']))
    mo = disc.get('mobility', {}).get('bests', {})
    if mo.get('most_sessions_week'): add('Most mobility sessions in a week', f"{mo['most_sessions_week']['value']}", ', '.join(mo['most_sessions_week']['dates']))

    if not rows:
        return '<p class="sub">No recorded bests in this export.</p>'
    return table(['Achievement', 'Value', 'Date(s)'], rows)


def multisport(data):
    disciplines = data.get('disciplines', {})
    swim = discipline_receipts(disciplines.get('swim'), 'swim') if disciplines else discipline_log(data['swim'])
    combined = disciplines.get('swim_run')
    if combined:
        swim = '<h4>Combined swim + run volume</h4>' + table(['Sessions', 'Recorded km', 'Timer hours'], [[combined['count'], receipt_metric(combined, 'km'), receipt_metric(combined, 'hours')]]) + '<p class="sub">Distance is a sum across disciplines, not an equivalent training load or an event result.</p>' + swim
    swim += '<h4>Swim map / recorded GPS</h4><p class="sub">Simplified, projected GPS traces; no basemap, not for navigation. Swim type comes from FIT metadata, not the shape of a trace. Sessions without GPS say “no GPS trace recorded”; pool GPS is not plotted.</p><div class="swim-maps">'
    if not data.get('swim_routes'):
        swim += '<p class="sub">No swim GPS data recorded.</p>'
    for session in data.get('swim_routes', []):
        label = f"{session['date']} · {session['kind']} · {number(session['km'])} km"
        swim += '<figure class="swim-map"><figcaption>' + escape(label) + '</figcaption>'
        m = session['map']
        if m:
            swim += f'<svg viewBox="0 0 {m["w"]} {m["h"]}" role="img" aria-label="{escape(label)}"><title>{escape(label)}</title>'
            swim += ''.join(f'<path d="{escape(p["d"])}"/>' for p in m['paths']) + '</svg>'
        else:
            swim += '<p class="sub">' + escape(session['status']) + '</p>'
        swim += '</figure>'
    swim += '</div>'
    bike = [s for s in data['sports'] if 'cycling' in s['sport'] or s['sport'] == 'biking']
    note = ('Cycling sessions are listed in the full training mix below.' if bike else
            'No cycling data in this FIT export. Swim + run only; no bike leg or bike totals are inferred.')
    swim += f'<p class="goalnote">{note}</p>'
    running = [s for s in data['sports'] if s['sport'] == 'running']
    swim += '<p class="goalnote">Running record: ' + '; '.join(
        f'{s["count"]} runs · {metric(s, "km")} km · {metric(s, "hours")} h' for s in running) + '. <a href="#data" data-running-link>Running dashboard →</a></p>'
    rows = [[s['category'].replace('_', ' '), s['sport'].replace('_', ' '),
             ', '.join(t.replace('_', ' ') for t in s['sub_sports']) or '—', s['count'],
             metric(s, 'hours'), metric(s, 'km'), metric(s, 'ascent_m')] for s in data['sports']]
    hiking = discipline_receipts(disciplines.get('mountaineering'), 'mountaineering') if disciplines else discipline_log(data['hiking'], ascent=True)
    hiking += hike_maps_and_profiles(data)
    return {'__HIKING__': hiking, '__SWIM__': swim,
            '__STRENGTH__': discipline_receipts(disciplines.get('strength'), 'strength'),
            '__MOBILITY__': discipline_receipts(disciplines.get('mobility'), 'mobility'),
            '__SPORTS__': table(['Discipline', 'FIT sport', 'Sub-sports', 'Sessions', 'Hours', 'km', 'Ascent / m'], rows),
            '__ACHIEVEMENTS__': achievements(data)}


def render(data, output):
    for period in ('monthly', 'weekly'):
        total = sum(row['km'] for row in data[period])
        assert abs(total-data['totals']['run_km']) < 1.5, f'{period} totals do not reconcile'
    template = (HERE/'template.html').read_text()
    assert template.count('__DATA__') == 1
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    html = template.replace('__DATA__', payload)
    assert sum(s['count'] for s in data['sports']) == data['meta']['unique']
    for token, content in multisport(data).items():
        assert html.count(token) == 1
        html = html.replace(token, content)
    # Inline brand assets: the resulting page works alone, even from file://.
    for asset in ('signature.svg', 'logo.svg', 'brand-logo-light.svg', 'brand-logo-dark.svg'):
        uri = 'data:image/svg+xml;base64,' + base64.b64encode((HERE/asset).read_bytes()).decode()
        html = html.replace(f'"{asset}"', f'"{uri}"')
    output.write_text(html)
    print(f"Built {output.name}: {data['totals']['workouts']} workouts, {data['totals']['run_km']} run km, {data['totals']['hours']} h; {len(html.encode()):,} bytes")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fit-dir', type=Path)
    parser.add_argument('--data', type=Path, default=HERE/'data.json')
    parser.add_argument('--out', type=Path, default=HERE/'index.html')
    args = parser.parse_args()
    if args.fit_dir:
        from concurrent.futures import ProcessPoolExecutor
        from fit_pipeline import parse_file, aggregate
        files = sorted(args.fit_dir.glob('*.fit'))
        if not files:
            parser.error('no .fit files found')
        with ProcessPoolExecutor(max_workers=8) as pool:
            parsed = list(pool.map(parse_file, map(str, files)))
        failures = [item for item in parsed if 'error' in item]
        if failures:
            parser.error(f'{len(failures)} FIT files unreadable; refusing silent partial publication')
        data = aggregate(parsed)
        args.data.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':'))+'\n')
    else:
        data = json.loads(args.data.read_text())
    render(data, args.out)

if __name__ == '__main__':
    main()
