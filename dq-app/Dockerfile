# syntax=docker/dockerfile:1
#
# IntelliDQ frontend - Create React App built to static files, served by nginx.
#
# Build from dq-app/ (NOT the repo root):
#   docker build -t intellidq-frontend:local ./dq-app
#   docker run --rm -p 3000:80 intellidq-frontend:local
#
# The API base URL is hardcoded to http://localhost:8000 in src/api.js, so the browser
# talks to the host's port 8000 directly - the backend container must publish it. See
# the note in docker-compose.yml before deploying this anywhere but localhost.

########################  build  ########################
FROM node:20-bookworm-slim AS build

WORKDIR /app

# Dependencies first so editing a component does not invalidate the npm layer.
# .npmrc is required, not incidental: it carries legacy-peer-deps=true, which the
# committed package-lock.json depends on. Without it `npm ci` fails on an optional
# peer dependency (yaml, via postcss-load-config) that the lock does not record.
COPY package.json package-lock.json .npmrc ./
RUN npm ci

COPY . .

# react-scripts treats every ESLint warning as a fatal error when CI is set, which some
# build environments do automatically. A container build should not fail on lint - CI
# already enforces that in the frontend job.
ENV CI=false
RUN npm run build

########################  runtime  ########################
FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -qO- http://localhost/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
