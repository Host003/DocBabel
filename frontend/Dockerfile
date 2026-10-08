FROM node:22-alpine AS builder

# 可选 npm 镜像源（默认官方源，CI 不受影响）：
#   --build-arg NPM_REGISTRY=https://registry.npmmirror.com
ARG NPM_REGISTRY=https://registry.npmjs.org

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm config set registry "$NPM_REGISTRY" && npm ci

COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
