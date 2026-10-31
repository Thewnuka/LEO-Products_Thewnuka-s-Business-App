"""
Simple bar charts drawn as inline SVG (no JavaScript library, prints well, works offline).

bar_chart() returns the geometry for templates/finance/partials/_bar_chart.html, or None
when there is nothing to draw. Values below zero are drawn as zero.
"""
from decimal import Decimal

HEIGHT, TOP, BOTTOM, LEFT = 220, 12, 44, 52
MAX_LABELS = 16


def _nice_max(value):
    if value <= 0:
        return Decimal(1)
    magnitude = Decimal(10) ** (len(str(int(value))) - 1)
    for step in (1, 2, 2.5, 5, 10):
        top = magnitude * Decimal(str(step))
        if top >= value:
            return top
    return magnitude * 10


def bar_chart(labels, series, stacked=False):
    """labels: [str]; series: [(name, [values], css_class)]."""
    if not labels or not series:
        return None
    clean = [(name, [max(Decimal(v or 0), Decimal(0)) for v in values], css) for name, values, css in series]
    if stacked:
        peak = max(sum(vals[i] for _n, vals, _c in clean) for i in range(len(labels)))
    else:
        peak = max(max(vals) for _n, vals, _c in clean)
    if peak <= 0:
        return None
    top = _nice_max(peak)
    slot = max(28, min(64, 640 // len(labels)))
    width = LEFT + slot * len(labels) + 8
    plot = HEIGHT - TOP - BOTTOM
    per_slot = 1 if stacked else len(clean)
    bar_w = max(6, (slot - 8) / per_slot)
    bars, label_marks = [], []
    every = max(1, -(-len(labels) // MAX_LABELS))
    for i, label in enumerate(labels):
        x0 = LEFT + i * slot + 4
        base = HEIGHT - BOTTOM
        for j, (name, vals, css) in enumerate(clean):
            h = float(vals[i] / top) * plot
            x = x0 if stacked else x0 + j * bar_w
            y = base - h
            if h > 0:
                bars.append({"x": round(x, 1), "y": round(y, 1), "w": round(bar_w - (0 if stacked else 1), 1),
                             "h": round(h, 1), "css": css, "title": f"{label} · {name}: LKR {vals[i]:,.2f}"})
            if stacked:
                base = y
        if i % every == 0:
            text = label if len(label) <= 14 else label[:13] + "…"
            label_marks.append({"x": round(x0 + (slot - 8) / 2, 1), "text": text})
    grid = [{"y": round(HEIGHT - BOTTOM - plot * f, 1), "value": f"{top * Decimal(str(f)):,.0f}"} for f in (0.5, 1)]
    return {"width": width, "height": HEIGHT, "bars": bars, "labels": label_marks, "grid": grid, "label_y": HEIGHT - BOTTOM + 16,
            "legend": [(name, css) for name, _v, css in clean], "plot_left": LEFT, "plot_right": width - 4, "axis_x": LEFT - 4,
            "baseline": HEIGHT - BOTTOM}
