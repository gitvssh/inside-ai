from inside_ai.wrap import plan


def test_claude_new_session_gets_fixed_id():
    p = plan("claude", ["--model", "opus"])
    assert p.view and p.mode == "new" and p.hint
    assert p.args == ["--session-id", p.hint, "--model", "opus"]


def test_claude_resume_and_continue():
    assert plan("claude", ["--resume", "abc"]).__dict__ | {} == {"view": True, "mode": "resume", "hint": "abc", "args": ["--resume", "abc"]}
    p = plan("claude", ["-c"])
    assert (p.mode, p.hint, p.args) == ("resume", None, ["-c"])
    p = plan("claude", ["--resume"])
    assert (p.mode, p.hint) == ("resume", None)
    p = plan("claude", ["--session-id", "x-y"])
    assert (p.mode, p.hint, p.args) == ("new", "x-y", ["--session-id", "x-y"])


def test_claude_prompt_argument_still_views():
    p = plan("claude", ["로그인 버그 고쳐줘"])
    assert p.view and p.args[-1] == "로그인 버그 고쳐줘"


def test_passthrough_and_info_flags():
    assert not plan("claude", ["mcp", "list"]).view
    assert not plan("codex", ["login"]).view
    assert not plan("agy", ["models"]).view
    assert not plan("claude", ["--version"]).view
    assert plan("claude", ["mcp", "list"]).args == ["mcp", "list"]


def test_codex_modes():
    assert (plan("codex", []).mode, plan("codex", []).hint) == ("new", None)
    p = plan("codex", ["resume", "01a0e34a"])
    assert (p.mode, p.hint) == ("resume", "01a0e34a")
    p = plan("codex", ["resume", "--last"])
    assert (p.mode, p.hint) == ("resume", None)
    assert plan("codex", ["exec", "hi"]).view


def test_agy_modes():
    p = plan("agy", ["--conversation", "c1"])
    assert (p.mode, p.hint) == ("resume", "c1")
    assert plan("agy", ["-c"]).mode == "resume"
    assert plan("agy", ["-p", "hi"]).mode == "new"


def test_hosts_tmux_only_outside_tmux_without_wt(monkeypatch):
    import sys

    from inside_ai import wrap

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(wrap, "wt_usable", lambda: False)
    monkeypatch.setattr(wrap.shutil, "which", lambda n: "/usr/bin/" + n)
    for k in ("TMUX", "IA_TMUX", "IA_NO_PANE"):
        monkeypatch.delenv(k, raising=False)
    assert wrap.should_host_tmux()
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    assert not wrap.should_host_tmux()
    monkeypatch.delenv("TMUX")
    monkeypatch.setenv("IA_TMUX", "0")
    assert not wrap.should_host_tmux()
    monkeypatch.delenv("IA_TMUX")
    monkeypatch.setattr(wrap, "wt_usable", lambda: True)
    assert not wrap.should_host_tmux()


def test_tmux_host_command_reruns_ia_inside(tmp_path):
    from inside_ai import wrap

    cmd = wrap.tmux_host_command("claude", ["-c", "a b"], "/w", tmp_path / "t.conf")
    assert cmd[:4] == ["tmux", "-L", "inside-ai", "-f"]
    assert "IA_HOSTED=1" in cmd and cmd[cmd.index("-c") + 1] == "/w"
    assert cmd[-1].endswith("-m inside_ai claude -c 'a b'")
