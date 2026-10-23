"""The simulated Alexa+ experience: routing rules, the full story through them, and the HTTP surface."""

import httpx
import pytest

from conftest import INTERNET
from test_mcp_e2e import _serve
from tripwire.server import create_app
from tripwire.service import Tripwire
from tripwire.simulator import Simulator
from tripwire.store import SqliteStore

SOFA = "We're getting the grey sofa because it's comfy. We'd return it if the price drops below $300."


@pytest.fixture
def sim():
    return Simulator()


@pytest.mark.parametrize("said,tool", [
    ("Alexa, " + INTERNET, "record_decision"),
    (SOFA, "record_decision"),
    ("I decided on the blue couch because it's soft", "record_decision"),
    ("tell Tripwire we're going with the standing desk because it's on sale", "record_decision"),
    ("The provider just raised our internet price to $55", "report_fact"),
    ("The provider is getting a new modem", "report_fact"),       # no 'we/I' subject: a fact, not a decision
    ("Alexa, the sofa is on sale, the price dropped to $250", "report_fact"),
    ("What should I look at?", "whats_on_watch"),
    ("what's on watch", "whats_on_watch"),
    ("Why did we pick that internet plan?", "why_did_we"),
    ("remind me why we chose the sofa", "why_did_we"),
    ("Keep it", "resolve_decision"),
    ("change it to the 500 megabit plan", "resolve_decision"),
    ("stop watching", "resolve_decision"),
])
def test_routing_table(svc, sim, said, tool):
    assert sim.route(svc, said)[0] == tool


def test_full_story_through_the_simulator(svc, sim):
    say = lambda t: sim.say(svc, t)  # noqa: E731
    assert say("Alexa, " + INTERNET)["result"]["ok"]
    assert say(SOFA)["result"]["ok"]
    assert say("The provider emailed that our internet price goes to $48 next month")["result"]["close_to_limit"] == ["internet plan"]
    trip = say("The provider just raised our internet price to $55")
    assert trip["tool"] == "report_fact" and trip["result"]["tripped"] == ["internet plan"]
    assert "internet plan" in say("What should I look at?")["spoken"]
    assert "cheapest" in say("Why did we pick that internet plan?")["spoken"]
    kept = say("Keep it, but move the price limit to $60.")
    assert kept["tool"] == "resolve_decision" and kept["args"]["new_limit"] == 60.0 and "price above $60" in kept["spoken"]
    assert say("The sofa is on sale. The price dropped to $250.")["result"]["tripped"] == ["grey sofa"]


def test_resolve_with_two_flagged_decisions_asks_which_one(svc, sim):
    sim.say(svc, INTERNET); sim.say(svc, SOFA)
    sim.say(svc, "internet price to $55"); sim.say(svc, "sofa price dropped to $250")
    out = sim.say(svc, "Keep it")
    assert out["result"]["ok"] is False and "Which one" in out["spoken"]
    assert sim.say(svc, "Keep the sofa")["result"]["ok"] is True


def test_resolve_with_nothing_flagged_is_a_polite_miss(svc, sim):
    assert sim.say(svc, "Keep it")["result"]["ok"] is False


def test_false_positive_decision_phrase_never_crashes(svc, sim):
    out = sim.say(svc, "We're getting new neighbours")
    assert isinstance(out["spoken"], str) and "Traceback" not in out["spoken"]


def test_skipping_days_moves_the_simulated_clock(sim):
    d0 = sim.today()
    assert sim.advance(7) == 7 and (sim.today() - d0).days == 7
    assert sim.advance(10_000) == 372  # one call is clamped to 365 days
    assert sim.advance(-5) == 372 and sim.advance(0) == 372


def test_checkin_date_fires_after_skipping_time(store):
    sim = Simulator()
    svc = Tripwire(store, "s", sim.today)
    sim.say(svc, INTERNET + " Check back in three months.")
    assert "All quiet" in sim.say(svc, "what should I look at")["spoken"]
    for _ in range(14):
        sim.advance(7)
    assert "check-in date has arrived" in sim.say(svc, "what should I look at")["spoken"]


# ------------------------------------------------------------------ HTTP surface
@pytest.fixture
def web(monkeypatch, clock):
    monkeypatch.delenv("TRIPWIRE_TOKEN", raising=False)
    monkeypatch.setenv("TRIPWIRE_SIM", "1")
    yield from _serve(create_app(Tripwire(SqliteStore(":memory:"), "web", clock)))


def test_simulator_page_is_labelled_as_simulated(web):
    r = httpx.get(f"{web}/sim")
    assert r.status_code == 200 and "Simulated Alexa+" in r.text and "Not a real Alexa device" in r.text


def test_say_state_and_advance_endpoints(web):
    j = {"Content-Type": "application/json"}
    r = httpx.post(f"{web}/sim/say", json={"utterance": INTERNET}, headers=j).json()
    assert r["tool"] == "record_decision" and r["result"]["ok"]
    r = httpx.post(f"{web}/sim/say", json={"utterance": "internet price to $55"}).json()
    assert r["result"]["tripped"] == ["internet plan"]
    st = httpx.get(f"{web}/sim/state").json()
    assert st["decisions"][0]["status"] == "revisit" and st["decisions"][0]["tripwires"][0]["obs"] == 55.0
    assert httpx.post(f"{web}/sim/advance", json={"days": 7}).json() == {"ok": True, "skipped_days": 7}


def test_bad_requests_are_rejected_cleanly(web):
    assert httpx.post(f"{web}/sim/say", content="utterance=hi", headers={"Content-Type": "text/plain"}).status_code == 415  # CSRF guard
    assert httpx.post(f"{web}/sim/say", json={"utterance": ""}).status_code == 400
    assert httpx.post(f"{web}/sim/say", json={"utterance": 5}).status_code == 400
    assert httpx.post(f"{web}/sim/say", json=[1, 2]).status_code == 415
    assert httpx.post(f"{web}/sim/advance", json={"days": "x"}).status_code == 400
    assert httpx.post(f"{web}/sim/advance", json={"days": True}).status_code == 400
    assert httpx.post(f"{web}/sim/say", content=b"{broken", headers={"Content-Type": "application/json"}).status_code == 415
    assert httpx.get(f"{web}/healthz").status_code == 200


def test_simulator_is_off_by_default(monkeypatch, clock):
    monkeypatch.delenv("TRIPWIRE_SIM", raising=False)
    monkeypatch.delenv("TRIPWIRE_TOKEN", raising=False)
    gen = _serve(create_app(Tripwire(SqliteStore(":memory:"), "off", clock)))
    base = next(gen)
    assert httpx.get(f"{base}/sim").status_code == 404 and httpx.post(f"{base}/sim/say", json={"utterance": "hi"}).status_code in (404, 405)


def test_simulator_endpoints_respect_the_bearer_token(monkeypatch, clock):
    monkeypatch.setenv("TRIPWIRE_SIM", "1")
    monkeypatch.setenv("TRIPWIRE_TOKEN", "tok")
    base = next(_serve(create_app(Tripwire(SqliteStore(":memory:"), "auth", clock))))
    assert httpx.get(f"{base}/sim").status_code == 401 and httpx.get(f"{base}/sim/state").status_code == 401
    assert httpx.get(f"{base}/sim", headers={"Authorization": "Bearer tok"}).status_code == 200


def test_ui_never_injects_untrusted_text_as_html():
    from tripwire.simhtml import SIM_HTML

    assert "innerHTML" not in SIM_HTML and "textContent" in SIM_HTML  # XSS guard: everything dynamic uses textContent
