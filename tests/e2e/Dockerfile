# A test layer over a built sandbox image; tests/e2e/test_image.py builds and boots it.
ARG IMAGE
FROM ${IMAGE}

# Stand-ins, ahead of the real binaries on PATH: the agent itself, gh (no real GitHub) and the
# NetBird client (no real mesh).
COPY tests/e2e/bin/ /usr/local/sbin/
# Plays the host half of upstream-proxy, which run.sh would start on the host.
COPY tests/e2e/e2e-upstream /opt/plugins/e2e-upstream
COPY tests/e2e/fixtures.sh /tmp/fixtures.sh
RUN chmod 755 /usr/local/sbin/* && sh /tmp/fixtures.sh && rm /tmp/fixtures.sh
