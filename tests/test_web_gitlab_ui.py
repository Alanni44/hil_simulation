from __future__ import absolute_import

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class GitLabWebUiTests(unittest.TestCase):
    def test_console_contains_release_workflow_without_browser_token_field(self):
        html = (ROOT / 'web' / 'hil_console.html').read_text(encoding='utf-8')
        client = (ROOT / 'web' / 'hil_console_gitlab.js').read_text(encoding='utf-8')

        self.assertIn('GitLab 受控发布', html)
        self.assertIn('gitlab_status', client)
        self.assertIn('gitlab_list_releases', client)
        self.assertIn('gitlab_stage_release', client)
        self.assertIn('build_package', client)
        self.assertIn('deploy_package', client)
        self.assertIn('elements.refresh.disabled = !state.configured', client)
        self.assertNotIn('HIL_GITLAB_TOKEN', html + client)
        self.assertNotIn('type="password"', html)


if __name__ == '__main__':
    unittest.main()
