"""Static acceptance checks; run with python3 -m unittest -v."""
import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

class SiteTests(unittest.TestCase):
    def test_embedded_training_snapshot_and_routes(self):
        path = HERE / 'index.html'
        self.assertTrue(path.exists(), 'portfolio index.html has not been built')
        html = path.read_text()
        match = re.search(r'const D = (.*?);\n', html)
        self.assertIsNotNone(match, 'training JSON must be embedded')
        assert match is not None
        data = json.loads(match.group(1))
        self.assertEqual(data, json.loads((HERE / 'data.json').read_text()))
        for section in ('sports', 'data', 'projects', 'code', 'directory'):
            self.assertIn(f'<section id="{section}">', html)
        for chart in ('monChart','wkChart','effChart','runScatter','loadChart','decChart','routeMaps','elevProfiles'):
            self.assertIn(f'id="{chart}"', html)
        self.assertNotIn('__DATA__', html)
        self.assertNotRegex(html, r'<script[^>]+src=|<link[^>]+rel="stylesheet"')
        for period in ('monthly','weekly'):
            self.assertLess(abs(sum(row['km'] for row in data[period])-data['totals']['run_km']),1.5)
        self.assertIn("const modes = ['auto','light','dark'];",html)
        self.assertIn("h<7 || h>=19",html)
        for block in ('hikingPanel', 'swimPanel', 'sportsTable'):
            self.assertIn(f'id="{block}"', html)
        self.assertNotIn('__MULTISPORT__', html)
        self.assertIn('No cycling data in this FIT export', html)
        self.assertIn(f'<td>{data["hiking"]["sessions"][0]["date"]}</td>', html)
        self.assertIn(f'<td>{data["swim"]["sessions"][0]["date"]}</td>', html)
        self.assertEqual(sum(s['count'] for s in data['sports']), data['meta']['unique'])
        self.assertEqual(data['hiking']['count'], len(data['hiking']['sessions']))
        self.assertEqual(data['swim']['count'], len(data['swim']['sessions']))

class MultiSportTests(unittest.TestCase):
    def test_missing_measurements_and_partial_coverage(self):
        from fit_pipeline import sport_summary
        from build_site import metric, multisport
        summary = sport_summary([{'total_timer_time': 3600, 'total_distance': 0}, {}])
        self.assertEqual(summary['count'], 2)
        self.assertEqual(summary['hours'], 1)
        self.assertEqual(summary['km'], 0)
        self.assertIsNone(summary['ascent_m'])
        self.assertEqual(metric(summary, 'hours'), '1 (1/2 recorded)')
        self.assertEqual(metric(summary, 'ascent_m'), '—')
        empty = sport_summary([], sessions=True)
        self.assertEqual(empty['sessions'], [])
        self.assertIsNone(empty['hours'])
        data = {'hiking': empty, 'swim': empty, 'sports': []}
        self.assertIn('No cycling data', multisport(data)['__SWIM__'])
        data['sports'] = [dict(sport_summary([{}]), category='cycling', sport='cycling', sub_sports=[])]
        self.assertNotIn('No cycling data', multisport(data)['__SWIM__'])

    def test_unreadable_fit_aborts_without_publishing(self):
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'broken.fit').write_bytes(b'not a FIT file')
            output, snapshot = root / 'index.html', root / 'data.json'
            result = subprocess.run([sys.executable, str(HERE / 'build_site.py'),
                                     '--fit-dir', tmp, '--data', str(snapshot), '--out', str(output)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('refusing silent partial publication', result.stderr)
            self.assertFalse(output.exists())
            self.assertFalse(snapshot.exists())

    def test_every_sport_is_counted_after_deduplication(self):
        from fit_pipeline import aggregate
        def session(day, sport, **fields):
            return dict(start_time=f'2026-01-{day:02d}T10:00:00+00:00',
                        sport=sport, total_timer_time=3600, **fields)
        run = session(1, 'running', total_distance=1000)
        hike = session(2, 'hiking', total_distance=12345, total_ascent=456)
        rows = [run, hike, dict(hike), session(3, 'swimming', total_distance=1500),
                session(4, 'open_water_swimming', total_distance=2000),
                session(5, 'strength_training'), session(6, 'fitness_equipment'),
                session(7, 'yoga'), session(8, 'flexibility_training'),
                session(9, 'pilates'), session(10, 'mind_and_body'),
                session(11, 'jump_rope'), session(12, 'other'), session(13, 'rowing', total_distance=500)]
        data = aggregate(rows)
        self.assertIn('sports', data, 'all disciplines need an exhaustive summary')
        self.assertEqual(sum(s['count'] for s in data['sports']), 13)
        self.assertEqual(sum(s['hours'] for s in data['sports']), 13)
        by_sport = {s['sport']: s for s in data['sports']}
        self.assertEqual(by_sport['flexibility_training']['category'], 'mind_and_body')
        self.assertEqual(by_sport['strength_training']['category'], 'strength')
        self.assertIsNone(by_sport['other']['km'])
        self.assertEqual(by_sport['rowing']['km'], 0.5)
        self.assertEqual(data['hiking']['count'], 1)
        self.assertEqual(data['hiking']['km'], 12.345)
        self.assertEqual(data['hiking']['ascent_m'], 456)
        self.assertEqual(data['hiking']['sessions'][0],
                         dict(date='2026-01-02', km=12.345, ascent_m=456, duration_s=3600))
        self.assertEqual(data['swim']['count'], 2)
        self.assertEqual(data['swim']['km'], 3.5)
        self.assertEqual(data['swim']['hours'], 2)
        self.assertEqual(len(data['swim']['sessions']), 2)
        self.assertEqual(data['tri_day']['date'], '2026-01-04')
        self.assertIsNone(data['swim']['ascent_m'])
        self.assertNotIn('cycling', by_sport)

if __name__ == '__main__':
    unittest.main()
