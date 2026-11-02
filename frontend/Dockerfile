FROM node:26-alpine as builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# `npm ci`, not `npm install`: the image is built from the lockfile alone, so a
# package.json/lock disagreement fails the build here instead of shipping a
# dependency set nobody tested.
RUN npm ci

# Copy source code
COPY . .

# Build the application (limit Node.js heap to prevent OOM on low-memory VPS)
RUN NODE_OPTIONS="--max-old-space-size=1024" npm run build

# Production stage — use unprivileged nginx (runs as UID 101, no root needed)
FROM nginxinc/nginx-unprivileged:alpine

# Copy built files
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
