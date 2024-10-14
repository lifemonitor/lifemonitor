FROM node:22-alpine

RUN npm install --global smee-client

ENV SMEE_CHANNEL="new"

ENV SMEE_TARGET="localhost:3000"

ENV EVENT_HANDLER_URL="/event_handler"

CMD ["sh", "-c", "smee", "-u", "https://smee.io/$SMEE_CHANNEL", "--target", "$SMEE_TARGET", "--path", "$EVENT_HANDLER_URL"]
