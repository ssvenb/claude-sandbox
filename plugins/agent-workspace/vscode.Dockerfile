# VS Code's own container (vscode.py): VS Code's standalone CLI, which downloads the server it
# serves on first use, and Python for vscode.py's settings. Nothing of the agent's, no credentials.
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git python3 \
    && rm -rf /var/lib/apt/lists/* \
    && arch=$(dpkg --print-architecture) \
    && case "$arch" in amd64) os=cli-alpine-x64 ;; arm64) os=cli-alpine-arm64 ;; armhf) os=cli-linux-armhf ;; \
         *) echo "no VS Code CLI for $arch" >&2; exit 1 ;; esac \
    && curl -fsSL "https://code.visualstudio.com/sha/download?build=stable&os=$os" | tar -xz -C /usr/local/bin code
