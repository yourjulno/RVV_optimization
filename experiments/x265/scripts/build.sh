#!/usr/bin/env bash
# Run on the macOS host after installing the documented container dependencies.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
container="${X265_CONTAINER:-diploma-syntacore-smoke}"
expected=b81f650e21e8aacbe6a9ad04ce14aefc05b932c0
actual="$(git -C "$root/sources/x265" rev-parse HEAD)"
[[ "$actual" == "$expected" ]] || { echo "Unexpected x265 revision: $actual" >&2; exit 1; }
mkdir -p "$root/results/build" "$root/bin"
docker exec "$container" mkdir -p /opt/diploma/x265-source
docker cp "$root/sources/x265/." "$container:/opt/diploma/x265-source/"
docker cp "$root/configs/riscv64-linux.cmake" "$container:/opt/diploma/x265-toolchain.cmake"
docker exec "$container" cmake -S /opt/diploma/x265-source/source -B /opt/diploma/x265-build -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE=/opt/diploma/x265-toolchain.cmake \
  -DCMAKE_BUILD_TYPE=Release -DENABLE_RVV=ON -DENABLE_ASSEMBLY=ON \
  -DRISCV64_RUNTIME_CPU_DETECT=ON -DHIGH_BIT_DEPTH=OFF -DENABLE_CLI=ON \
  -DENABLE_SHARED=OFF -DENABLE_LIBNUMA=OFF \
  2>&1 | tee "$root/results/build/configure.log"
docker cp "$container:/opt/diploma/x265-build/CMakeCache.txt" "$root/results/build/CMakeCache.txt"
# Do not silently accept CMake's fallback to a build without RVV.
grep -q '^ENABLE_RVV:BOOL=ON$' "$root/results/build/CMakeCache.txt"
grep -q '^RVV_INTRINSIC_CXX_TEST_COMPILED:INTERNAL=1$' "$root/results/build/CMakeCache.txt"
docker exec "$container" cmake --build /opt/diploma/x265-build --parallel 4 \
  2>&1 | tee "$root/results/build/build.log"
docker cp "$container:/opt/diploma/x265-build/x265" "$root/bin/x265-riscv64"
shasum -a 256 "$root/bin/x265-riscv64" > "$root/results/build/sha256.txt"
