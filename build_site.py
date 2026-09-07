#!/usr/bin/env python3
"""Render one self-contained HTML file. No dependencies for snapshot builds.

python3 build_site.py
python3 build_site.py --fit-dir /path/to/HealthFit/exports  # requires fitdecode
"""
import argparse
import base64
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

def render(data, output):
    for period in ('monthly', 'weekly'):
        total = sum(row['km'] for row in data[period])
        assert abs(total-data['totals']['run_km']) < 1.5, f'{period} totals do not reconcile'
    template = (HERE/'template.html').read_text()
    assert template.count('__DATA__') == 1
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    html = template.replace('__DATA__', payload)
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
