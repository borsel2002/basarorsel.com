import json
import re
import unittest
from pathlib import Path
from fit_pipeline import evidence_summary, best_windows, muscle_summary, load_routine_rules

class EvidenceTests(unittest.TestCase):
    def test_missing_zero_indoor_gps_and_months(self):
        pts = [(38+i*.0001,27+i*.0001) for i in range(20)]
        base = dict(sport='walking',start_time='2026-01-01T10:00:00+00:00')
        rows = [dict(base,pts=pts,total_distance=0,total_timer_time=3600,total_ascent=0,record_hr=True),
                dict(base,start_time='2026-03-01T10:00:00+00:00'),
                dict(base,pts=pts,sub_sport='indoor')]
        d=evidence_summary(rows); c=d['coverage'][0]
        self.assertEqual([c[k] for k in ('sessions','distance','timer','ascent','hr','gps','exercise_detail')],[3,1,1,1,1,1,0])
        self.assertEqual(len(d['training_mix']['monthly']),3)
        self.assertEqual(d['training_mix']['monthly'][1]['sessions'],0)
        self.assertEqual(sum(sum(r['hours'].values()) for r in d['training_mix']['monthly']),1)
        self.assertIsNone(d['discipline_routes']['walking'][2]['map'])

    def test_three_kilometres(self):
        self.assertEqual(best_windows(list(range(0,1201,10)),list(range(0,6001,50)))['k3'],600)

    def test_seven_day_boundary(self):
        rows=[dict(sport='training',start_time=f'2026-09-{day:02d}T10:00:00+03:00') for day in (1,2,8)]
        rules=load_routine_rules();rules['historical_before']='2026-09-09'
        d=muscle_summary(rows,rules)['strength']
        self.assertEqual(d['recent_7d']['quads'],2)
        self.assertEqual(d['recent_28d']['quads'],3)

    def test_snapshot_and_render(self):
        d=json.loads(Path('data.json').read_text());s=Path('index.html').read_text()
        self.assertEqual(sum(r['sessions'] for r in d['coverage']),d['meta']['unique'])
        self.assertAlmostEqual(sum(sum(r['hours'].values()) for r in d['training_mix']['monthly']),sum(r['hours'] or 0 for r in d['sports']),delta=.01)
        for name in ('coverage','training-mix','data-records','tab-records'):
            self.assertIn(f'id="{name}"',s)
        self.assertIn('Routine sources / routines.md',s)
        self.assertIn('Meet the person →',s)
        self.assertNotRegex(s,r'__[A-Z_]+__|(?i:sprint[- ]orienteer)|<script[^>]+src=|<link[^>]+rel="stylesheet"')
        self.assertLess(s.index('id="coverage"'),s.index('<section id="builder">'))
        for category,routes in d['discipline_routes'].items():
            self.assertEqual(sum(r['map'] is not None for r in routes),next(c['gps'] for c in d['coverage'] if c['category']==category))
