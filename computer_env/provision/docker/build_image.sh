#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

IMAGE_NAME="${1:-${DOCKER_ENV_IMAGE:-paraverse-desktop:latest}}"
PLATFORM="${DOCKER_ENV_PLATFORM:-linux/amd64}"

cd "${REPO_ROOT}"
docker build --platform "${PLATFORM}" -f computer_env/provision/docker/Dockerfile -t "${IMAGE_NAME}" .
