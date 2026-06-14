# ---------------------------------------------------------------------------
# TalentMatch AI — Frontend Dockerfile
# Base: node:20-alpine
# ---------------------------------------------------------------------------
FROM node:20-alpine

WORKDIR /app

# Install dependencies first (layer-cache friendly)
COPY package.json package-lock.json ./
RUN npm ci

# Copy application source and build
COPY . .
RUN npm run build

# Expose the Next.js port
EXPOSE 3000

CMD ["npm", "start"]
