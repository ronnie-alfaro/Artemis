FROM rust:1.90-bookworm AS build
WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --locked --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates python3 && rm -rf /var/lib/apt/lists/*
COPY --from=build /build/target/release/artemis-bridge /usr/local/bin/
COPY adapters /usr/local/lib/artemis-bridge/adapters
USER 10001:10001
ENTRYPOINT ["artemis-bridge"]
