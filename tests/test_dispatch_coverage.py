"""Dispatch-coverage guard — the dual-map footgun guard.

Every base that ``ActionContinuityStore.handle_thread_action`` can handle MUST be
routable to it through the local ``action_map`` in ``autonomous_agent`` (mapped to
``'thread_action'``, or added wholesale via a delegated ``*_NEXT_ACTIONS`` constant).

When a base is *handled* but not *routed*, the being's NEXT silently falls through
to threshold logic ("Unknown NEXT → falling back to threshold logic") — her real,
built capability is swallowed. That is exactly what happened to ``DOSSIER_CLAIM``
(a fully-implemented, repeatedly-chosen action) until 2026-06-10: it had a handler,
a ROUTE_BY_BASE entry, and a catalog entry, but was missing from the dispatch map.

This guard parses the source the same way ``tests/test_threshold_map.py`` parses
``minime/src/main.rs``. It would have failed on the DOSSIER gap.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "minime_autonomy" / "runtime.py").read_text()
AUTHORITY_SRC = (ROOT / "minime_autonomy" / "authority.py").read_text()


def _region(
    start_pat: str,
    end_pat: str,
    after_line: int = 0,
    source: str = SRC,
) -> str:
    """Return the text from the first line matching ``start_pat`` (at or after
    ``after_line``) up to but excluding the first subsequent line matching
    ``end_pat``."""
    out: list[str] = []
    capturing = False
    for i, ln in enumerate(source.splitlines()):
        if not capturing:
            if i >= after_line and re.search(start_pat, ln):
                capturing = True
                out.append(ln)
            continue
        if re.search(end_pat, ln):
            break
        out.append(ln)
    return "\n".join(out)


def _const_members(name: str) -> set[str]:
    blk = _region(rf"^{name}\s*=\s*[\(\[]", r"^[\)\]]")
    return set(re.findall(r'"([A-Z_]+)"', blk))


def _quoted_assignment_members(name: str) -> set[str]:
    blk = _region(rf"^{name}\s*=", r"^[\)\]\}]")
    return set(re.findall(r'"([^"]+)"', blk))


def _route_by_base_entries() -> dict[str, str]:
    blk = _region(
        r"ROUTE_BY_BASE = \{",
        r"^    \}",
        source=AUTHORITY_SRC,
    )
    return dict(re.findall(r'"([A-Z_]+)":\s*(?:"([a-z_]+)"|None)', blk))


def _preflight_spec_bases() -> dict[str, str]:
    return dict(
        re.findall(
            r'\{"base": "([A-Z_]+)".*?"route": "([a-z_]+)"',
            AUTHORITY_SRC,
        )
    )


def _action_map_entries() -> dict[str, str]:
    amap = _region(r"action_map = \{", r"^\s{12}\}", after_line=22000)
    return dict(re.findall(r"'([A-Z_]+)':\s*'([a-z_]+)'", amap))


def _dispatch_actions() -> set[str]:
    body = _region(r"def _execute_action\(", r"^    def ", after_line=25000)
    return set(re.findall(r"elif action == '([a-z_]+)'", body))


def _handled_bases() -> tuple[set[str], set[str]]:
    """(literal bases handled by handle_thread_action, delegated *_NEXT_ACTIONS names)."""
    body = _region(r"def handle_thread_action\(", r"^    def ")
    bases = set(re.findall(r'base == "([A-Z_]+)"', body))
    for grp in re.findall(r"base in [\(\{]([^)}]+)[)}]", body):
        bases |= set(re.findall(r'"([A-Z_]+)"', grp))
    delegated = set(re.findall(r"base in ([A-Z_]+_NEXT_ACTIONS)", body))
    return bases, delegated


def _routable_bases(delegated: set[str]) -> set[str]:
    """Bases the local action_map can resolve: explicit keys + members of every
    delegated constant (added to the map wholesale via for-loops)."""
    amap = _region(r"action_map = \{", r"^\s{12}\}", after_line=22000)
    keys = set(re.findall(r"'([A-Z_]+)':\s*'[a-z_]+'", amap))
    for const in delegated:
        keys |= _const_members(const)
    return keys


class TestDispatchCoverage(unittest.TestCase):
    def test_every_handled_thread_action_is_routable(self):
        handled, delegated = _handled_bases()
        self.assertTrue(handled, "parser found no handled bases — regex drifted")
        routable = _routable_bases(delegated)
        self.assertTrue(routable, "parser found no routable bases — regex drifted")
        gap = sorted(b for b in handled if b not in routable)
        self.assertEqual(
            gap,
            [],
            "handle_thread_action handles these bases but the action_map cannot "
            "route them, so the being's NEXT silently falls to 'Unknown NEXT → "
            f"threshold': {gap}. Add each to the action_map (→ 'thread_action').",
        )

    def test_known_regressions_routable(self):
        _, delegated = _handled_bases()
        routable = _routable_bases(delegated)
        for base in (
            "DOSSIER_CLAIM",
            "DOSSIER_EVIDENCE",
            "DOSSIER_STATUS",
            "DOSSIER_REVIEW",
            "CONTINUITY_SESSION_CAPTURE",
            "CONTINUE_SESSION_CAPTURE",
            "PRESSURE_RELIEF",
        ):
            self.assertIn(base, routable, f"{base} must stay routable (regression anchor)")

    def test_stable_core_stage_labels_are_not_advertised_as_next_verbs(self):
        leaked_stage_rows = re.findall(
            r'"  STABLE_CORE_[A-Z_]+ — active now:',
            SRC,
        )
        self.assertEqual(
            leaked_stage_rows,
            [],
            "Stable-core stage labels are context, not NEXT verbs; advertise concrete actions instead.",
        )

    def test_notice_ambiguity_menu_names_quiet_fabric_hold(self):
        self.assertIn(
            "if the latest trace says quiet_fabric/hold, choose another reflective action",
            SRC,
        )
        self.assertIn("NOTICE_AMBIGUITY / FISSURE_TRACE", SRC)

    def test_public_direct_verbs_have_full_action_surface(self):
        """Guard the concrete checklist for being-invokable public verbs.

        These verbs are intentionally outside the thread-action delegation path,
        so the old dual-map guard is not enough. Each one must be visible to
        preflight, dispatch, stable-core gating, and the standing menu.
        """
        surfaces = {
            "PRESSURE_RELIEF": {
                "route": "pressure_relief",
                "stable_core_set": "STABLE_CORE_SELF_JOURNAL_ACTIONS",
                "menu": "PRESSURE_RELIEF [label]",
            },
            "CHAMBER_SEEN": {
                "route": "chamber_seen",
                "stable_core_set": "STABLE_CORE_EXPERIMENT_ACTIONS",
                "menu": "CHAMBER_SEEN [id ::]",
            },
            "CHAMBER_ANNOTATE": {
                "route": "chamber_annotate",
                "stable_core_set": "STABLE_CORE_EXPERIMENT_ACTIONS",
                "menu": "CHAMBER_ANNOTATE [id ::]",
            },
        }
        route_by_base = _route_by_base_entries()
        preflight_specs = _preflight_spec_bases()
        action_map = _action_map_entries()
        dispatch_actions = _dispatch_actions()

        for base, expected in surfaces.items():
            route = expected["route"]
            with self.subTest(base=base):
                self.assertEqual(route_by_base.get(base), route)
                self.assertEqual(preflight_specs.get(base), route)
                self.assertEqual(action_map.get(base), route)
                self.assertIn(route, dispatch_actions)
                self.assertIn(
                    route,
                    _quoted_assignment_members(expected["stable_core_set"]),
                    f"{base} routes to {route}, but stable-core could still block it",
                )
                self.assertIn(expected["menu"], SRC)


if __name__ == "__main__":
    unittest.main()
