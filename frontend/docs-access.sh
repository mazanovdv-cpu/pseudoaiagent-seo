#!/bin/sh
set -eu

if [ "${EXPOSE_API_DOCS:-1}" = "0" ]; then
    cat > /etc/nginx/docs-access.conf <<'EOF'
location = /api/docs { return 404; }
location = /api/docs/ { return 404; }
location = /api/redoc { return 404; }
location = /api/redoc/ { return 404; }
location = /api/openapi.json { return 404; }
EOF
else
    : > /etc/nginx/docs-access.conf
fi
