import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class PolicyConsistencyTests(unittest.TestCase):
    def test_repository_checklist_matches_distributed_checklist(self):
        self.assertEqual((ROOT / '.agent/dod-checklist.md').read_bytes(),
                         (ROOT / 'strict-mode/templates/dod-checklist.md').read_bytes())

    def test_current_inventory_accepts_independent_fallback(self):
        text = (ROOT / 'docs/current-stack-inventory.md').read_text()
        self.assertNotIn('not be represented as completed implementation review', text)
        self.assertIn('satisfies the implementation-review gate', text)

    def test_canon_preserves_scoped_merge_authority(self):
        text = (ROOT / 'docs/canon.md').read_text()
        self.assertNotIn('- Do not self-merge.', text)
        self.assertIn('exact or standing human authorization', text)
        self.assertIn('repository policy', text)

    def test_active_review_instructions_have_no_retired_round_limits(self):
        for name in ('docs/canon.md', 'docs/review-workflow.md',
                     'strict-mode/methodology.md', 'skills/gh-review-certify-loop/SKILL.md'):
            with self.subTest(path=name):
                text = (ROOT / name).read_text()
                for obsolete in ('At most two revise-and-re-review', 'up to seven minutes',
                                 'two consecutive bounded waits'):
                    self.assertNotIn(obsolete, text)
