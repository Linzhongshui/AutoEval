ARG HARBOR_BASE
FROM ${HARBOR_BASE}

COPY deploy/r13-harbor-entrypoint.sh /usr/local/bin/autoeval-harbor-runner
RUN command -v docker && command -v dockerd && chmod 0755 /usr/local/bin/autoeval-harbor-runner
ENV DOCKER_HOST=unix:///tmp/autoeval-docker.sock
ENTRYPOINT ["/usr/local/bin/autoeval-harbor-runner"]
CMD []
