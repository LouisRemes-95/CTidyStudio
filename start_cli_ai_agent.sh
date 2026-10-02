#!/usr/bin/env bash
set -euo pipefail

open -g -a Docker
sleep 2

osascript <<'APPLESCRIPT'
tell application "System Events"
  if exists (application process "Docker Desktop") then
    tell application process "Docker Desktop"
      if (exists window 1) then click button 1 of window 1 -- red ⓧ
    end tell
  else if exists (application process "Docker") then
    tell application process "Docker"
      if (exists window 1) then click button 1 of window 1
    end tell
  end if
end tell
APPLESCRIPT


# Always run codex-cli via Docker
docker run -it --rm \
  -v "$PWD":/workspace \
  -v "$HOME/.codex":/home/coder/.codex \
  codex-cli