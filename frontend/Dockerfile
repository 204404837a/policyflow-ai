# Next.js dev/build container
FROM node:20-alpine

WORKDIR /app

# Install deps first (better layer caching)
COPY package.json ./
RUN npm install

# App source
COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]
