"""Platform tracks (1.4.0): Android / iOS / Roblox / Web pick prompts, repo template and launch audit."""
from pathlib import Path

import pytest

from studio import audit
from studio.prompts import PLATFORMS, load_role
from studio.worker import run_until_idle
from conftest import pending


def test_platform_track_is_added_to_every_agent_prompt(studio):
    p = studio.paths.prompts
    assert "Platform track: Roblox" in load_role(p, "engineer", "roblox")
    assert "Platform track: iOS" in load_role(p, "qa", "ios")
    assert "Platform track" not in load_role(p, "engineer", "")
    assert "Platform track" not in load_role(p, "engineer", "switch")
    for name in PLATFORMS:  # shipped defaults exist for every platform
        assert (Path(audit.__file__).parent / "prompt_defaults" / "platforms" / f"{name}.md").exists()


def test_unknown_platform_is_refused(studio):
    with pytest.raises(ValueError):
        studio.new_game("a racing game", "Racer", "switch")


def test_roblox_game_gets_rojo_repo_and_roblox_prompts(studio, fake):
    gid = studio.new_game("A cozy obby with pets", "Pet Obby", "roblox")
    assert studio.game(gid)["platform"] == "roblox"
    run_until_idle(studio)
    assert "Platform: roblox" in fake.calls[-1].prompt and "Platform track: Roblox" in fake.calls[-1].prompt
    studio.approve(pending(studio, 1)[0]["id"])
    repo = Path(studio.game(gid)["repo_path"])
    assert (repo / "default.project.json").exists() and not (repo / "project.godot").exists()
    assert "{{" not in (repo / "src" / "server" / "Main.server.luau").read_text()


def test_roblox_audit_uses_roblox_rules_not_play_rules(studio, tmp_path):
    repo = tmp_path / "r"
    import shutil
    shutil.copytree(Path(audit.__file__).parent / "templates" / "roblox", repo)
    items = audit.deterministic_checks(repo, "pet-obby", studio.db.settings(), "", 0, None, "roblox")
    checks = " ".join(i["check"] for i in items)
    assert "Robux" in checks and "TextService" in checks
    assert "Target SDK" not in checks and "Play Console" not in checks and "intro" not in checks
    assert any("Google Fonts" in i["check"] and i["verdict"] == "PASS" for i in items)


def test_web_audit_flags_cdn_font(studio, tmp_path):
    repo = tmp_path / "w"
    repo.mkdir()
    (repo / "index.html").write_text('<link href="https://fonts.googleapis.com/css2?family=Inter">')
    items = audit.deterministic_checks(repo, "w", studio.db.settings(), "", 0, None, "web")
    hit = [i for i in items if "Google Fonts" in i["check"]][0]
    assert hit["verdict"] == "FAIL" and hit["blocker"]
