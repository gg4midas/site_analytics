#!/usr/bin/env bash
# 下载并更新 GeoIP 城市库 + ASN（运营商）库。
# 两种数据源：
#   1) MaxMind GeoLite2（默认）：需免费 License Key，同时下载 City 与 ASN 两个库
#      GEOIP_LICENSE_KEY=你的Key ./update_geoip.sh
#   2) db-ip 免费库（免 Key，无需注册）：下载 City 与 ASN 两个库
#      ./update_geoip.sh --dbip
# 产出：geoip/GeoLite2-City.mmdb（地域）+ geoip/GeoLite2-ASN.mmdb（运营商），app.py 已兼容两种内部格式。
# 免费申请 MaxMind Key: https://www.maxmind.com/ (My Account -> Generate License Key)
set -e

# 参数解析
SOURCE="maxmind"
for a in "$@"; do
  case "$a" in
    --dbip) SOURCE="dbip" ;;
  esac
done

DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$DIR/geoip"
TMP="$(mktemp -d)"
mkdir -p "$OUT"

if [ "$SOURCE" = "dbip" ]; then
  YM="$(date +%Y-%m)"
  URL="https://download.db-ip.com/free/dbip-city-lite-$YM.mmdb.gz"
  echo "下载 db-ip 免费城市库 ($YM) ..."
  curl -fsSL -L "$URL" -o "$TMP/dbip.mmdb.gz"
  gunzip -c "$TMP/dbip.mmdb.gz" > "$OUT/GeoLite2-City.mmdb"
  # ASN（运营商）库
  ASN_URL="https://download.db-ip.com/free/dbip-asn-lite-$YM.mmdb.gz"
  echo "下载 db-ip 免费 ASN 库 ($YM) ..."
  if curl -fsSL -L "$ASN_URL" -o "$TMP/dbip-asn.mmdb.gz"; then
    gunzip -c "$TMP/dbip-asn.mmdb.gz" > "$OUT/GeoLite2-ASN.mmdb"
  else
    echo "[warn] db-ip ASN 库下载失败，运营商识别将不可用（不影响其它功能）。" >&2
  fi
else
  KEY="${GEOIP_LICENSE_KEY:-$1}"
  if [ -z "$KEY" ]; then
    echo "缺少 MaxMind License Key。"
    echo "用法: GEOIP_LICENSE_KEY=你的Key ./update_geoip.sh   （或 ./update_geoip.sh --dbip 免 Key）"
    echo "免费申请: https://www.maxmind.com/ (My Account -> Generate License Key)"
    exit 1
  fi
  URL="https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=${KEY}&suffix=tar.gz"
  echo "下载 GeoLite2-City ..."
  curl -fsSL -L "$URL" -o "$TMP/geo.tar.gz"
  tar -xzf "$TMP/geo.tar.gz" -C "$TMP"
  find "$TMP" -name 'GeoLite2-City.mmdb' -exec mv {} "$OUT/GeoLite2-City.mmdb" \;
  # ASN（运营商）库：同一个 License Key，edition_id=GeoLite2-ASN
  ASN_URL="https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-ASN&license_key=${KEY}&suffix=tar.gz"
  echo "下载 GeoLite2-ASN ..."
  if curl -fsSL -L "$ASN_URL" -o "$TMP/asn.tar.gz"; then
    tar -xzf "$TMP/asn.tar.gz" -C "$TMP"
    find "$TMP" -name 'GeoLite2-ASN.mmdb' -exec mv {} "$OUT/GeoLite2-ASN.mmdb" \;
  else
    echo "[warn] GeoLite2-ASN 下载失败，运营商识别将不可用（不影响其它功能）。" >&2
  fi
fi

rm -rf "$TMP"

if [ -f "$OUT/GeoLite2-City.mmdb" ]; then
  echo "已更新: $OUT/GeoLite2-City.mmdb"
  if [ -f "$OUT/GeoLite2-ASN.mmdb" ]; then
    echo "已更新: $OUT/GeoLite2-ASN.mmdb（运营商识别）"
  fi
  echo "重启 app.py 即可生效（数据库在启动时加载，更新后需重启后端）。"
else
  echo "更新失败：未找到 GeoLite2-City.mmdb" >&2
  exit 1
fi
