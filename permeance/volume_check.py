from .contract import num
from .evidence import volume_checkpoints


def reconcile_volume(review, liquid):
    result = []
    for row, point in volume_checkpoints(review, liquid):
        observed = num(row.get('observed_ml'), '实测池量', 0, 1e4)
        tolerance = num(row.get('tolerance_ml'), '池量允差', 0, 1e4)
        delta = observed-point['after']
        result.append(dict(id=row['id'], sample=point['id'], time=point['time'], modeled=point['after'],
                           observed=observed, residual=delta, state='verified' if abs(delta) <= tolerance else 'residual',
                           evidence={'before': point['before'], 'removed': point['removed'], 'added': point['added']}))
    return result
