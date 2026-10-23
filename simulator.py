"""Simulated Alexa+ experience.

Real Alexa+ routes what a person says to MCP tools using its own AI. When Alexa+ access is unavailable, the hackathon
rules allow a *simulated* Alexa+ experience. This module is that simulation's routing layer: it maps a spoken sentence to
the **same service calls the MCP tools make** (record_decision, report_fact, ...), using simple, inspectable rules.

It is a stand-in for Alexa+'s routing, NOT for Tripwire's logic: every state change still goes through ``Tripwire``.
Enable the web UI with ``TRIPWIRE_SIM=1`` and open ``/sim``.
"""

from __future__ import annotations

import re
import threading
from datetime import date, timedelta
from typing import Any

from . import ai
from .service import Tripwire, default_today

_WAKE = re.compile(r"^(?:(?:hey |ok |okay )?alexa)[,.!:]?\s+|^(?:(?:tell|ask) tripwire(?: to| that)?[,:]?\s+)", re.I)
_DECISION = re.compile(
    r"\b(?:we|i)(?:'re|'m| are| am| will|'ll)?\s+(?:going with|going to (?:get|buy|take|use)|getting|buying|picking|choosing|"
    r"chose|picked|decided on|decided to (?:get|buy|take|use)|will (?:get|take|use))\b", re.I)
_WHY = re.compile(r"^(?:why (?:did|do|would) (?:we|i)|why'd (?:we|i)|remind me why (?:we|i))\s*(.*)$", re.I)
_WATCH = re.compile(r"what (?:should i|do i need to|do we need to) look at|what'?s on (?:the )?watch|what are you watching|"
                    r"what needs (?:my |our )?attention|anything (?:i|we) should (?:know|look at)", re.I)
_RESOLVE = re.compile(r"^(keep|change|close|drop|stop watching)\b\s*(.*)$", re.I)
_LIMIT = re.compile(r"(?:move|raise|lower|set|change|adjust|bump)\b.*?\blimit\b.*?\bto\s+\$?(\d[\d,]*(?:\.\d+)?)", re.I)


class Simulator:
    """Holds the simulated clock (so the UI can 'skip days') and routes sentences to service calls."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.offset_days = 0

    def today(self) -> date:
        return default_today() + timedelta(days=self.offset_days)

    def advance(self, days: int) -> int:
        with self._lock:
            self.offset_days = max(0, min(3650, self.offset_days + max(0, min(int(days), 365))))
            return self.offset_days

    # ------------------------------------------------------------------ routing
    def route(self, svc: Tripwire, utterance: str) -> tuple[str, dict[str, Any]]:
        text = ai._clean_text(utterance)
        text = _WAKE.sub("", text).strip()
        m = _WHY.match(text)
        if m:
            return "why_did_we", {"topic": (m.group(1) or text).strip(" ?.")}
        if _WATCH.search(text):
            return "whats_on_watch", {}
        m = _RESOLVE.match(text)
        if m and not _DECISION.search(text):
            return self._resolve_args(svc, m.group(1).lower(), m.group(2), text)
        if _DECISION.search(text):
            return "record_decision", {"what_was_said": text}
        return "report_fact", {"statement": text}

    @staticmethod
    def _resolve_args(svc: Tripwire, verb: str, rest: str, full: str) -> tuple[str, dict[str, Any]]:
        outcome = {"keep": "keep", "change": "change", "close": "close", "drop": "close", "stop watching": "close"}[verb]
        args: dict[str, Any] = {"outcome": outcome}
        lim = _LIMIT.search(full)
        if lim and outcome == "keep":
            args["new_limit"] = float(lim.group(1).replace(",", ""))
        note = re.sub(r"\b(it|that|this|one|but|and|please)\b", "", _LIMIT.sub("", rest), flags=re.I).strip(" ,.;")
        live = [d for d in svc._all() if d["status"] in ("active", "revisit")]
        flagged = [d for d in live if d["status"] == "revisit"]
        named = [d for d in live if ai.tokens(note) & ai.tokens(d["title"] + " " + d["choice"])]
        pool = named or flagged
        if len(pool) == 1:
            args["topic"] = pool[0]["title"]
        elif len(pool) > 1:  # "keep it" with several candidates: ask, never guess
            args["ambiguous"] = [d["title"] for d in pool]
            args["topic"] = ""
        else:
            args["topic"] = note or ""
        if outcome == "change" and note and not named:
            args["note"] = note
        elif outcome == "keep" and note and not named:
            args["note"] = note
        return "resolve_decision", args

    def say(self, svc: Tripwire, utterance: str) -> dict[str, Any]:
        tool, args = self.route(svc, utterance)
        fn = getattr(svc, tool)
        if tool == "resolve_decision":
            if args.get("ambiguous"):
                names = " or ".join(args["ambiguous"])
                result = {"ok": False, "ambiguous": True, "spoken": f"Which one do you mean: {names}?"}
            elif not args["topic"]:
                result = {"ok": False, "spoken": "Nothing needs a decision right now. Tell me which one you mean."}
            else:
                result = fn(args["topic"], args["outcome"], args.get("note"), args.get("new_limit"), None)
        else:
            result = fn(**args)
        return {"tool": tool, "args": args, "result": result, "spoken": result["spoken"]}

    def state(self, svc: Tripwire) -> dict[str, Any]:
        out = []
        for d in svc._all():
            if d["status"] in ("closed",):
                continue
            out.append({"title": d["title"], "status": d["status"], "choice": d["choice"], "tripwires": [
                {"d": t["description"], "op": t.get("op"), "v": t.get("value"), "state": t["state"], "obs": t.get("observed")}
                for t in d["tripwires"]]})
        return {"date": svc._today().strftime("%b %-d, %Y"), "decisions": out, "skipped_days": self.offset_days}
