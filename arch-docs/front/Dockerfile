FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_PATH=/api
ARG VITE_APP_TITLE=arch-docs
ENV VITE_API_BASE_PATH=${VITE_API_BASE_PATH}
ENV VITE_APP_TITLE=${VITE_APP_TITLE}

RUN npm run build

FROM nginx:alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
