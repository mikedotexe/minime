"""Exercise isolation decisions directly; never attempt an actual live operation."""

import pytest

import autonomous_agent as aa
from minime_autonomy import envelope_registry as er
from tests.conftest import LIVE_ROOTS, _deny_live_writes


def test_peer_shared_research_and_review_defaults_are_private():
    paths = [aa.ASTRID_BRIDGE_INBOX_DIR, aa.ASTRID_BRIDGE_INBOX_PATH,
             aa.ASTRID_SELF_STUDY_REVIEW_DIR, aa.SHARED_INVESTIGATION_DIR,
             aa.CORRESPONDENCE_LEDGER_PATH, aa.PHASE_TRANSITIONS_LEDGER_PATH,
             aa.MIKE_RESEARCH_ROOT, aa.AUTORESEARCH_ROOT,
             aa.AutonomousAgent.SHARED_COLLAB_DIR, aa.AutonomousAgent.ASTRID_INBOX_DIR,
             aa.AutonomousAgent.BRIDGE_INBOX,
             aa._latest_lived_term_review_path.__defaults__[0],
             aa.render_lived_term_bridge_action.__kwdefaults__["review_root"],
             aa.render_regulator_map_bridge_action.__kwdefaults__["review_root"],
             er.DEFAULT_REGISTRY_PATH, er.load_registry.__defaults__[0],
             er.envelope_for.__kwdefaults__["path"], er.channel_range_for.__kwdefaults__["path"]]
    assert all(path.is_relative_to(aa.BASE_DIR) for path in paths)
    assert all(not path.is_relative_to(root) for path in paths for root in LIVE_ROOTS)


@pytest.mark.parametrize("root", ["shared", "research", "autoresearch"])
def test_guard_rejects_external_live_writes_without_performing_them(root):
    with pytest.raises(RuntimeError, match="live write"):
        _deny_live_writes("open", (f"/Users/v/other/{root}/synthetic-should-not-exist", "w", 0))


@pytest.mark.parametrize("port", [3040, 7881])
def test_guard_rejects_extra_live_endpoints_without_connecting(port):
    with pytest.raises(RuntimeError, match="live runtime connection"):
        _deny_live_writes("socket.connect", (None, ("127.0.0.1", port)))


@pytest.mark.parametrize("command,cwd", [
    (["python3", "helper.py"], "/Users/v/other/autoresearch"),
    (["python3", "/Users/v/other/autoresearch/scripts/helper.py"], None),
])
def test_guard_rejects_live_subprocess_targets_without_launching(command, cwd):
    with pytest.raises(RuntimeError, match="subprocess against live"):
        _deny_live_writes("subprocess.Popen", ("python3", command, cwd, None))


def test_guard_allows_synthetic_subprocess_paths(tmp_path):
    _deny_live_writes("subprocess.Popen", ("python3", ["python3", str(tmp_path / "fixture.py")], str(tmp_path), None))
