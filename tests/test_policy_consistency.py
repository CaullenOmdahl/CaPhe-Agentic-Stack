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

    def test_active_review_surfaces_allow_separate_same_family_review(self):
        for name in ('docs/canon.md', 'docs/review-workflow.md', 'docs/reviewer-catalog.md',
                     'docs/model-routing.md', 'strict-mode/methodology.md',
                     'skills/codex-review/SKILL.md', 'skills/second-opinion/SKILL.md',
                     'skills/gh-review-certify-loop/SKILL.md', 'skills/strict-mode/SKILL.md'):
            with self.subTest(path=name):
                text = (ROOT / name).read_text()
                for retired in ('same-family review is not independent',
                                'Codex-on-Codex remains a same-family audit, not independent',
                                'Independent only when its provider',
                                'independent only when its model family differs',
                                'Do not call a Codex-on-Codex result independent'):
                    self.assertNotIn(retired, text)
                self.assertIn('family', text)
                self.assertTrue('separate' in text or 'separately' in text)

    def test_optional_review_guides_do_not_reintroduce_a_blanket_gate(self):
        catalog = (ROOT / 'docs/reviewer-catalog.md').read_text()
        runtime = (ROOT / 'strict-mode/README.md').read_text()
        self.assertNotIn('implementation review required by', catalog)
        self.assertNotIn('satisfies the fallback gate', runtime)
        self.assertIn('when useful or required', catalog)
        self.assertIn('no mandatory review gate', runtime)
