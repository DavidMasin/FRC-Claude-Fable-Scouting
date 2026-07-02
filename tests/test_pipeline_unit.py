import numpy as np

from frcscout.pipeline import SceneGuard


def _frame(value):
    return np.full((360, 640, 3), value, np.uint8)


def test_scene_guard_stable_footage():
    guard = SceneGuard(threshold=40)
    assert guard.stable(_frame(100))
    assert guard.stable(_frame(102))  # normal motion/noise
    assert guard.stable(_frame(99))


def test_scene_guard_cut_and_cooldown():
    guard = SceneGuard(threshold=40, cooldown=2)
    assert guard.stable(_frame(100))
    assert not guard.stable(_frame(220))   # hard cut
    assert not guard.stable(_frame(220))   # cooldown 1
    assert not guard.stable(_frame(221))   # cooldown 2
    assert guard.stable(_frame(221))       # stabilized


def test_scene_guard_recovers_after_replay():
    guard = SceneGuard(threshold=40, cooldown=1)
    assert guard.stable(_frame(100))
    assert not guard.stable(_frame(240))   # cut to replay
    assert not guard.stable(_frame(240))   # cooldown
    assert guard.stable(_frame(240))       # replay itself is 'stable' footage
    assert not guard.stable(_frame(100))   # cut back to live
    assert not guard.stable(_frame(100))
    assert guard.stable(_frame(100))
