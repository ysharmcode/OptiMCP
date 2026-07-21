"""Pluggable optimization engines.

OptiMCP does not implement its own solver. It orchestrates two mature,
independently-validated open-source engines and then verifies their answers:

* ``cpsat``   - Google OR-Tools CP-SAT: an exact constraint/integer solver that
  proves optimality and infeasibility.
* ``annealer`` - D-Wave ``dwave-samplers`` simulated annealing over a QUBO built
  with ``dimod``: a quantum-inspired heuristic sampler.

Each adapter returns an :class:`EngineOutcome` and never raises; a missing
library or an unsupported problem shape degrades gracefully so the orchestrator
can still use the other engine.
"""

from optimcp.engines.common import EngineOutcome

__all__ = ["EngineOutcome"]
