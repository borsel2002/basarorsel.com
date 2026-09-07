import datetime
import tempfile
import unittest
from pathlib import Path

class ImprovementTests(unittest.TestCase):
    def test_stops_speed_distance_gap_and_threshold(self):
        from fit_pipeline import detect_breakpoints
        records = [(38, 27, t, 0.0) for t in range(0, 151, 10)]
        self.assertEqual(detect_breakpoints(records)[0]['duration_s'], 150)
        self.assertEqual(len(detect_breakpoints([(a,b,t,None) for a,b,t,s in records])), 1)
        self.assertEqual(detect_breakpoints(records[:13]), [])
        self.assertEqual(detect_breakpoints([(38,27,0,0),(38,27,180,0)]), [])
        self.assertEqual(detect_breakpoints([(38,27,t,1) for t in range(151)]), [])
        # stop immediately after a GPS gap: first valid sample must not be dropped
        gap_then_stop = [(38,27,0,0.0),(38,27,60,0.0),(38,27,90,0.0),(38,27,120,0.0),(38,27,150,0.0),(38,27,180,0.0),(38,27,190,0.0)]
        self.assertEqual(detect_breakpoints(gap_then_stop)[0]['duration_s'], 130)

    def test_routine_history_future_and_exact_precedence(self):
        from fit_pipeline import load_routine_rules, muscle_summary
        rules = load_routine_rules()
        def workout(date):
            return {'start_time': date, 'sport':'training'}
        rules['sessions'] = [{'when':'2026-09-09','routines':['Leg']},
                             {'when':'2026-09-09T10:00:00+03:00','routines':['Neck']}]
        result = muscle_summary([workout('2026-09-07T10:00:00+03:00'),workout('2026-09-09T10:00:00+03:00'),workout('2026-09-10T10:00:00+03:00')], rules)
        strength = result['strength']
        self.assertEqual(strength['matched_sessions'], 2)
        self.assertEqual(strength['unmatched_sessions'], 1)
        self.assertEqual(strength['all_time']['neck-flexors'], 2)
        self.assertEqual(strength['all_time']['quads'], 1)
        self.assertEqual(strength['recent_28d']['quads'], 1)

    def test_cluster_projection_and_breakpoint_payload(self):
        from fit_pipeline import build_routes
        pts = [(38+i*.0001,27+i*.0001) for i in range(20)]
        ws = [{'pts':pts,'sport':'running','breakpoints':[{'lat':38.001,'lon':27.001,'duration_s':130}]} for _ in range(3)]
        cluster = build_routes(ws)['clusters'][0]
        self.assertEqual(len(cluster['breakpoints']),3)
        self.assertEqual(cluster['paths'][0]['d'],cluster['paths'][1]['d'])
        self.assertTrue(all(0 <= p['x'] <= cluster['w'] for p in cluster['breakpoints']))

    def test_swim_routes_metadata_and_missing_gps(self):
        from fit_pipeline import swim_routes, build_routes
        base = dict(start_time='2026-01-01T12:00:00+00:00', sport='swimming', total_distance=1500)
        pts = [(38+i*.0001,27+i*.0001) for i in range(20)]
        rows = [dict(base,sub_sport='open_water',pts=pts), dict(base,sub_sport='lap_swimming'),
                dict(base,pts=[(38,27)]*5),dict(base,pts=pts),dict(base,sub_sport='lap_swimming',pts=pts)]
        result = swim_routes(rows)
        self.assertEqual(result[0]['kind'],'Open-water')
        self.assertTrue(result[0]['map']['paths'])
        self.assertEqual(result[1]['status'],'no GPS trace recorded')
        self.assertIsNone(result[2]['map'])
        self.assertEqual(result[3]['kind'],'Swim type not recorded')
        self.assertIsNone(result[4]['map'])
        self.assertEqual(build_routes([rows[0]])['clusters'],[])
        self.assertEqual(result[0]['km'],1.5)

if __name__ == '__main__':
    unittest.main()
