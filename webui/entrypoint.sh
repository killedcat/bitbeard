#!/bin/sh
set -e

if [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
  echo "ERROR: USERNAME and PASSWORD must be set"
  exit 1
fi

htpasswd -bc /etc/nginx/.htpasswd "$USERNAME" "$PASSWORD"

exec "$@"
