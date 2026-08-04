# Disposable dev sandbox for agent work — see sandbox/README.md.
# TS + Python toolchains per AGENTS.md; everything else stays lean.
FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git build-essential \
    python3 python3-venv python3-pip pipx \
    jq less nano procps \
    && rm -rf /var/lib/apt/lists/*

COPY --chmod=755 entrypoint.sh /usr/local/bin/sandbox-entrypoint

# Non-root: a runaway rm/chmod hits permissions before it hits anything real.
# /work is created and chowned explicitly — WORKDIR after USER can leave it
# root-owned (moby#36677), which would break the entrypoint's clone.
RUN useradd -m -s /bin/bash agent && mkdir -p /work && chown agent:agent /work
USER agent
WORKDIR /work

# Identity is sandbox-local. core.pager cat: the service allocates a TTY, so git would otherwise page
# into less and hang non-interactive agent commands.
RUN git config --global user.name "sandbox-agent" \
    && git config --global user.email "sandbox@localhost" \
    && git config --global init.defaultBranch main \
    && git config --global core.pager cat

ENTRYPOINT ["sandbox-entrypoint"]
CMD ["bash"]
