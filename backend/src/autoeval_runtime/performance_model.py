"""Container-only AISBench client. Keep credentials out of dumped model configs."""

import os

from ais_bench.benchmark.models import VLLMCustomAPIChat


class PerformanceChat(VLLMCustomAPIChat):
    def __init__(self, **kwargs):
        kwargs["api_key"] = os.environ["AE_PERFORMANCE_KEY"]
        super().__init__(**kwargs)
