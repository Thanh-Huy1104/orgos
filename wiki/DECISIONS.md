
## metrics_v2 conventions (established sprint L10-01)
- Metric dataclass fields, in order: (name, value, unit). frozen=True.
- Metric.name style: snake_case only (e.g. 'mean_takt', not 'MeanTakt' or 'mean-takt').
- Invalid-input policy for metric functions: RETURN None, do NOT raise. This applies to every metrics_v2/*.py function.
- Every new metric function goes in its own module under orgos/agile/metrics_v2/.
