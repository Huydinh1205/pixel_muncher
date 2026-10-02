# Shared helpers for the launchers. Sourced, not run.

# config file used by a mode (--local, --mock or production)
pxm_config_for_mode() {
  local repo="$1" mode="$2"
  case "$mode" in
    --local) echo "$repo/config.local.yaml" ;;
    --mock)  echo "$repo/config.mock.yaml" ;;
    *) echo "$repo/config.yaml" ;;
  esac
}

# first "port:" value in the config, default 8080
pxm_port() {
  local p
  p=$(grep -E '^[[:space:]]*port:[[:space:]]*[0-9]+' "$1" 2>/dev/null | head -1 | sed -E 's/.*port:[[:space:]]*([0-9]+).*/\1/')
  echo "${p:-8080}"
}

pxm_is_up() { curl -s -o /dev/null --max-time 2 "$1"; }

# wait up to $2 seconds for the URL to answer
pxm_wait_up() {
  local url="$1" secs="${2:-60}" i=0
  while [ $i -lt "$secs" ]; do
    pxm_is_up "$url" && return 0
    sleep 1; i=$((i + 1))
  done
  return 1
}

# A Python that can import nicegui (and osgeo for --local). Prints its path.
pxm_find_python() {
  local repo="$1" mode="$2" need="import nicegui, yaml" cand base
  [ "$mode" = "--local" ] && need="$need; import osgeo_utils.gdal2tiles"
  local cands=()
  [ -n "${PXM_GUI_PYTHON:-}" ] && cands+=("$PXM_GUI_PYTHON")
  cands+=("$repo/.venv/bin/python")
  for base in "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3" "$HOME/anaconda3" \
              "$HOME/.conda" "/opt/homebrew/Caskroom/miniforge/base" "/opt/homebrew/anaconda3" \
              "/opt/miniconda3" "/opt/anaconda3" "/usr/local/miniconda3"; do
    cands+=("$base/envs/pxm/bin/python")
  done
  # ask the user's own shell where conda lives (works when conda init was run)
  for sh in zsh bash; do
    if command -v "$sh" >/dev/null 2>&1; then
      base=$("$sh" -ic 'conda info --base' 2>/dev/null | tail -1)
      [ -n "$base" ] && cands+=("$base/envs/pxm/bin/python")
    fi
  done
  cands+=("$(command -v python3 2>/dev/null)")
  for cand in "${cands[@]}"; do
    [ -n "$cand" ] && [ -x "$cand" ] && "$cand" -c "$need" >/dev/null 2>&1 && { echo "$cand"; return 0; }
  done
  return 1
}
