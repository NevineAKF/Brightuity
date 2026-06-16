FROM alpine:3.20

RUN apk add --no-cache squid

COPY squid.conf /etc/squid/squid.conf

# Initialize Squid's swap directory before first run.
# Safe to run even with "cache deny all" — creates the directory structure squid expects.
RUN squid -z -f /etc/squid/squid.conf 2>&1 || true

EXPOSE 3128

# -N = no daemon mode (foreground). Required so Docker captures the process.
CMD ["squid", "-f", "/etc/squid/squid.conf", "-N"]
