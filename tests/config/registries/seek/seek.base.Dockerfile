# This Dockerfile is used to build a SEEK image for testing purposes.
# It is based on the official SEEK image and includes additional configuration
# and data for testing.

# Set the base image to the official SEEK image
# The SEEK version can be specified as a build argument
ARG TARGET_VERSION=1.12
ARG SOURCE_VERSION=${SOURCE_VERSION:-${TARGET_VERSION}}

FROM fairdom/seek:${TARGET_VERSION} AS seek

# Consume the SOURCE_VERSION build argument
ARG SOURCE_VERSION
# Consume the TARGET_VERSION build argument
ARG TARGET_VERSION

# Set the environment variables for SEEK
ENV TARGET_VERSION=${TARGET_VERSION}

# Switch to root user to perform administrative tasks
USER root

# Copy the data tarball from the build context to the SEEK image
COPY --chown=www-data:www-data ./data/${SOURCE_VERSION}.tar.gz /tmp/data.tar.gz

# Extract the data from the tarball and copy it to the appropriate directories
RUN cd /tmp && mkdir data && tar xzvf data.tar.gz -C /tmp/data \
    && cp -a /tmp/data/filestore/* /seek/filestore/ \
    && mv /tmp/data/db.sqlite3 /seek/sqlite3-db/production.sqlite3 \
    && chown -R www-data:www-data /seek/filestore \
    && chown -R www-data:www-data /seek/sqlite3-db/production.sqlite3 \
    && rm -rf data.tar.gz /tmp/data

# Copy the certificates and Nginx configuration file to the SEEK image
RUN mkdir -p /seek/certs
COPY --chown=www-data:www-data certs/lm.crt /seek/certs/lm.crt
COPY --chown=www-data:www-data certs/lm.key /seek/certs/lm.key
COPY --chown=www-data:www-data nginx.conf /seek/nginx.conf

# Set the working directory to /seek
WORKDIR /seek

# Restore the user to www-data
USER www-data

# Perform the migration if the SEEK version is different from the source version
RUN docker/upgrade.sh --migrate
