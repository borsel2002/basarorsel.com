"""Receipt calculations: missing data, ties, calendar boundaries and rendering."""
import unittest
from fit_pipeline import discipline_summary
from build_site import discipline_receipts, receipt_chart


def workout(date, **fields):
    return dict(start_time=date, sport='swimming', **fields)


class DisciplineReceiptsTests(unittest.TestCase):
    def test_pace_uses_paired_measurements_and_weighting(self):
        result = discipline_summary([
            workout('2026-01-01T10:00:00+00:00', total_distance=100, total_timer_time=60),
            workout('2026-01-02T10:00:00+00:00', total_distance=300, total_timer_time=240),
            workout('2026-01-03T10:00:00+00:00', total_distance=900),
            workout('2026-01-04T10:00:00+00:00', total_distance=0, total_timer_time=100),
        ])
        self.assertEqual(result['pace_s_100m'], 75)
        self.assertEqual(result['pace_recorded'], 2)
        self.assertEqual(result['bests']['fastest_pace']['value'], 60)
        self.assertEqual(result['bests']['fastest_pace']['dates'], ['2026-01-01'])
        self.assertIsNone(result['sessions'][-1]['pace_s_100m'])
        self.assertEqual(result['recorded']['hours'], 3)

    def test_local_calendar_ties_and_daily_ascent(self):
        result = discipline_summary([
            workout('2025-12-31T22:00:00+00:00', total_ascent=100, total_timer_time=600),
            workout('2026-01-01T10:00:00+00:00', total_ascent=200, total_timer_time=600),
            workout('2026-01-04T22:00:00+00:00'),
        ])
        self.assertEqual(result['sessions'][0]['date'], '2026-01-01')
        self.assertEqual(result['bests']['biggest_ascent']['value'], 200)
        self.assertEqual(result['bests']['biggest_ascent_day']['value'], 300)
        self.assertEqual(result['bests']['most_sessions_week']['dates'], ['2025-12-29'])
        self.assertEqual(result['bests']['most_sessions_month']['value'], 3)
        self.assertEqual(len(result['bests']['longest_session']['dates']), 2)
        self.assertEqual(result['monthly'][0]['recorded']['duration_s'], 2)

    def test_partial_ascent_day_reports_winning_coverage(self):
        result = discipline_summary([
            workout('2026-01-01T10:00:00+00:00', total_ascent=100),
            workout('2026-01-01T11:00:00+00:00'),
        ])
        self.assertEqual(result['bests']['biggest_ascent_day']['winning_coverage'],
                         [{'date': '2026-01-01', 'recorded': 1, 'total': 2}])
        self.assertIn('1/2 sessions measured', discipline_receipts(result, 'mountaineering'))

    def test_built_snapshot_receipts_reconcile(self):
        import json
        from pathlib import Path
        data = json.loads(Path('data.json').read_text())
        html = Path('index.html').read_text()
        for kind in ('mountaineering', 'swim', 'strength', 'mobility'):
            summary = data['disciplines'][kind]
            self.assertEqual(summary['count'], len(summary['sessions']))
            self.assertEqual(summary['count'], sum(r['count'] for r in summary['monthly']))
            seconds = sum(r['duration_s'] or 0 for r in summary['sessions'])
            self.assertAlmostEqual(summary['hours'], seconds / 3600, places=3)
            self.assertIn(discipline_receipts(summary, kind), html)
        self.assertEqual(data['disciplines']['swim_run']['count'], data['swim']['count'] + data['totals']['run_n'])
        self.assertIn('data-running-link', html)
        for token in ('__STRENGTH__', '__MOBILITY__', '__HIKING__', '__SWIM__'):
            self.assertNotIn(token, html)

    def test_missing_and_recorded_zero_are_distinct(self):
        empty = discipline_summary([])
        self.assertTrue(all(v is None for v in empty['bests'].values()))
        for kind in ('swim', 'mountaineering', 'strength', 'mobility'):
            self.assertIn('No data recorded', discipline_receipts(empty, kind))
        zero = discipline_summary([workout('2026-01-01T10:00:00+00:00', total_ascent=0)])
        self.assertEqual(zero['bests']['biggest_ascent']['value'], 0)
        self.assertIsNone(zero['bests']['longest_distance'])
        self.assertIn('height="0.0"', receipt_chart(zero['sessions'], 'ascent_m', 'Ascent'))

    def test_render_receipts_and_escape_fit_labels(self):
        result = discipline_summary([workout('2026-01-01T10:00:00+00:00', sub_sport='<script>', total_timer_time=600)])
        html = discipline_receipts(result, 'strength')
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)
        self.assertIn('0:10:00', html)
        self.assertIn('Most sessions / week', html)
        self.assertIn('not current fitness', html)
        self.assertIn('<title>', html)


if __name__ == '__main__':
    unittest.main()
