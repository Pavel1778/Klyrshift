"""Autonomous QA engine for Klyrshift.

This package is a testing layer *on top of* the existing suite, never a
replacement for it. It drives the real daemon through the headless simulator
(:mod:`klyrshift.simulate`), checks independent invariants, classifies failures
and keeps a regression store.

The pieces are deliberately separate so each can be tested alone:

* :mod:`klyrshift.qa.scenario` -- the scenario model and its JSON format;
* :mod:`klyrshift.qa.invariants` -- independent correctness checks;
* :mod:`klyrshift.qa.executor` -- a safe runner over ``klyrshift.simulate``;
* :mod:`klyrshift.qa.generator` -- deterministic scenario generation;
* :mod:`klyrshift.qa.analyzer` -- failure minimisation and classification;
* :mod:`klyrshift.qa.store` -- the regression store;
* :mod:`klyrshift.qa.report` -- JSON and Markdown reporting;
* :mod:`klyrshift.qa.runner` -- orchestration.

The engine never runs a command an LLM proposes: scenarios are data, and only
the fixed step DSL of :mod:`klyrshift.simulate` is executed.
"""

from __future__ import annotations

__all__: list[str] = []
