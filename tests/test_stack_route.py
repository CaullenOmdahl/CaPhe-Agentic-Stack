import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from tools.stack_route import resolve_route, route_digest, RouteError


def route(model='incumbent', config='baseline', effort='medium', tier='standard'):
    return {'model': model, 'config': config, 'effort': effort, 'service_tier': tier}


def approval(config='candidate', task_class='implementation', approved=True):
    selected = {'candidate': route('candidate', 'candidate', 'high'),
                'cheap': route('cheap', 'cheap'),
                'approved-review': route('reviewer', 'approved-review', 'high')}[config]
    return {'approved': approved, 'config': config, 'task_class': task_class, 'route_digest': route_digest(selected),
            'evidence': {'id': 'evaluation-1', 'source_digest': 'e' * 64, 'acceptance_digest': 'f' * 64}}


def contract(**overrides):
    value = {'schema_version': 1, 'source': {'repository': 'example/project', 'revision': 'a' * 40, 'snapshot_digest': 'b' * 64},
             'goal': 'Implement the scoped fix', 'acceptance': ['Behavior regression passes'],
             'allowed_writes': ['tools/'], 'exclusions': ['config/'], 'lane': 'scoped-behavior',
             'canon_refs': ['docs/canon.md'], 'required_checks': ['unit'],
             'output_limits': {'max_bytes': 8000, 'max_words': 500},
             'repair_budget': {'max_repairs': 1}, 'escalation': 'parent',
             'task_class': 'implementation', 'parent_id': 'parent-1', 'children': [], 'max_workers': 2}
    value.update(overrides)
    return value


def capabilities():
    return {'models': {name: {'available': True, 'efforts': ['medium', 'high'], 'service_tiers': ['standard']}
                       for name in ('incumbent', 'candidate', 'reviewer', 'cheap')}}


def policy():
    return {'incumbent': route(), 'routes': {'implementation': {
        'route': route('candidate', 'candidate', 'high'), 'promotion': approval()}}}


