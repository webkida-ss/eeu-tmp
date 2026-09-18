#!/bin/bash
# Usage: ./scaffold.sh <project-root>
# Sets up standard directories and files following project structure rules.

set -e

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${1:-.}"

DIRS=("api" "backend" "docs" "frontend" "infra" "poc")
FILES=("README.md" ".gitignore" "task.yaml" ".env.example")

create_file() {
  local path="$1"
  local name="$2"

  case "$(basename "$path")" in
    .gitignore)
      /bin/cp "$SKILL_DIR/references/gitignore.template" "$path"
      echo "updated: $path"
      return
      ;;
  esac

  if [ -f "$path" ]; then
    echo "skip: $path"
    return
  fi

  case "$(basename "$path")" in
    README.md)
      printf "# %s\n\nOverview and usage.\n" "$name" > "$path"
      ;;
    task.yaml)
      echo "tasks: []" > "$path"
      ;;
    .env.example)
      printf "# Environment variables\n# Copy this file to .env and fill in the values\n" > "$path"
      ;;
  esac

  echo "created: $path"
}

# Standard files at project root only
for file in "${FILES[@]}"; do
  create_file "$ROOT/$file" "$(basename "$ROOT")"
done

# Standard directories (no files)
for dir in "${DIRS[@]}"; do
  if [ ! -d "$ROOT/$dir" ]; then
    mkdir -p "$ROOT/$dir"
    echo "created: $ROOT/$dir/"
  else
    echo "skip: $ROOT/$dir/"
  fi
done

# GitHub Actions deploy workflow scaffold
WORKFLOW_DIR="$ROOT/.github/workflows"
if [ ! -d "$WORKFLOW_DIR" ]; then
  mkdir -p "$WORKFLOW_DIR"
  echo "created: $WORKFLOW_DIR/"
else
  echo "skip: $WORKFLOW_DIR/"
fi

create_deploy_workflow() {
  local target="$1"
  local title="$2"
  local job_id="$3"
  local display_name="$4"

  if [ -f "$target" ]; then
    echo "skip: $target"
    return
  fi

  cat > "$target" <<EOF
name: Deploy $title

on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  $job_id:
    name: Deploy $display_name
    runs-on: ubuntu-latest
    steps:
      - name: Placeholder
        run: echo "$title deploy workflow is not implemented yet."
EOF
  echo "created: $target"
}

create_deploy_workflow "$WORKFLOW_DIR/deploy-backend.yml" "Backend" "deploy-backend" "backend"
create_deploy_workflow "$WORKFLOW_DIR/deploy-infra.yml" "Infra" "deploy-infra" "infra"
create_deploy_workflow "$WORKFLOW_DIR/deploy-frontend.yml" "Frontend" "deploy-frontend" "frontend"

# OpenAPI documentation scaffold inside contracts/openapi/
API_DIRS=(
  "components/schemas"
  "paths"
)

for dir in "${API_DIRS[@]}"; do
  target="$ROOT/contracts/openapi/$dir"
  if [ ! -d "$target" ]; then
    mkdir -p "$target"
    touch "$target/.gitkeep"
    echo "created: $target/"
  else
    echo "skip: $target/"
  fi
done

if [ ! -f "$ROOT/contracts/openapi/openapi.yaml" ]; then
  cat > "$ROOT/contracts/openapi/openapi.yaml" <<'EOF'
openapi: 3.1.0
info:
  title: API
  version: 0.1.0
paths: {}
components:
  schemas: {}
EOF
  echo "created: $ROOT/contracts/openapi/openapi.yaml"
else
  echo "skip: $ROOT/contracts/openapi/openapi.yaml"
fi

# Next.js (Bulletproof React) src/ structure inside frontend/
NEXT_SRC_DIRS=(
  "app"
  "components/ui"
  "components/layout"
  "features"
  "hooks"
  "lib"
  "stores"
  "types"
  "utils"
)

for dir in "${NEXT_SRC_DIRS[@]}"; do
  target="$ROOT/frontend/src/$dir"
  if [ ! -d "$target" ]; then
    mkdir -p "$target"
    touch "$target/.gitkeep"
    echo "created: $target/"
  else
    echo "skip: $target/"
  fi
done

echo "Init complete."
