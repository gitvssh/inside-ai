import io
import os
import subprocess
import time

import pytest
from conftest import claude_rec, write_jsonl

from inside_ai import links, view
from inside_ai.cache import TranslationCache
from inside_ai.sources import ClaudeSource
from inside_ai.translate import TranslationService


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("INSIDE_AI_STATE_DIR", str(tmp_path / "state"))


class Upper:
    id = "upper-v1"

    def translate(self, text, recent=None):
        if text == "boom":
            raise RuntimeError("HTTP 503")
        time.sleep(0.05)
        return "번역:" + text


def test_view_translates_in_order_and_marks_failures(roots, tmp_path):
    proc = subprocess.Popen(["sleep", "2"])
    link = links.Link.create("claude", "/w", proc.pid, "new", "S1", [])
    link.save()
    write_jsonl(
        roots["claude"] / "-w" / "S1.jsonl",
        [claude_rec(f"u{i}", [{"type": "thinking", "thinking": t}]) for i, t in enumerate(["one", "boom", "three"])],
    )
    out = io.StringIO()
    service = TranslationService(Upper(), TranslationCache(tmp_path / "t.sqlite"))
    view.run(link.id, service=service, out=out, interval=0.1, close_wait=0, source=ClaudeSource(roots["claude"]))
    proc.wait()
    text = out.getvalue()
    assert "<클로드>의 생각은?" in text and "한국어 번역" in text
    assert text.index("번역:one") < text.index("boom") < text.index("번역:three")
    assert "원문(번역 실패)" in text


def test_renderer_passes_recent_context(roots, tmp_path):
    seen = []

    class Rec:
        id = "rec-v1"

        def translate(self, text, recent=None):
            seen.append(list(recent or []))
            return "번역:" + text

    proc = subprocess.Popen(["sleep", "1.5"])
    link = links.Link.create("claude", "/w", proc.pid, "new", "S2", [])
    link.save()
    write_jsonl(roots["claude"] / "-w" / "S2.jsonl",
                [claude_rec(f"u{i}", [{"type": "thinking", "thinking": t}]) for i, t in enumerate(["a", "b", "c"])])
    view.run(link.id, service=TranslationService(Rec(), TranslationCache(tmp_path / "r.sqlite")), out=io.StringIO(),
             interval=0.1, close_wait=0, source=ClaudeSource(roots["claude"]))
    proc.wait()
    assert seen == [[], [("a", "번역:a")], [("a", "번역:a"), ("b", "번역:b")]]
