#!/usr/bin/env bash
# Build the Android .aab on Tower instead of waiting in the EAS cloud queue.
# Same EAS signing key (upload key for Play) and the same remote versionCode counter as cloud builds.
# Needs (one-time, see CLAUDE.md "Local Android builds"): JDK 17 + Android SDK under $TOOLS, the Expo token in .expo-token.
#   bash scripts/android-build-local.sh [output.aab]
set -euo pipefail
TOOLS=${TOOLS:-/mnt/user/AI/tools}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export JAVA_HOME=$TOOLS/jdk-17 ANDROID_HOME=$TOOLS/android-sdk ANDROID_SDK_ROOT=$TOOLS/android-sdk
export PATH=$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH
export GRADLE_USER_HOME=${GRADLE_USER_HOME:-/tmp/gradle-home}           # fast local disk; rebuilt if lost
export EAS_LOCAL_BUILD_WORKINGDIR=${EAS_LOCAL_BUILD_WORKINGDIR:-/tmp/eas-local-build}
export EXPO_TOKEN=$(cat "$ROOT/.expo-token")
OUT=$(realpath -m "${1:-$ROOT/releases/pocketprint3d-local.aab}")
cd "$ROOT/mobile"
npx eas-cli@latest build -p android --profile production --local --non-interactive --output "$OUT"
ls -la "$OUT"
