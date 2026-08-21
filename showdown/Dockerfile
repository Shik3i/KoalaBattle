FROM node:22.18.0-bookworm-slim

ARG SHOWDOWN_COMMIT=b22742debfdce6e640193384f5731b9030f9cb6e
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && git clone https://github.com/smogon/pokemon-showdown.git /opt/showdown \
    && cd /opt/showdown \
    && git checkout "${SHOWDOWN_COMMIT}" \
    && npm ci \
    && node build \
    && apt-get purge -y git \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/showdown
COPY showdown/config/config.js config/config.js
COPY showdown/config/custom-formats.js config/custom-formats.js
COPY showdown/config/custom-formats.js dist/config/custom-formats.js
COPY showdown/team-validator-server.js team-validator-server.js
EXPOSE 8000 8002
CMD ["node", "pokemon-showdown", "start", "--no-security", "8000"]
