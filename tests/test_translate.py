import threading
import time

from inside_ai.cache import TranslationCache
from inside_ai.translate import TranslationService


class FakeBackend:
    id = "fake-v1"

    def __init__(self, delay=0.0, fail=False):
        self.calls = 0
        self.delay = delay
        self.fail = fail
        self.lock = threading.Lock()

    def translate(self, text, recent=None):
        with self.lock:
            self.calls += 1
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("boom")
        return f"KO:{text}"


def test_two_viewers_translate_once(tmp_path):
    db = tmp_path / "t.sqlite"
    backend = FakeBackend(delay=0.3)
    a = TranslationService(backend, TranslationCache(db))
    b = TranslationService(backend, TranslationCache(db))
    results = {}
    ts = [threading.Thread(target=lambda n=n, s=s: results.__setitem__(n, s.translate("hello"))) for n, s in (("a", a), ("b", b))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results == {"a": "KO:hello", "b": "KO:hello"}
    assert backend.calls == 1


def test_restart_reuses_cache(tmp_path):
    db = tmp_path / "t.sqlite"
    backend = FakeBackend()
    assert TranslationService(backend, TranslationCache(db)).translate("x") == "KO:x"
    again = TranslationService(backend, TranslationCache(db))
    assert again.translate("x") == "KO:x"
    assert backend.calls == 1 and again.calls == 0


def test_backend_change_separates_cache(tmp_path):
    db = tmp_path / "t.sqlite"
    b1, b2 = FakeBackend(), FakeBackend()
    b2.id = "fake-v2"
    TranslationService(b1, TranslationCache(db)).translate("x")
    TranslationService(b2, TranslationCache(db)).translate("x")
    assert (b1.calls, b2.calls) == (1, 1)


def test_failure_releases_claim_for_retry(tmp_path):
    db = tmp_path / "t.sqlite"
    bad = FakeBackend(fail=True)
    assert TranslationService(bad, TranslationCache(db)).translate("x") is None
    good = FakeBackend()
    good.id = bad.id
    assert TranslationService(good, TranslationCache(db)).translate("x") == "KO:x"


def test_stale_claim_is_taken_over(tmp_path):
    cache = TranslationCache(tmp_path / "t.sqlite", stale_after=0.1)
    assert cache.claim("k", "dead-window")
    assert not cache.claim("k", "other")
    time.sleep(0.15)
    assert cache.claim("k", "other")


def test_no_backend_shows_original():
    assert TranslationService(None).translate("x") is None
