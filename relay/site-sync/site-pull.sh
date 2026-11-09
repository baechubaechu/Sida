#!/bin/sh
# 국내 서버에서 1분마다(site-pull.timer) 'site' 계정으로 돈다.
# GitHub main의 relay/site/만 얕게 받아, 바뀌었으면 Caddy가 내주는 /opt/sida-kr/site/에 복사한다.
# 서버가 가져오는 방식이라 서버의 SSH(22번)를 밖에 열 필요가 없다.
# 저장소 접근은 읽기 전용 배포 키(~/.ssh/github_site, ~/.ssh/config의 Host github.com)로 한다.
set -eu

REPO_URL="${SITE_REPO_URL:-git@github.com:baechubaechu/Sida.git}"
CLONE="${SITE_CLONE:-$HOME/sida-site-src}"
TARGET="${SITE_TARGET:-/opt/sida-kr/site}"
STAMP="$CLONE/.deployed-tree"

if [ ! -d "$CLONE/.git" ]; then
  git clone --quiet --depth 1 --filter=blob:none --sparse --branch main "$REPO_URL" "$CLONE"
  git -C "$CLONE" sparse-checkout set relay/site
fi

git -C "$CLONE" fetch --quiet --depth 1 origin main
tree=$(git -C "$CLONE" rev-parse FETCH_HEAD:relay/site)
[ "$(cat "$STAMP" 2>/dev/null || true)" = "$tree" ] && exit 0

git -C "$CLONE" reset --quiet --hard FETCH_HEAD
rsync -rlc --delete --chmod=D755,F644 --itemize-changes "$CLONE/relay/site/" "$TARGET/"
echo "$tree" > "$STAMP"
echo "반영함: relay/site $tree ($(git -C "$CLONE" log -1 --format='%h %s'))"
