# Discord-Bot von WhisperNotes (siehe docker/compose.yml, Profil "discord")
FROM node:22-bookworm-slim
LABEL org.opencontainers.image.title="WhisperNotes Discord bot" \
      org.opencontainers.image.source="https://github.com/Poldion/WhisperNotes" \
      org.opencontainers.image.licenses="MIT"
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY *.mjs ./
RUN mkdir -p /app/recordings && chown node /app/recordings
USER node
ENV RECORDINGS_DIR=/app/recordings
CMD ["node", "bot.mjs"]
