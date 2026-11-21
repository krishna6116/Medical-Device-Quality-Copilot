"""The key writer keeps other .env lines, never prints the key, and .env stays git-ignored."""

from mdqc import setup_env


def test_set_values_updates_and_keeps_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nOPENFDA_API_KEY=old\nOTHER=1\n", encoding="utf-8")
    setup_env.set_values(env, {"OPENFDA_API_KEY": "new", "ANTHROPIC_API_KEY": "a"})
    assert env.read_text(encoding="utf-8") == "# comment\nOPENFDA_API_KEY=new\nOTHER=1\nANTHROPIC_API_KEY=a\n"


def test_main_hides_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup_env.getpass, "getpass", lambda prompt: "SECRET123")
    monkeypatch.setattr(setup_env, "check_openfda_key", lambda key: "works")
    setup_env.main(anthropic=False, path=tmp_path / ".env")
    out = capsys.readouterr().out
    assert "SECRET123" not in out and "OPENFDA_API_KEY" in out
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "OPENFDA_API_KEY=SECRET123\n"


def test_main_skip_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_env.getpass, "getpass", lambda prompt: "")
    setup_env.main(anthropic=True, path=tmp_path / ".env")
    assert not (tmp_path / ".env").exists()
