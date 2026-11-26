ARG AISBENCH_BASE
FROM ${AISBENCH_BASE}

RUN if test -e /benchmark; then mv /benchmark /benchmark.base; fi
COPY aisbench/ /benchmark/
COPY adaptor/ /opt/autoeval-r13/adaptor/
RUN test "$(git -C /benchmark rev-parse HEAD)" = 525ed1779f50a8ac068b8638771f633a151e769f \
    && test "$(git -C /opt/autoeval-r13/adaptor rev-parse HEAD)" = 955089ab32ef696c231d628f5ad0d9da28f430c4 \
    && python3 -m pip install --no-index --no-deps --no-build-isolation --target /opt/autoeval-r13/site \
       'git+file:///opt/autoeval-r13/adaptor@955089ab32ef696c231d628f5ad0d9da28f430c4'

RUN printf '%s\n' "import sys; sys.path[0:0] = ['/opt/autoeval-r13/site', '/benchmark']" \
    > "$(python3 -c 'import site; print(site.getsitepackages()[0])')/autoeval-r13.pth"
RUN python3 -c "import importlib.metadata as m, json; assert json.loads(m.distribution('autoeval-benchmark-adaptor').read_text('direct_url.json'))['vcs_info']['commit_id'] == '955089ab32ef696c231d628f5ad0d9da28f430c4'"
ENV PATH=/opt/autoeval-r13/site/bin:$PATH
