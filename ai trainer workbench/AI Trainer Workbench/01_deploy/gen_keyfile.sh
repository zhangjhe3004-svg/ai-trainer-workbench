#!/usr/bin/env bash
# 生成副本集内部认证的 keyFile，并设置 400 权限
set -e
mkdir -p /data/mongo
openssl rand -base64 756 > /data/mongo/keyfile
chmod 400 /data/mongo/keyfile
for p in 27017 27018 27019; do
  mkdir -p /data/mongo/rs0_$p
done
echo "keyFile 已生成：/data/mongo/keyfile"
