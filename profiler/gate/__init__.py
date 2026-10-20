"""The Window B leakage gate.

Lives under `profiler/` rather than beside `fixtures/` because
`infra/profiler/Dockerfile` copies only `src` and `profiler` into the sealed image, and this
code has to be inside that image to run with `--network=none`.
"""
