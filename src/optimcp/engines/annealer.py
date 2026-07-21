"""Heuristic engine: D-Wave simulated annealing over a QUBO.

This is a genuinely different method from CP-SAT: the decision is expressed as a
:class:`dimod.ConstrainedQuadraticModel`, converted to an unconstrained QUBO with
``dimod.cqm_to_bqm`` (which adds the penalty terms and binary slack variables for
us - validated D-Wave code, not ours), and sampled with the classical
``dwave-samplers`` simulated-annealing sampler.

A sampler can and does return constraint-violating samples, so this adapter only
proposes the best sample that OptiMCP's own verifier accepts as feasible. The
orchestrator verifies again; being wrong here can only cost a contribution, never
produce an unchecked answer.

Unsupported shapes (currently the ``!=`` operator, which a CQM cannot express)
degrade to "unavailable" so the orchestrator falls back to CP-SAT.
"""

from __future__ import annotations

from optimcp.engines.common import EngineOutcome
from optimcp.spec import DecisionSpec
from optimcp.verify import verify_assignment

_NUM_READS = 200
_SEED = 1234


def solve_annealer(spec: DecisionSpec, *, num_reads: int = _NUM_READS, seed: int = _SEED) -> EngineOutcome:
    """Sample ``spec`` with simulated annealing, return best verified-feasible. Never raises."""
    if any(c.op == "!=" for c in spec.constraints):
        return EngineOutcome(available=False, detail="annealer: '!=' constraints unsupported")
    try:
        import dimod
        from dwave.samplers import SimulatedAnnealingSampler
    except Exception as exc:  # pragma: no cover - only when dwave-samplers missing
        return EngineOutcome(available=False, detail=f"dwave-samplers unavailable: {exc}")
    try:
        return _sample(spec, dimod, SimulatedAnnealingSampler, num_reads, seed)
    except Exception as exc:  # pragma: no cover - defensive
        return EngineOutcome(available=False, detail=f"annealer error: {type(exc).__name__}: {exc}")


def _sample(spec, dimod, Sampler, num_reads, seed) -> EngineOutcome:
    symbols = {}
    for var in spec.variables:
        if var.kind == "binary":
            symbols[var.name] = dimod.Binary(var.name)
        else:
            symbols[var.name] = dimod.Integer(
                var.name, lower_bound=int(var.lb), upper_bound=int(var.ub)
            )

    def expr(terms):
        total = None
        for term in terms:
            piece = None
            for name in term.vars:
                piece = symbols[name] if piece is None else piece * symbols[name]
            piece = term.coeff * piece
            total = piece if total is None else total + piece
        return total

    cqm = dimod.ConstrainedQuadraticModel()
    if spec.objective.terms:
        objective = expr(spec.objective.terms)
        cqm.set_objective(-objective if spec.objective.sense == "maximize" else objective)

    for i, constraint in enumerate(spec.constraints):
        lhs = expr(constraint.terms)
        rhs = constraint.rhs
        op = constraint.op
        label = constraint.name or f"c{i}"
        if op == "<":
            lhs, op, rhs = lhs, "<=", rhs - 1
        elif op == ">":
            op, rhs = ">=", rhs + 1
        if op == "<=":
            cqm.add_constraint(lhs <= rhs, label=label)
        elif op == ">=":
            cqm.add_constraint(lhs >= rhs, label=label)
        elif op == "==":
            cqm.add_constraint(lhs == rhs, label=label)

    bqm, invert = dimod.cqm_to_bqm(cqm)
    sampleset = Sampler().sample(bqm, num_reads=num_reads, seed=seed)

    best_assignment = None
    best_objective = None
    maximize = spec.objective.sense == "maximize"
    for sample, _energy in sampleset.data(["sample", "energy"], sorted_by="energy"):
        original = invert(sample)
        try:
            assignment = {v.name: int(round(float(original[v.name]))) for v in spec.variables}
        except (KeyError, TypeError, ValueError):
            continue
        cert = verify_assignment(spec, assignment)
        if not cert.all_satisfied:
            continue
        value = cert.objective_value
        if best_objective is None or (value > best_objective if maximize else value < best_objective):
            best_assignment, best_objective = assignment, value

    if best_assignment is None:
        return EngineOutcome(detail="annealer: no verified-feasible sample")
    return EngineOutcome(assignment=best_assignment, detail="annealer: simulated annealing")
