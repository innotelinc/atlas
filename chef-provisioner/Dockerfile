# Atlas Chef provisioner — deployment-per-app Convex backends (fork 3b.2).
# Node HTTP service that shells out to the docker CLI (mounted host socket)
# to spawn one convex-backend container per Chef project.
FROM docker:cli AS docker-cli

FROM node:22-alpine
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
WORKDIR /app
COPY server.mjs /app/server.mjs
ENV NODE_ENV=production
EXPOSE 9080
CMD ["node", "/app/server.mjs"]
