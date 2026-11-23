from .blank_correction import GAP_STATES
from .mass_assessment import flux_between, threshold_crossings
from .mass_ledger import accumulate_mass


def decide(model, facts):
    points = accumulate_mass(model, facts['bounds'])
    flux = flux_between(points)
    crossings = threshold_crossings(points, model['threshold'])
    revisit=[dict(id=p['id'],time=p['time'],state=p['state'],evidence=p['evidence']) for p in points if p['state'] in ('missing','unresolved',*GAP_STATES)]
    return dict(facts,mass=points,flux=flux,crossing=crossings,revisit=revisit)
