ARG BASE_IMAGE=mcr.microsoft.com/devcontainers/base:ubuntu-24.04@sha256:d94c97dd9cacf183d0a6fd12a8e87b526e9e928307674ae9c94139139c0c6eae
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# A dated, signed Ubuntu snapshot makes package resolution immutable. The
# snapshot's Release metadata naturally ages, so Valid-Until is disabled only
# for this digest-pinned image build while signature, TLS peer, and host
# verification remain mandatory.
RUN rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources \
    && printf '%s\n' \
        'Types: deb' \
        'URIs: https://snapshot.ubuntu.com/ubuntu/20260719T000000Z/' \
        'Suites: noble noble-updates noble-security' \
        'Components: main restricted universe multiverse' \
        'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg' \
        'Check-Valid-Until: no' \
        'Check-Date: yes' \
        > /etc/apt/sources.list.d/ubuntu.sources \
    && printf '%s\n' \
        'Acquire::https::Verify-Peer "true";' \
        'Acquire::https::Verify-Host "true";' \
        'Acquire::AllowInsecureRepositories "false";' \
        'APT::Get::AllowUnauthenticated "false";' \
        > /etc/apt/apt.conf.d/99untangle-snapshot-security

# Keep repository tool versions under mise/bootstrap control. This image only
# provides the host bootstrap utilities, native build support, and the exact
# Ubuntu libraries required by Playwright 1.61 Chromium.
RUN apt-get -o Acquire::AllowInsecureRepositories=false update \
    && apt-get -o APT::Get::AllowUnauthenticated=false install --yes --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        fonts-freefont-ttf \
        fonts-ipafont-gothic \
        fonts-liberation \
        fonts-noto-color-emoji \
        fonts-tlwg-loma-otf \
        fonts-unifont \
        fonts-wqy-zenhei \
        git \
        libasound2t64 \
        libatk-bridge2.0-0t64 \
        libatk1.0-0t64 \
        libatspi2.0-0t64 \
        libcairo2 \
        libcups2t64 \
        libdbus-1-3 \
        libdrm2 \
        libfontconfig1 \
        libfreetype6 \
        libgbm1 \
        libglib2.0-0t64 \
        libnspr4 \
        libnss3 \
        libpango-1.0-0 \
        libx11-6 \
        libxcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxkbcommon0 \
        libxrandr2 \
        python3 \
        tar \
        unzip \
        xfonts-cyrillic \
        xfonts-scalable \
        xz-utils \
        zip \
    && rm -rf /var/lib/apt/lists/*

USER vscode
WORKDIR /workspaces

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD bash -c 'source /etc/os-release && [[ "${ID}" == ubuntu && "${VERSION_ID}" == 24.04 ]] && [[ "$(id -u)" -ne 0 ]]'
