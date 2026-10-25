"""No model calls: preregistration and isolation-contract tests."""
from collections import Counter
from scripts.reflection_comparison import OPTIONS, SEEDS, PROTECTED_PORTS, schedule, sandbox_profile


def test_fixed_sample_counterbalanced_and_identical_repeats():
    jobs = schedule()
    assert len(jobs) == 24 and jobs == schedule()
    assert len({job["blind_id"] for job in jobs}) == 24
    assert Counter(job["cell"] for job in jobs) == {0: 6, 1: 6, 2: 6, 3: 6}
    for cell in range(4):
        rows = [job for job in jobs if job["cell"] == cell]
        assert sorted(job["seed"] for job in rows) == sorted(SEEDS + [SEEDS[0]])
        assert sum(job["repeat"] for job in rows) == 1
    assert OPTIONS == {"temperature": .7, "top_p": .95, "num_predict": 4096, "num_ctx": 65536}


def test_no_live_endpoints_and_no_writes_outside_owned_output(tmp_path):
    profile = sandbox_profile(tmp_path, tmp_path / "assets", 12345)
    assert {7878, 7879, 7880, 7881, 7900, 7901, 7902, 11434} <= set(PROTECTED_PORTS)
    assert "(deny network*)" in profile
    assert "(deny file-write*)" in profile
    for port in PROTECTED_PORTS:
        assert f'localhost:{port}' in profile
    assert '(subpath "/Users/v/other")' in profile
