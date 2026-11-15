import os

from mustiefly_qt.helpers import dependencies as dep


def which_factory(present):
    return lambda name: f"/usr/bin/{name}" if name in present else None


def test_all_present_gives_no_message():
    deps = dep.check_dependencies(which_factory({"ffmpeg", "ffprobe", "node"}))
    assert all(d.found for d in deps) and dep.missing_message(deps) == ""


def test_ffmpeg_needs_ffprobe_too_and_message_explains_impact():
    deps = {d.name: d for d in dep.check_dependencies(which_factory({"ffmpeg"}))}
    assert not deps["FFmpeg"].found and not deps["Node.js"].found
    msg = dep.missing_message(list(deps.values()))
    assert "indirme" in msg and "YouTube" in msg and "winget" in msg


def test_only_missing_items_are_listed():
    msg = dep.missing_message(dep.check_dependencies(which_factory({"ffmpeg", "ffprobe"})))
    assert "Node.js" in msg and "FFmpeg" not in msg


def test_bundled_bin_is_prepended_once(tmp_path, monkeypatch):
    (tmp_path / "bin").mkdir()
    monkeypatch.setattr(dep, "bundled_bin_dir", lambda: str(tmp_path / "bin"))
    env = {"PATH": "/usr/bin"}
    assert dep.prepend_bundled_bin_to_path(env)
    assert env["PATH"].split(os.pathsep)[0] == str(tmp_path / "bin")
    dep.prepend_bundled_bin_to_path(env)
    assert env["PATH"].count(str(tmp_path / "bin")) == 1
    monkeypatch.setattr(dep, "bundled_bin_dir", lambda: str(tmp_path / "yok"))
    assert dep.prepend_bundled_bin_to_path({"PATH": "x"}) is False
