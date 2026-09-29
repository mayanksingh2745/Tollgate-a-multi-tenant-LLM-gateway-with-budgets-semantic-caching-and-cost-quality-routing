# Build Stage
FROM node:20-alpine AS build

WORKDIR /app

COPY apps/dashboard/package.json ./
RUN npm install

COPY apps/dashboard ./
RUN npm run build

# Run Stage
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY apps/dashboard/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
