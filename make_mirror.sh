#!/usr/bin/env bash
# ============================================================================
#  site_analytics 国内镜像生成器
#  用途：在你的「能直连 GitHub」的服务器（通常是国外服务器）运行一次，
#        把各 Release 的 tarball + 版本清单 + 最新控制台脚本拉到本地目录，
#        再把这个目录通过 Web 服务器 / 对象存储 + CDN 暴露为 https 地址。
#        国内服务器把 SA_UPDATE_MIRROR 指向该地址后，升级/回滚即可走镜像，
#        不再依赖被墙的 codeload.github.com。
#
#  用法：
#     SA_UPDATE_MIRROR_OUT=/var/www/site_analytics-mirror bash make_mirror.sh
#  不指定 OUT 时，默认输出到当前目录下的 ./site_analytics-mirror。
#  可加 GH_TOKEN=xxx 以更高频调用 GitHub API（公开库可不填）。
# ============================================================================
set -u

REPO="gg4midas/site_analytics"
OUT="${SA_UPDATE_MIRROR_OUT:-./site_analytics-mirror}"
TOKEN="${GH_TOKEN:-}"
mkdir -p "$OUT"

echo "==> 拉取 tag 列表（来自 GitHub）"
tags=$(curl -fsSL --max-time 30 ${TOKEN:+-H "Authorization: Bearer $TOKEN"} \
  "https://api.github.com/repos/$REPO/tags?per_page=100" 2>/dev/null \
  | grep -oE '"name"\s*:\s*"[^"]+"' | sed -E 's/.*"([^"]+)".*/\1/' | sort -V)
if [ -z "$tags" ]; then echo "无法获取 tag 列表，请检查网络或 GH_TOKEN。"; exit 1; fi
latest=$(echo "$tags" | tail -1)
echo "    共 $(echo "$tags" | wc -l) 个 tag，latest=$latest"

echo "==> 下载各版本 tarball"
for t in $tags; do
  echo "  - $t"
  if ! curl -fsSL --max-time 120 -o "$OUT/$t.tar.gz" "https://github.com/$REPO/archive/refs/tags/$t.tar.gz" 2>/dev/null; then
    # github 302 到 codeload 偶发失败时的兜底
    curl -fsSL --max-time 120 -o "$OUT/$t.tar.gz" "https://codeload.github.com/$REPO/tar.gz/refs/tags/$t" 2>/dev/null \
      || echo "    警告：$t 下载失败"
  fi
done

echo "==> 生成 versions.json"
tags_json=$(echo "$tags" | sed 's/.*/"&"/' | paste -sd, -)
printf '{\n  "latest": "%s",\n  "tags": [%s]\n}\n' "$latest" "$tags_json" > "$OUT/versions.json"

echo "==> 复制最新控制台脚本（便于国内首次引导）"
curl -fsSL --max-time 30 -o "$OUT/sa-console.sh" "https://raw.githubusercontent.com/$REPO/main/sa-console.sh" 2>/dev/null \
  && chmod +x "$OUT/sa-console.sh" \
  || echo "    警告：sa-console.sh 复制失败（不影响 tarball 镜像）"

echo "==> 完成。请把 $OUT 通过 Web 服务暴露为 https，例如："
echo "      https://<你的域名>/site_analytics-mirror/"
echo "   然后在国内服务器执行："
echo "      echo 'https://<你的域名>/site_analytics-mirror' > /安装目录/.update_mirror"
echo "   之后 sa-console 的 升级/回滚 即走镜像。"
