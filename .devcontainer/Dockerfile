FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        git-lfs \
        build-essential \
        libgl1 \
        libglib2.0-0 \
        python3 \
        python3.10-dev \
        python3-pip \
        python3-venv \
        sudo \
        nodejs \
    && ln -s /usr/bin/python3 /usr/local/bin/python \
    && ln -s /usr/bin/pip3 /usr/local/bin/pip \
    && useradd --create-home --shell /bin/bash vscode \
    && echo "vscode ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/vscode \
    && chmod 0440 /etc/sudoers.d/vscode \
    && python3 -m venv /opt/venv \
    && chown -R vscode:vscode /opt/venv \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:${PATH}

WORKDIR /workspace/memgpt_demo

USER vscode
