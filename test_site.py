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

if __name__ == '__main__':
    unittest.main()
