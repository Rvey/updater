FROM node:22-bookworm-slim AS build
WORKDIR /app

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

COPY package.json package-lock.json ./
# npm ci is strict about lock/platform combinations: npm 11 can prune the
# bundled @emnapi/* entries for Tailwind's wasm fallback when the lock is
# regenerated on another platform, which makes npm ci fail in this image.
# Fall back to a lock-repairing install so the image still builds.
RUN npm ci --include=optional --no-audit --no-fund \
    || (echo "package-lock.json was out of sync with npm ci; repairing with npm install" \
        && npm install --include=optional --no-audit --no-fund)

COPY . .
RUN test -n "$VITE_API_BASE_URL" && npm run build

FROM nginx:stable-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
