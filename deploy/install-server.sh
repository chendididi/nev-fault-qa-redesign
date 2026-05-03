#!/usr/bin/env bash
set -euo pipefail

echo "== NEV Fault QA server prerequisite check =="

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install Docker Engine before continuing."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is not available. Install the compose plugin before continuing."
  exit 1
fi

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi is not available. Install the NVIDIA driver before GPU deployment."
  exit 1
fi

nvidia-smi

echo "Checking Docker GPU runtime..."
if docker info 2>/dev/null | grep -qi nvidia; then
  echo "Docker reports NVIDIA runtime support."
else
  echo "Docker does not report NVIDIA runtime support. Install nvidia-container-toolkit before starting vLLM."
  exit 1
fi

echo "Prerequisite check passed."
