# Stage 1: Build
# Node 22: Vite 7 needs >= 20.19. The image only builds; frontend tests run on the host.
FROM node:22-alpine AS builder

WORKDIR /app

# Accept build argument
ARG VITE_API_URL=
ENV VITE_API_URL=$VITE_API_URL
# Analysis surfaces (reading-finish R3): off builds the reading-only app. At
# runtime the backend's GET /api/config wins over this value.
ARG VITE_INSIGHT_ANALYSIS=off
ENV VITE_INSIGHT_ANALYSIS=$VITE_INSIGHT_ANALYSIS

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
