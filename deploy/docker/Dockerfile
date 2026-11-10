
FROM node:22.23.0-slim@sha256:d9f850096136edbc402debdd8729579a288aac64574ada0ff4db26b6ae58b0b2 AS frontend
ARG VORTIS_LEADERBOARD_PUBLIC_ANON=

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm install --global "$(node -p 'require("./package.json").packageManager')" && \
    npm ci --ignore-scripts
COPY frontend/ .
RUN VITE_SUPABASE_ANON_KEY="${VORTIS_LEADERBOARD_PUBLIC_ANON}" npm run build

FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:${PATH}"

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
        sh -s -- -y --profile minimal --default-toolchain none && \
    rustup toolchain install 1.89 --profile minimal && \
    rustup default 1.89

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir uv && \
    uv export --frozen --no-dev --extra server --no-emit-project > requirements.txt && \
    uv pip install --system --no-deps -r requirements.txt && \
    uv pip install --system --no-deps "maturin>=1.12.6,<2"

COPY src/ src/
COPY rust/ rust/
COPY scripts/install scripts/install
COPY deploy/windows deploy/windows
COPY configs/vortis/examples configs/vortis/examples

COPY --from=frontend /src/vortis/server/static src/vortis/server/static/

RUN uv pip install --system --no-deps . && \
    maturin build --release \
        --manifest-path rust/crates/vortis-python/Cargo.toml \
        --interpreter python3 \
        --out /tmp/vortis-rust-wheel && \
    uv pip install --system --no-deps /tmp/vortis-rust-wheel/*.whl && \
    python3 -c "import vortis_rust; print('vortis_rust ok')" && \
    python3 -m pip uninstall -y maturin && \
    rm -rf /tmp/vortis-rust-wheel rust

FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
WORKDIR /app

RUN groupadd --system --gid 10001 vortis && \
    useradd --system --uid 10001 --gid vortis \
        --create-home --home-dir /home/vortis vortis
ENV HOME=/home/vortis
USER vortis

EXPOSE 8000

ENTRYPOINT ["vortis"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
