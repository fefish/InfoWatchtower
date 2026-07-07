FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html vite.config.ts tsconfig.json tsconfig.node.json ./
COPY src ./src
# 子路径部署（如内网门户 /watchtower/）时通过构建参数覆盖：
#   docker build --build-arg VITE_BASE_PATH=/watchtower/ ...
# vite.config.ts 读取 VITE_BASE_PATH 同步驱动静态资源、router base 与 API 前缀。
ARG VITE_BASE_PATH=/
ENV VITE_BASE_PATH=$VITE_BASE_PATH
RUN npm run build

FROM nginx:1.27-alpine AS runtime

# nginx 官方镜像入口脚本会用 envsubst 把 /etc/nginx/templates/*.template
# 渲染到 /etc/nginx/conf.d/，让 EMBED_FRAME_ANCESTORS 在运行期可配。
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

# CSP frame-ancestors 白名单默认仅允许同源；intranet 形态由 compose/env 覆盖为门户域。
ENV EMBED_FRAME_ANCESTORS="'self'"

EXPOSE 80
