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
    return ('<div class="chart-scroll"><table><thead><tr>' +
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


def multisport(data):
    swim = discipline_log(data['swim'])
    swim += '<h4>Swim map / recorded GPS</h4><p class="sub">Simplified, projected GPS traces; no basemap, not for navigation. Swim type comes from FIT metadata, not the shape of a trace. Sessions without GPS say “no GPS trace recorded”; pool GPS is not plotted.</p><div class="swim-maps">'
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
        f'{s["count"]} runs · {metric(s, "km")} km · {metric(s, "hours")} h' for s in running) + '. <a href="#data">Running dashboard →</a></p>'
    rows = [[s['category'].replace('_', ' '), s['sport'].replace('_', ' '),
             ', '.join(t.replace('_', ' ') for t in s['sub_sports']) or '—', s['count'],
             metric(s, 'hours'), metric(s, 'km'), metric(s, 'ascent_m')] for s in data['sports']]
    return {'__HIKING__': discipline_log(data['hiking'], ascent=True), '__SWIM__': swim,
            '__SPORTS__': table(['Discipline', 'FIT sport', 'Sub-sports', 'Sessions', 'Hours', 'km', 'Ascent / m'], rows)}


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
