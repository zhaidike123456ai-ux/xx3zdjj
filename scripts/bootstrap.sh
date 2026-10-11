#!/bin/bash
# macOS bootstrap; no remote script execution and no persistent PATH change.
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
runtime_root="$HOME/Library/Application Support/xx3zdjj/runtime"
allow_install=0
chosen_python=""
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  case "${args[$i]}" in
    --allow-install) allow_install=1 ;;
    --runtime-root) i=$((i+1)); runtime_root="${args[$i]}" ;;
    --runtime-root=*) runtime_root="${args[$i]#*=}" ;;
    --python) i=$((i+1)); chosen_python="${args[$i]}" ;;
    --python=*) chosen_python="${args[$i]#*=}" ;;
  esac
done
if [ ${#args[@]} -eq 0 ]; then args=(check); fi
compatible_python() {
  "$1" -B -c 'import sys;sys.exit(0 if (3,9)<=sys.version_info[:2]<(3,14) else 1)' >/dev/null 2>&1
}
if [ -n "$chosen_python" ] && ! compatible_python "$chosen_python"; then
  echo '指定Python不可用或版本不兼容（需要3.9–3.13）。' >&2; exit 2
fi
if [ -z "$chosen_python" ]; then
  for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python; do
    if command -v "$candidate" >/dev/null 2>&1 && compatible_python "$(command -v "$candidate")"; then
      chosen_python="$(command -v "$candidate")"; break
    fi
  done
fi
if [ -n "$chosen_python" ]; then
  exec "$chosen_python" -B "$script_dir/runtime_manager.py" "${args[@]}"
fi
# Also adopt an existing managed Python after an interrupted/completed bootstrap.
if [ -d "$runtime_root/bootstrap-python" ]; then
  while IFS= read -r candidate; do
    if compatible_python "$candidate"; then
      exec "$candidate" -B "$script_dir/runtime_manager.py" "${args[@]}"
    fi
  done < <(find "$runtime_root/bootstrap-python" -type f -name python3.11 2>/dev/null)
fi
if [ "$allow_install" -ne 1 ]; then
  echo '未找到兼容Python。只读检查未下载任何文件。需补装约120MB：Astral uv官方校验发行包及Python，位置：' >&2
  echo "$runtime_root/bootstrap-python" >&2
  echo '已有用户授权后再传 --allow-install；不执行远端安装脚本。' >&2
  exit 2
fi
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) archive=uv-aarch64-apple-darwin.tar.gz; digest=3f61099e261e449527141dbf125629fab33ad696468c8c90cebbac40185a306c ;;
  Darwin-x86_64) archive=uv-x86_64-apple-darwin.tar.gz; digest=76638fdcfa91357858771551a1c88de1f7c3b270b33ab1866f8a0618d9e442d8 ;;
  *) echo '此bootstrap.sh只支持macOS ARM64/x64。Windows请用bootstrap.ps1。' >&2; exit 2 ;;
esac
mkdir -p "$runtime_root/cache"
lock="$runtime_root/bootstrap.lock"
if ! mkdir "$lock" 2>/dev/null; then echo '另一个bootstrap持有锁，请确认其进程状态；不自动抢锁。' >&2; exit 2; fi
stage="$(mktemp -d "$runtime_root/cache/bootstrap.XXXXXX")"
trap 'rm -rf "$stage"; rmdir "$lock" 2>/dev/null || true' EXIT
curl --fail --location --proto '=https' --tlsv1.2 --output "$stage/$archive" "https://github.com/astral-sh/uv/releases/download/0.8.22/$archive"
actual="$(shasum -a 256 "$stage/$archive" | awk '{print $1}')"
if [ "$actual" != "$digest" ]; then echo 'uv下载SHA256校验失败，未执行。' >&2; exit 2; fi
# uv archives contain only relative regular binary members/directories.
if tar -tzf "$stage/$archive" | awk '/^\// || /(^|\/)\.\.(\/|$)/ {bad=1} END {exit !bad}'; then
  echo 'uv归档路径非法。' >&2; exit 2
fi
tar -xzf "$stage/$archive" -C "$stage"
uv="$(find "$stage" -type f -name uv -print -quit)"
[ -n "$uv" ] || { echo 'uv归档没有可执行程序。' >&2; exit 2; }
chmod u+x "$uv"
UV_CACHE_DIR="$runtime_root/cache/uv" "$uv" python install 3.11.13 --install-dir "$runtime_root/bootstrap-python" --no-bin
chosen_python="$(find "$runtime_root/bootstrap-python" -type f -name python3.11 -print -quit)"
compatible_python "$chosen_python" || { echo '补装的Python无法运行，旧环境未修改。' >&2; exit 2; }
# Finish bootstrap cleanup before invoking manager; runtime manager owns another lock.
rm -rf "$stage"
rmdir "$lock"
trap - EXIT
exec "$chosen_python" -B "$script_dir/runtime_manager.py" --python "$chosen_python" "${args[@]}"
