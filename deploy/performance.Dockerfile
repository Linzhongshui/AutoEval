# Build context: a fresh checkout of AISBench at the revision below (including .git).
FROM ghcr.io/aisbench/aisbench_benchmark@sha256:2a4fe997203efa99e8089814b9628f15839902bf2ab6273d197bdbab82406858
WORKDIR /
RUN rm -rf /benchmark
COPY . /benchmark/
WORKDIR /benchmark
RUN test "$(git rev-parse HEAD)" = "842d0dd6b87a3a8620b6931aafa1b9089d91485f" \
    && git -c core.autocrlf=false archive -o /tmp/aisbench-source.tar HEAD ais_bench requirements \
    && tar -xf /tmp/aisbench-source.tar && rm /tmp/aisbench-source.tar \
    && git diff --quiet HEAD -- ais_bench requirements \
    && /opt/venvs/agentx113/bin/python -c "import importlib.metadata as m; assert m.version('agentx-harness') == '1.0.13'" \
    && /opt/venvs/agentx113/bin/pip check \
    && /opt/venvs/agentx113/bin/agentx --help >/dev/null \
    && python3 -m ais_bench.benchmark.cli.main --help >/dev/null
ENV HF_HUB_OFFLINE=1
