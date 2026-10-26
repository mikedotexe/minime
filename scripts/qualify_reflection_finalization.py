#!/usr/bin/env python3
"""Qualify frozen Minime sources and exact synthetic pending-work handoff offline."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


HANDOFF = r'''
import hashlib, json, pathlib, runpy, sys
source, tests, fixture, output = map(pathlib.Path, sys.argv[1:5])
operation = sys.argv[5]
sys.path[:0] = [str(source), str(tests)]
runpy.run_path(str(tests / 'tests/conftest.py'))
def deny_network(event, args):
    if event == 'socket.connect':
        raise RuntimeError('synthetic handoff forbids network')
sys.addaudithook(deny_network)
import autonomous_agent as aa
from tests.test_maintenance_next import agent, checkpoint, start_once
from minime_autonomy import maintenance_next as m
assert pathlib.Path(aa.__spec__.origin) == source / 'minime_autonomy/runtime.py'
aa.WORKSPACE_DIR, aa.RUNTIME_DIR, aa.BASE_DIR = fixture, fixture / 'runtime', fixture
aa.DB_PATH = fixture / 'fixture.db'
fixture.mkdir(parents=True, exist_ok=True)
value = agent(fixture)
value._agent_inputs_at_start = {'minime_autonomy/runtime.py': hashlib.sha256((source / 'minime_autonomy/runtime.py').read_bytes()).hexdigest()}
value._query_llm = lambda *a, **k: (_ for _ in ()).throw(AssertionError('unrequested inference'))
path = fixture / 'sovereignty_state.json'
if operation == 'seal':
    value._pending_next_action = 'WRITE REVISE "NEXT: REST" synthetic \u00e9'
    value._pending_next_selection_id = 'synthetic-exact-selection'
    value._pending_choice_envelope_v1 = {'exact': 'synthetic retained context'}
    checkpoint(value)
    m.seal(value)
else:
    before = path.read_bytes()
    saved = json.loads(before)
    start_once(value)
    assert path.read_bytes() == before
    assert value._pending_next_action == saved['pending_next_action']
    assert value._pending_next_selection_id == saved['pending_next_selection_id']
    assert value._pending_choice_envelope_v1 == saved['choice_envelope_v1']
    assert value._next_handoff_restore['scheduling_authorized'] is False
    assert value._next_handoff_restore['pending_present'] is True
    assert m.history(str(path))[0][-1]['body']['kind'] == 'restored'
output.write_text(json.dumps(dict(operation=operation,
    state_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    pending_sha256=hashlib.sha256(m.canonical(m.pending(json.loads(path.read_bytes())))).hexdigest(),
    source_inputs=value._agent_inputs_at_start, generation_requested=False), sort_keys=True))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reconciliation", "tests", "astrid", "helper", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.astrid / "scripts"))
    from qualify_retained_accounts_release import frozen_tests, test_inventory
    from qualify_geometry_release import inventory, freeze_python, require, sha, write_json
    binding = json.loads(args.reconciliation.read_bytes())
    source = Path(binding["snapshot_root"])
    previous = Path(binding["bindings"]["canonical_root"])
    expected, old = binding["selected_inputs"], binding["canonical_inputs"]
    require(inventory(source) == expected and inventory(previous) == old, "source drift")
    require({p for p in expected.keys() | old.keys() if expected.get(p) != old.get(p)} ==
            {"minime_autonomy/reflection_publication.py", "minime_autonomy/runtime.py"}, "unexpected runtime overlay")
    inputs = {str(p): sha(p) for p in (Path(__file__), args.reconciliation, args.helper,
              args.astrid / "scripts/qualify_retained_accounts_release.py",
              args.astrid / "scripts/qualify_geometry_release.py")}
    tests = test_inventory(args.tests)
    args.out.mkdir(mode=0o700)
    try:
        tested = frozen_tests(source, args.tests, args.astrid, args.helper, args.out)
        old_source = args.out / "old-source"
        require(freeze_python(previous, old_source) == old, "old source drift")
        dependencies = [p for p in sys.path if p and Path(p).name in {"site-packages", "dist-packages"}]
        env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=os.pathsep.join(dependencies))
        results = {}
        for direction, first, second in (("old-to-new", old_source, source), ("new-to-old", source, old_source)):
            for operation, runtime in (("seal", first), ("restore", second)):
                name = direction + "-" + operation
                output = args.out / (name + ".json")
                result = subprocess.run([sys.executable, "-B", "-c", HANDOFF, str(runtime), str(args.tests),
                    str(args.out / direction), str(output), operation], env=env, cwd=args.out,
                    capture_output=True, text=True, timeout=60)
                (args.out / (name + ".stdout")).write_text(result.stdout)
                (args.out / (name + ".stderr")).write_text(result.stderr)
                require(result.returncode == 0, "handoff probe failed: " + name)
                results[name] = json.loads(output.read_bytes())
            for key in ("state_sha256", "pending_sha256"):
                require(results[direction + "-seal"][key] == results[direction + "-restore"][key], "pending work changed")
        require(inventory(source) == expected and inventory(previous) == old, "final source drift")
        require(tests == test_inventory(args.tests), "test source drift")
        require(inputs == {p: sha(Path(p)) for p in inputs}, "qualification input drift")
        write_json(args.out / "qualification.json", dict(schema="reflection_finalization_qualification_v1",
            status="passed", selected_inputs=expected, previous_inputs=old, tests=tested, test_inputs=tests,
            handoff=results, implementation_inputs=inputs, activation_performed=False,
            limits="Synthetic stores only; no live recovery or deployment authority."))
        print(json.dumps({"status": "passed", "receipt": str(args.out / "qualification.json")}))
    except Exception as error:
        write_json(args.out / "failure.json", {"error": str(error), "activation_performed": False})
        raise


if __name__ == "__main__":
    main()
