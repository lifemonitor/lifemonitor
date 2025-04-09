#!/bin/bash

# Copyright (c) 2020-2025 CRS4
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# Get the current path
CURRENT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Default values
TARGET_VERSION=""
PUSH=false
SAVE_DATA=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
    --help | -?)
        echo "Usage: $0 [TARGET_VERSION] [SOURCE_VERSION] [--push] [--save-data]"
        echo "  TARGET_VERSION: The target version of the Docker image (default: 1.12)"
        echo "  SOURCE_VERSION: The source version of the Docker image (default: TARGET_VERSION)"
        echo "  --push: Push the built Docker image to the registry"
        echo "  --save-data: Save data from the Docker container to a tarball file within the $CURRENT_PATH/data directory"
        exit 0
        ;;
    --push)
        PUSH=true
        ;;
    --save-data)
        SAVE_DATA=true
        ;;
    *)
        if [ -z "$TARGET_VERSION" ]; then
            TARGET_VERSION="$1"
        elif [ -z "$SOURCE_VERSION" ]; then
            SOURCE_VERSION="${1:-$TARGET_VERSION}"
        else
            echo "Unknown argument: $1"
            exit 1
        fi
        ;;
    esac
    shift
done

# Check if TARGET_VERSION is provided
if [ -z "$TARGET_VERSION" ]; then
    echo "TARGET_VERSION is required."
    exit 1
fi
# Set the default SOURCE_VERSION to TARGET_VERSION if not provided
if [ -z "$SOURCE_VERSION" ]; then
    SOURCE_VERSION="$TARGET_VERSION"
fi

# echo -e "\nBuilding Docker image for TARGET_VERSION $TARGET_VERSION and SOURCE_VERSION $SOURCE_VERSION..."
# echo "Push: $PUSH"
# echo "Save data: $SAVE_DATA"

# Check if the TARGET_VERSION is available
echo -e "\nAttempting to pull the Docker image for TARGET_VERSION $TARGET_VERSION..."
if ! docker pull "fairdom/seek:$TARGET_VERSION"; then
    echo "TARGET_VERSION $TARGET_VERSION not found in the Docker registry. Please ensure the image exists."
    exit 1
fi

# Define the image name
IMAGE_NAME="crs4/lifemonitor-tests:seek-$TARGET_VERSION"

# Set the target Dockerfile
DOCKERFILE="$CURRENT_PATH/seek.base.Dockerfile"
if [ "$TARGET_VERSION" == "1.12" ]; then
    echo -e "\nUsing the base Dockerfile for TARGET_VERSION $TARGET_VERSION..."
else
    echo -e "\nUsing the Dockerfile for SOURCE_VERSION $SOURCE_VERSION..."
    DOCKERFILE="$CURRENT_PATH/seek.Dockerfile"
fi
# Build the image
echo -e "\nBuilding the Docker image for TARGET_VERSION $TARGET_VERSION..."
docker build \
    --debug \
    --build-arg TARGET_VERSION=$TARGET_VERSION \
    --build-arg SOURCE_VERSION=$SOURCE_VERSION \
    -t $IMAGE_NAME \
    -f $DOCKERFILE \
    $CURRENT_PATH

# Check the exit code of the docker build command
if [ $? -ne 0 ]; then
    echo -e "\nDocker image $IMAGE_NAME built successfully for TARGET_VERSION $TARGET_VERSION."
    exit 1
fi

# If the image is built successfully, check if we need to save data
if [ "$SAVE_DATA" == "true" ]; then
    
    # Remove any existing container named "seek"
    docker rm -f seek 2>/dev/null

    # Extract the image data
    echo -e "\nExtracting the image data for TARGET_VERSION $TARGET_VERSION..."
    docker run -d --name seek \
        -v $CURRENT_PATH/data:/data \
        -e TARGET_VERSION=$TARGET_VERSION \
        -e SOURCE_VERSION=$SOURCE_VERSION \
        --entrypoint /bin/bash \
        $IMAGE_NAME -c "sleep infinity"

    # Prepare the directories for the backup
    docker exec --user 0:0 seek /bin/bash -c "
        mkdir -p /tmp/data
        cp -a /seek/filestore /tmp/data/filestore
        cp -a /seek/sqlite3-db/production.sqlite3 /tmp/data/db.sqlite3
        chown -R www-data:www-data /tmp/data
        tar -czf /tmp/seek.tar.gz -C /tmp/data .
        chown www-data:www-data /tmp/seek.tar.gz
        mv /tmp/seek.tar.gz /data/${TARGET_VERSION}.tar.gz
    "
    # Check the exit code of the docker exec command
    if [ $? -ne 0 ]; then
        echo "Failed to copy the data from the container."
        exit 1
    else
        echo -e "\nData extracted successfully for TARGET_VERSION $TARGET_VERSION."
        echo -e "Data saved in $CURRENT_PATH/data/${TARGET_VERSION}.tar.gz."
        echo -e "Please check the data directory for the saved data."
    fi

    # Remove the container
    docker rm -f seek >/dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo -e "\nContainer removed successfully."
        exit 1
    fi
fi

# If push is required, push the image
if [ "$PUSH" == "true" ]; then
    docker push $IMAGE_NAME
    if [ $? -ne 0 ]; then
        echo "Failed to push Docker image $IMAGE_NAME."
        exit 1
    fi
    echo -e "\nDocker image $IMAGE_NAME pushed successfully."
fi
