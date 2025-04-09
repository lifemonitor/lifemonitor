# This Dockerfile is used to build a SEEK image for testing purposes.
# It is based on the official SEEK image and includes additional configuration
# and data for testing.

# Set the base image to the official SEEK image
# The SEEK version can be specified as a build argument
ARG TARGET_VERSION=1.12
ARG SOURCE_VERSION=${SOURCE_VERSION:-${TARGET_VERSION}}

# Stage 1: Build the base image
# Use the crs4/lifemonitor-tests image as a base for the build
# This image contains the necessary data and configurations for testing
FROM crs4/lifemonitor-tests:seek-${SOURCE_VERSION} AS base


# Stage 2: Build the SEEK image 
FROM fairdom/seek:${TARGET_VERSION} AS seek

# Consume the SOURCE_VERSION build argument
ARG SOURCE_VERSION
# Consume the TARGET_VERSION build argument
ARG TARGET_VERSION
# Set the environment variables for SEEK
ENV TARGET_VERSION=${TARGET_VERSION}

# Switch to root user to perform administrative tasks
USER root

# Copy the filestore and SQLite database from the base image to the SEEK image
RUN mkdir -p /tmp/data
COPY --from=base --chown=www-data:www-data /seek/filestore /tmp/data/filestore
COPY --from=base --chown=www-data:www-data /seek/sqlite3-db/production.sqlite3 /tmp/data/db.sqlite3

RUN cd /tmp \
    && cp -a /tmp/data/filestore/* /seek/filestore/ \
    && mv /tmp/data/db.sqlite3 /seek/sqlite3-db/production.sqlite3 \
    && chown -R www-data:www-data /seek/filestore \
    && chown -R www-data:www-data /seek/sqlite3-db/production.sqlite3 \
    && rm -rf /tmp/data

# Copy the certificates and Nginx configuration file to the SEEK image
RUN mkdir -p /seek/certs
COPY --chown=www-data:www-data certs/lm.crt /seek/certs/lm.crt
COPY --chown=www-data:www-data certs/lm.key /seek/certs/lm.key
COPY --chown=www-data:www-data nginx.conf /seek/nginx.conf


# Set the working directory to /seek
WORKDIR /seek

# Restore the user to www-data
USER www-data


RUN docker/upgrade.sh --migrate

# Perform the migration if the SEEK version is different from the source version
# and archive the migrated data for later use within the container image
# RUN if [ "${TARGET_VERSION}" != "${SOURCE_VERSION}" ]; then \
#     docker/upgrade.sh --migrate; \
#     fi

# RUN if [ "${TARGET_VERSION}" != "${SOURCE_VERSION}" ]; then \
#     docker/upgrade.sh --migrate; \
#     mkdir -p /tmp/data/filestore; \
#     cp -a /seek/filestore/* /tmp/data/filestore/; \
#     cp -a /seek/sqlite3-db/production.sqlite3 /tmp/data/db.sqlite3; \
#     cd /tmp && tar -czvf /seek/data.tar.gz data; \
#     rm -rf /tmp/data; \
# \\\\\\\\\\\\\\\\\fi

# RUN cd /tmp && tar xzvf data.tar.gz \
#     && chown -R www-data:www-data data \
#     && mv data /seek/ \
#     && rm -rf data.tar.gz \
#     && chmod 755 /usr/local/bin/entrypoint.sh

#     rm -Rf /seek/filestore/*
#     cp -a data/filestore/* /seek/filestore/
#     cp -a data/db.sqlite3 /seek/sqlite3-db/production.sqlite3


# ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

USER www-data
