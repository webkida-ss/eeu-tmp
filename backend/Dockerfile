FROM rust:1.85-slim AS builder

WORKDIR /app
COPY contracts ./contracts
COPY frontend/src/features/learning/data/learningPaths.json ./frontend/src/features/learning/data/learningPaths.json
COPY backend ./backend

WORKDIR /app/backend
RUN cargo build --release

FROM debian:bookworm-slim

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY --from=builder /app/backend/target/release/english-backend /usr/local/bin/english-backend
COPY --from=builder /app/backend/target/release/personalization_worker /usr/local/bin/personalization_worker
COPY --from=builder /app/frontend/src/features/learning/data/learningPaths.json /app/data/learningPaths.json

ENV APP_HOST=0.0.0.0
ENV APP_PORT=8080
ENV CATALOG_DATA_PATH=/app/data/learningPaths.json
ENV RUST_LOG=info

EXPOSE 8080
USER appuser

CMD ["english-backend"]
