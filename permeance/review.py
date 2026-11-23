from .evidence import blank_footprint, draw_exposure, threshold_review
from .steady_state import analyze_steady_state
from .volume_check import reconcile_volume
from .windows import rate_agreement, read_windows, window_delta


def analyze_review(review, model, facts, outputs):
    result = dict(windows=window_delta(model, facts['bounds'], read_windows(review, model)),
                  agreement=rate_agreement(outputs['flux'], outputs['increment']),
                  draws=draw_exposure(model, facts['bounds']),
                  blank_footprint=blank_footprint(facts['blank'], facts['bounds']),
                  threshold_review=threshold_review(outputs['crossing'], outputs['mass']),
                  checkpoints=reconcile_volume(review, facts['liquid']),
                  zero_draw_gaps=zero_draw_gaps(model, facts, outputs))
    if 'steady_state' in review:
        result['steady_state'] = analyze_steady_state(review, outputs['mass'], model['threshold'])
    return result


def zero_draw_gaps(model, facts, outputs):
    """Distinguish a missing assay that affects this snapshot from one that poisons later draws."""
    result = []
    for sample, bound, point in zip(model['samples'], facts['bounds'], outputs['mass'], strict=True):
        if bound['lo'] is not None:
            continue
        result.append(dict(id=sample['id'], time=sample['time'], removed=sample['removed'],
                           state='carried' if sample['removed'] else 'local',
                           evidence={'concentration': bound['state'], 'mass': point['state'], 'blank': bound['evidence']}))
    return result
