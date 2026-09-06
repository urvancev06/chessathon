"""Local web app for playing, watching and inspecting the Mikhail LeTal engine.

Run with ``python -m tools.webapp.server`` from the repository root. Nothing in this package ships
in the submission zip; it speaks to agents only through ``harness.sandbox``, exactly as the platform
does, so it works unchanged for the starter's random mover, the baselines, and the real engine.
"""
