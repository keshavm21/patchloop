# The sandbox image: Python 3.12 plus pinned, hash-checked pytest, pytest-timeout and numpy.
# The base is pinned by its multi-arch digest, so arm64 and amd64 builds start from the same tag.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

COPY sandbox-requirements.txt /runner/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /runner/requirements.txt \
    && groupadd --gid 10001 sandbox \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin sandbox

COPY run_tests.sh /runner/run_tests.sh
USER 10001:10001
ENTRYPOINT ["/bin/sh", "/runner/run_tests.sh"]
