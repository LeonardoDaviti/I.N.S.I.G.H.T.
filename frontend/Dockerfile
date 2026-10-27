# Stage 1: Build
# Node 22: Vite 7 needs >= 20.19. The image only builds; frontend tests run on the host.
FROM node:22-alpine AS builder

WORKDIR /app

# Accept build argument
ARG VITE_API_URL=
ENV VITE_API_URL=$VITE_API_URL
# The build stamp (issue 0020), inlined by Vite into the Ingestion tab's version line.
ARG INSIGHT_VERSION=
ARG INSIGHT_COMMIT=
ARG INSIGHT_COMMIT_DATE=
ENV VITE_INSIGHT_VERSION=$INSIGHT_VERSION \
    VITE_INSIGHT_COMMIT=$INSIGHT_COMMIT \
    VITE_INSIGHT_COMMIT_DATE=$INSIGHT_COMMIT_DATE

COPY package*.json ./
RUN npm ci || npm install

COPY . .
RUN npm run build

# Stage 2: Production (unchanged)
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
