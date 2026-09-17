"""Named metric series: never reinterpret a loss as a validation score."""
import math


def point_value(point, name):
    value = (point.get('metrics') or {}).get(name)
    if value is None and name == 'loss':
        value = point.get('loss', point.get('current_loss'))
    if value is None and point.get('metric_name') == name:
        value = point.get('current_iou', point.get('iou'))
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def series(run, name):
    values = {}
    for point in run.get('history', []):
        value = point_value(point, name)
        if value is not None:
            values[float(point.get('epoch', 0))] = value
    return sorted(values.items())


def latest_metric(run, name):
    value = point_value(run, name)
    if value is not None:
        return value, (run.get('metric_epochs') or {}).get(name, run.get('epoch'))
    points = series(run, name)
    return (points[-1][1], points[-1][0]) if points else (None, None)


def best_metric(run, name):
    value = (run.get('best_metrics') or {}).get(name)
    if value is not None:
        return value
    values = [v for _, v in series(run, name)]
    current, _ = latest_metric(run, name)
    if current is not None:
        values.append(current)
    return (min(values) if name == 'loss' else max(values)) if values else None
