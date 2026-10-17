"""Documentation coverage and read-only delivery contracts."""
import json
from pathlib import Path
import tempfile
import unittest

from app import create_app
from uwb.workspace import capabilities

ROOT = Path(__file__).resolve().parents[1]


class UserGuideTests(unittest.TestCase):
    def test_every_default_editor_input_has_specific_help(self):
        catalog = json.loads((ROOT / 'web/input-help.json').read_text(encoding='utf-8'))

        def leaves(value, prefix=''):
            for key, item in value.items():
                path = f'{prefix}.{key}' if prefix else key
                if isinstance(item, dict):
                    yield from leaves(item, path)
                else:
                    yield path

        for engine, model in capabilities()['models'].items():
            for path in leaves(model['defaults']):
                if not path.startswith(('physical.', 'assumptions.', 'numerical.')) or path.startswith('assumptions.survey.'):
                    continue
                with self.subTest(engine=engine, path=path):
                    self.assertGreater(len(catalog['paths'].get(path, '')), 40)
        reference = (ROOT / 'docs/INPUT_REFERENCE.md').read_text(encoding='utf-8')
        for path in catalog['paths']:
            self.assertIn(f'`{path}`', reference)

    def test_guide_and_catalog_are_available_without_saved_history_or_fits(self):
        with tempfile.TemporaryDirectory() as directory:
            client = create_app(directory).test_client()
            for route, expected in [('/user-guide.html', b'First experiment'),
                                    ('/input-reference.html', b'physical.acquisition.spacing_s'),
                                    ('/function-reference.html', b'fit_observations'),
                                    ('/input-help.json', b'assumptions.assumed_std_m'),
                                    ('/help.js', b'aria-describedby'), ('/help.css', b'field-help-tooltip')]:
                with self.subTest(route=route):
                    response = client.get(route)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(expected, response.data)
                    response.close()
            self.assertEqual(list(Path(directory).rglob('*.json')), [])

    def test_local_guide_navigation_targets_exist(self):
        from html.parser import HTMLParser

        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []
                self.ids = set()

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if 'id' in attrs:
                    self.ids.add(attrs['id'])
                if tag == 'a':
                    self.links.append(attrs.get('href', ''))

        for page in ('user-guide', 'input-reference', 'function-reference'):
            parser = Links()
            parser.feed((ROOT / 'web' / f'{page}.html').read_text(encoding='utf-8'))
            for target in parser.links:
                with self.subTest(page=page, target=target):
                    if target.startswith('#'):
                        self.assertIn(target[1:], parser.ids)
                    elif target.endswith('.html'):
                        self.assertTrue((ROOT / 'web' / target.lstrip('/')).is_file())


if __name__ == '__main__':
    unittest.main()
