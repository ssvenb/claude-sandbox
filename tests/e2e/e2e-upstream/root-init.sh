# shellcheck shell=sh
# Test fixture, enabled ahead of upstream-proxy: plays the HOST half run.sh would start — an
# upstream that echoes each request back, and proxy.py in front of it holding the credential.
python3 "$PLUGIN_DIR/echo.py" >/var/log/e2e-echo.log 2>&1 &
mkdir -p /run/upstream-proxy
printf '[{"name": "api", "port": 8099, "upstream": "http://127.0.0.1:9000",
          "auth": {"type": "bearer", "valueEnv": "E2E_UPSTREAM_KEY"}}]' >/tmp/e2e-routes.json
E2E_UPSTREAM_KEY=upstream-secret python3 /opt/plugins/upstream-proxy/host/proxy.py \
  /tmp/e2e-routes.json /run/upstream-proxy >/var/log/e2e-proxy.log 2>&1 &
for _ in $(seq 50); do [ -S /run/upstream-proxy/api.sock ] && break; sleep 0.1; done