class StackRouteTests(unittest.TestCase):
    def test_approved_bound_route_resolves_explicit_configuration(self):
        result = resolve_route(contract(), capabilities(), policy())
        self.assertEqual(result['status'], 'resolved')
        self.assertEqual(result['model'], 'candidate')
        self.assertEqual(result['config'], 'candidate')

    def test_unapproved_candidate_uses_validated_incumbent(self):
        settings = policy()
        settings['routes']['implementation']['promotion']['approved'] = False
        result = resolve_route(contract(), capabilities(), settings)
        self.assertEqual((result['status'], result['model']), ('fallback', 'incumbent'))
        caps = capabilities()
        caps['models']['incumbent']['available'] = False
        self.assertEqual(resolve_route(contract(), caps, settings)['status'], 'unsupported')

    def test_missing_promotion_falls_back_and_mutated_route_cannot_reuse_approval(self):
        settings = policy()
        del settings['routes']['implementation']['promotion']
        self.assertEqual(resolve_route(contract(), capabilities(), settings)['model'], 'incumbent')
        settings = policy()
        settings['routes']['implementation']['route']['model'] = 'cheap'
        with self.assertRaises(RouteError):
            resolve_route(contract(), capabilities(), settings)

    def test_missing_service_capabilities_never_default_to_requested_tier(self):
        caps = capabilities()
        del caps['models']['incumbent']['service_tiers']
        with self.assertRaises(RouteError):
            resolve_route(contract(), caps, {'incumbent': route(), 'routes': {}})

    def test_truthy_approval_and_unbound_promotion_are_rejected(self):
        for change in ({'approved': 'signed'}, {'config': 'different'}, {'task_class': 'review'}):
            settings = policy()
            settings['routes']['implementation']['promotion'].update(change)
            with self.subTest(change=change), self.assertRaises(RouteError):
                resolve_route(contract(), capabilities(), settings)
        settings = policy()
        settings['routes']['implementation']['promotion'] = 'approved'
        with self.assertRaises(RouteError):
            resolve_route(contract(), capabilities(), settings)

    def test_canonical_review_cannot_inherit_generic_cheap_medium_route(self):
        settings = policy()
        settings['routes']['review'] = {'route': route('cheap', 'cheap'), 'promotion': approval('cheap', 'review')}
        request = contract(task_class='review', canonical_review_role=True)
        self.assertEqual(resolve_route(request, capabilities(), settings)['status'], 'unsupported')
        settings['reviewer_route'] = {'route': route('reviewer', 'approved-review', 'high'),
                                      'approval': approval('approved-review', 'review')}
        result = resolve_route(request, capabilities(), settings)
        self.assertEqual(result['model'], 'reviewer')
        self.assertEqual(result['config'], 'approved-review')

    def test_closed_typed_contract_rejects_bad_nested_values(self):
        invalid = [contract(goal=42), contract(acceptance='tests'), contract(allowed_writes=['../escape']),
                   contract(allowed_writes=['/absolute']), contract(extra='hidden'),
                   contract(source={'revision': 'abc', 'snapshot_digest': 'x'}),
                   contract(output_limits={'max_bytes': True, 'max_words': 20}),
                   contract(repair_budget={'max_repairs': -1}), contract(repair_budget={'max_repairs': 2}),
                   contract(canonical_review_role='yes'), contract(required_checks=[])]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(RouteError):
                resolve_route(request, capabilities(), policy())

    def test_protected_path_components_reject_case_aliases(self):
        for path in ('.GIT/config', '.SsH/key'):
            with self.subTest(path=path), self.assertRaises(RouteError):
                resolve_route(contract(allowed_writes=[path]), capabilities(), policy())
        self.assertEqual(resolve_route(contract(allowed_writes=['Git/config']), capabilities(), policy())['status'], 'resolved')

    def test_nested_delegation_and_concurrency_limits_rejected(self):
        child = {'task_id': 'worker-1', 'goal': 'Check a thing', 'acceptance': ['Report evidence'], 'allowed_writes': []}
        for request in (contract(max_workers=3), contract(children=[child], max_workers=0),
                        contract(children=[{**child, 'children': [child]}])):
            with self.assertRaises(RouteError):
                resolve_route(request, capabilities(), policy())

    def test_worker_write_scopes_must_be_disjoint_including_ancestor_paths(self):
        def worker(identifier, writes):
            return {'task_id': identifier, 'goal': 'Implement scoped change',
                    'acceptance': ['Unit check'], 'allowed_writes': writes}
        for first, second in ((['tools/shared.py'], ['tools/shared.py']),
                              (['tools/'], ['tools/shared.py']),
                              (['tools/nested/file.py'], ['tools/nested/'])):
            request = contract(children=[worker('one', first), worker('two', second)])
            with self.subTest(first=first, second=second), self.assertRaises(RouteError):
                resolve_route(request, capabilities(), policy())
        for first, second in ((['tools/one.py'], ['tools/two.py']), ([], ['tools/one.py']), ([], [])):
            request = contract(children=[worker('one', first), worker('two', second)])
            self.assertEqual(resolve_route(request, capabilities(), policy())['status'], 'resolved')

    def test_write_and_exclusion_scopes_cannot_overlap_in_either_direction(self):
        for allowed, excluded in ((['src'], ['src/secrets']), (['src/secrets'], ['src']),
                                  (['src/secrets'], ['src/secrets'])):
            request = contract(allowed_writes=allowed, exclusions=excluded)
            with self.subTest(allowed=allowed, excluded=excluded), self.assertRaises(RouteError):
                resolve_route(request, capabilities(), policy())
        request = contract(allowed_writes=['src/public'], exclusions=['src/secrets'])
        self.assertEqual(resolve_route(request, capabilities(), policy())['status'], 'resolved')

    def test_scope_comparisons_casefold_without_collapsing_components(self):
        for allowed, excluded in ((['Secrets/config'], ['secrets']),
                                  (['secrets'], ['Secrets/config'])):
            request = contract(allowed_writes=allowed, exclusions=excluded)
            with self.subTest(allowed=allowed, excluded=excluded), self.assertRaises(RouteError):
                resolve_route(request, capabilities(), policy())

        request = contract(allowed_writes=['src/foo'], exclusions=['src/foobar'])
        self.assertEqual(resolve_route(request, capabilities(), policy())['status'], 'resolved')

        def worker(identifier, writes):
            return {'task_id': identifier, 'goal': 'Implement scoped change',
                    'acceptance': ['Unit check'], 'allowed_writes': writes}
        request = contract(children=[worker('one', ['tools/Secrets']),
                                     worker('two', ['tools/secrets/config'])])
        with self.assertRaises(RouteError):
            resolve_route(request, capabilities(), policy())
        request = contract(children=[worker('one', ['tools/foo']), worker('two', ['tools/foobar'])])
        self.assertEqual(resolve_route(request, capabilities(), policy())['status'], 'resolved')
        request = contract(children=[worker('one', ['TOOLS/file.py'])])
        self.assertEqual(resolve_route(request, capabilities(), policy())['status'], 'resolved')
        self.assertEqual(resolve_route(contract(), capabilities(), policy())['status'], 'resolved')

    def test_cli_roundtrip_and_schema_parity(self):
        import tools.stack_route as module
        self.assertEqual(json.loads(Path('schemas/delegation-contract-v1.json').read_text()), module.CONTRACT_SCHEMA)
        reviewer = {'incumbent': route(), 'routes': {}, 'reviewer_route': {
            'route': route('reviewer', 'approved-review', 'high'),
            'approval': approval('approved-review', 'review')}}
        for request, settings, expected_model in (
                (contract(), policy(), 'candidate'),
                (contract(task_class='review', canonical_review_role=True), reviewer, 'reviewer')):
            with self.subTest(expected_model=expected_model):
                process = self.run_cli(json.dumps({
                    'contract': request, 'capabilities': capabilities(), 'policy': settings}))
                self.assertEqual(process.returncode, 0, process.stderr)
                result = json.loads(process.stdout)
                self.assertEqual(result['status'], 'resolved')
                self.assertEqual(result['model'], expected_model)

    def run_cli(self, encoded):
        return subprocess.run([sys.executable,
            str(Path(__file__).resolve().parents[1] / 'tools/stack_route.py')],
            input=encoded, text=True, capture_output=True, timeout=10)

    def assert_duplicate_rejected(self, encoded):
        process = self.run_cli(encoded)
        self.assertEqual(process.returncode, 2)
        result = json.loads(process.stdout)
        self.assertEqual(result['status'], 'unsupported')
        self.assertIn('duplicate keys', result['reason'])
        self.assertNotIn('model', result)
        self.assertNotIn('Traceback', process.stderr)

    def test_cli_rejects_duplicate_top_level_policy_keys_in_both_orders(self):
        approved = policy()
        denied = copy.deepcopy(approved)
        denied['routes']['implementation']['promotion']['approved'] = False
        prefix = json.dumps({'contract': contract(), 'capabilities': capabilities()})[:-1]
        for first, second in ((approved, denied), (denied, approved)):
            with self.subTest(first_approved=first['routes']['implementation']['promotion']['approved']):
                encoded = prefix + ', "policy": ' + json.dumps(first) + ', "policy": ' + json.dumps(second) + '}'
                self.assert_duplicate_rejected(encoded)

    def test_cli_rejects_duplicate_nested_promotion_and_reviewer_approvals(self):
        reviewer = {'incumbent': route(), 'routes': {}, 'reviewer_route': {
            'route': route('reviewer', 'approved-review', 'high'),
            'approval': approval('approved-review', 'review')}}
        for request, settings in ((contract(), policy()),
                (contract(task_class='review', canonical_review_role=True), reviewer)):
            for first, second in ((True, False), (False, True)):
                with self.subTest(task_class=request['task_class'], first_approved=first):
                    encoded = json.dumps({'contract': request, 'capabilities': capabilities(), 'policy': settings})
                    encoded = encoded.replace('"approved": true',
                        '"approved": ' + json.dumps(first) + ', "approved": ' + json.dumps(second))
                    self.assert_duplicate_rejected(encoded)


if __name__ == '__main__':
    unittest.main()
