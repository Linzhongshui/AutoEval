ARG HARBOR_BASE
ARG ADAPTOR_IMAGE
FROM ${ADAPTOR_IMAGE} AS locked_adaptor
FROM ${HARBOR_BASE}

COPY --from=locked_adaptor /opt/autoeval-r13/site /opt/autoeval-r13/site
COPY deploy/r13-harbor-entrypoint.sh /usr/local/bin/autoeval-harbor-runner
COPY deploy/r13-harbor-adaptor.sh /opt/autoeval-r13/bin/autoeval-adaptor
RUN command -v docker && command -v dockerd \
    && chmod 0755 /usr/local/bin/autoeval-harbor-runner /opt/autoeval-r13/bin/autoeval-adaptor \
    && printf '%s\n' "import sys; sys.path.insert(0, '/opt/autoeval-r13/site')" \
       > "$(/opt/venvs/harbor/bin/python -c 'import site; print(site.getsitepackages()[0])')/autoeval-r13.pth"

ENV PATH=/opt/autoeval-r13/bin:/opt/venvs/harbor/bin:$PATH
ENV DOCKER_HOST=unix:///tmp/autoeval-docker.sock
RUN python3 -c "import mmengine, harbor, importlib.metadata as m, json; assert json.loads(m.distribution('autoeval-benchmark-adaptor').read_text('direct_url.json'))['vcs_info']['commit_id'] == '955089ab32ef696c231d628f5ad0d9da28f430c4'" \
    && autoeval-adaptor --help | grep -q -- '--preflight-only'

ENTRYPOINT ["/usr/local/bin/autoeval-harbor-runner"]
CMD []
