FROM autoeval/deepswe:offline-e968d1b-20261126
COPY wheels/ /opt/autoeval/miniswe-wheels/
RUN cd /opt/autoeval/miniswe-wheels && echo '5365624582ff0bd98eb8ccf3b5ef91479df349f8f90173c28b87f1b1919c209e  sha256sums' | sha256sum -c - && sha256sum --quiet -c sha256sums
COPY patch_runner.py /opt/autoeval/patch_runner.py
COPY offline_agent.py /opt/venvs/harbor/lib/python3.12/site-packages/harbor/agents/installed/autoeval_offline.py
RUN set -eu; factory=/opt/venvs/harbor/lib/python3.12/site-packages/harbor/agents/factory.py; \
    grep -Fq 'harbor.agents.installed.mini_swe_agent:MiniSweAgent' "$factory"; \
    sed -i 's/harbor.agents.installed.mini_swe_agent:MiniSweAgent/harbor.agents.installed.autoeval_offline:OfflineMiniSweAgent/' "$factory"; \
    python /opt/autoeval/patch_runner.py /benchmark/ais_bench/benchmark/runners/harbor_runner.py
