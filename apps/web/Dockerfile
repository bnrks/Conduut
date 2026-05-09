FROM node:20-alpine AS base

WORKDIR /app
ARG PNPM_VERSION=10.19.0
RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

FROM node:20-alpine AS runtime

WORKDIR /app
ARG PNPM_VERSION=10.19.0
RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate

ENV NODE_ENV=production

COPY --from=base /app/package.json ./package.json
COPY --from=base /app/pnpm-lock.yaml ./pnpm-lock.yaml
COPY --from=base /app/.next ./.next
COPY --from=base /app/public ./public
COPY --from=base /app/node_modules ./node_modules

EXPOSE 3000

CMD ["pnpm", "start", "-p", "3000"]
