#!/bin/bash
set -eo pipefail
# Script to run gerrit/jenkins CI checks on your local code.
# It uses the same docker image we use to run such tests in
# CI.
usage() {
    cat <<USG
$0 - run tests on your working directory.
    USAGE: [IMG_VERSION=X.Y.Z] $0 [-h|[-n] TOX_ARGS]
    Options:
        -h Prints this help message
        -n Don't pull the docker image, useful when you are testing local images.
    Arguments:
        TOX_ARGS are (optional) arguments that get passed directly to "tox" in the container.
    You can override the image version to use with the environment variable
    IMG_VERSION.
    EXAMPLES:
        # Run all tests CI would run
        $ run_ci_locally.sh
        # Execute a specific tox test
        $ run_ci_locally.sh -e py37-unit
USG
    exit 2
}
if [[ -n "$1" && "$1" == "-h" ]]; then
    usage
fi
PULL=true
if [[ -n "$1" && "$1" == "-n" ]]; then
    PULL=false
    shift
fi
# Verify that docker is installed, and that the current user has
# permissions to operate on it.
if ! command -v docker > /dev/null; then
    echo "'docker' was not found in your $PATH. Please install docker"
    exit 1
fi
if ! (docker info > /dev/null); then
    echo "Your current user ($USER) is not authorized to operate on the docker daemon. Please fix that."
    exit 1
fi
# make pycache world writable
# If we dont like this then we can merge the following and mount to local at the end
# i.e. no need for seperate rw mounts for doc/build and .tox
# https://gerrit.wikimedia.org/r/c/integration/config/+/665133
SCRIPT_DIR="$( cd "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"
REPO_DIR="${SCRIPT_DIR}/.."
#sudo find "${REPO_DIR}/toolforge_cli" -type d -name __pycache__ -exec chmod -R 0777 {} +
DOCKER_TMP_DIR="${REPO_DIR}/.docker_tmp"
mkdir -p "${DOCKER_TMP_DIR}"/{.tox/distshare,doc}
# We need to make sure the following directories exist before preforming the mount
# otherwise docker (on linux) will create them as root
mkdir -p "${REPO_DIR}/doc/build"
# We could probably make this clener?
sudo find "${DOCKER_TMP_DIR}" \! -user nobody -and -type d -exec chmod 0777 {} +
# The following may be required depending on the users umask
sudo find "${REPO_DIR}" \! -perm -o=r -exec chmod o+r {} +
sudo find "${REPO_DIR}" -type d \! -perm -o=x -exec chmod o+x {} +
IMG_VERSION=${IMG_VERSION:-latest}
IMG_NAME=${IMG_NAME:-docker-registry.wikimedia.org/releng/tox-buster:$IMG_VERSION}
CONT_NAME=local-ci-tests-${IMG_VERSION}
if [[ "$IMG_VERSION" == "latest" ]]
then
    echo "Using 'latest' image tag, set IMG_VERSION to use a specific version"
    if [[ "$PULL" == "false" ]]; then
        if [[ "$(docker image ls -q "$IMG_NAME")" == "" ]]; then
            docker pull "$IMG_NAME"
        else
            echo "Not pulling docker image $IMG_NAME as '-n' was passed and" \
                "there's already an image with that name locally"
        fi
    else
        docker pull "$IMG_NAME"
    fi
fi
exit_trap() {
  docker rm -f "${CONT_NAME}"
  sudo rm -rf ${DOCKER_TMP_DIR}/.tox/*/log
}
set -x
# we update COVERAGE_FILE below so that its avalible in the
# docker_tmp dir and thus writeable by docker
trap 'exit_trap' EXIT
docker run \
    --name "$CONT_NAME" \
    --env COVERAGE_FILE=.tox/.coverage \
    --volume /"$PWD"://src \
    --volume /"${DOCKER_TMP_DIR}/.tox"://src/.tox:rw \
    --volume /"${DOCKER_TMP_DIR}/.tox"://nonexistent/.tox:rw \
    --volume /"${DOCKER_TMP_DIR}/doc"://src/doc/build:rw \
    "$IMG_NAME" \
    "$@"


