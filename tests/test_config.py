import pytest

from frcscout.config import load_config

MINIMAL = """
match_key: "2026isde1_qm14"
apis:
  tba:
    auth_key: "from-file"
  nexus:
    api_key: ""
"""


def test_load_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL)
    config = load_config(path)
    assert config["match_key"] == "2026isde1_qm14"
    assert config["apis"]["tba"]["auth_key"] == "from-file"


def test_env_fills_empty_secrets(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL)
    monkeypatch.setenv("NEXUS_API_KEY", "from-env")
    monkeypatch.setenv("TBA_AUTH_KEY", "should-not-win")
    config = load_config(path)
    assert config["apis"]["nexus"]["api_key"] == "from-env"
    # file value takes precedence over the environment
    assert config["apis"]["tba"]["auth_key"] == "from-file"


def test_env_creates_missing_sections(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("match_key: x\n")
    monkeypatch.setenv("FRC_EVENTS_USERNAME", "u")
    monkeypatch.setenv("FRC_EVENTS_AUTH_TOKEN", "t")
    config = load_config(path)
    assert config["apis"]["frc_events"] == {"username": "u", "auth_token": "t"}


def test_missing_file_message(tmp_path):
    with pytest.raises(FileNotFoundError, match="config.example.yaml"):
        load_config(tmp_path / "nope.yaml")


def test_cli_schedule_fetch_json(tmp_path, monkeypatch, capsys):
    from frcscout.cli import main
    from frcscout.schedule.model import lineup_from_alliances
    import frcscout.schedule

    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL)
    lineup = lineup_from_alliances("2026isde1_qm14", "2026isde1", "tba",
                                   [1690, 2630, 3339], [5987, 1577, 4590])
    monkeypatch.setattr(frcscout.schedule, "fetch_lineup",
                        lambda match_key, config, providers: lineup)
    assert main(["schedule", "fetch", "--config", str(path), "--json"]) == 0
    out = capsys.readouterr().out
    assert '"source": "tba"' in out and '"match_key": "2026isde1_qm14"' in out
