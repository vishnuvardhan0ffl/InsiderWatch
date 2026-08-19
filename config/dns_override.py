"""Resolve *.polymarket.com over DNS-over-HTTPS when the local resolver
intercepts them. Changes only which resolver answers the lookup; not a
VPN or proxy, does not conceal the client IP."""
import socket, sys

_orig = socket.getaddrinfo
_cache = {}


def _doh(hostname):
    import requests
    try:
        r = requests.get("https://cloudflare-dns.com/dns-query",
                         params={"name": hostname, "type": "A"},
                         headers={"Accept": "application/dns-json"},
                         timeout=10)
        r.raise_for_status()
        for a in r.json().get("Answer", []):
            if a.get("type") == 1:
                return a.get("data")
    except Exception as e:
        print(f"  [dns_override] DoH failed for {hostname}: {e}", file=sys.stderr)
    return None


def _patched(host, port, family=0, type=0, proto=0, flags=0):
    if isinstance(host, str) and host.endswith("polymarket.com"):
        ip = _cache.get(host) or _doh(host)
        if ip:
            _cache[host] = ip
            return _orig(ip, port, family, type, proto, flags)
    return _orig(host, port, family, type, proto, flags)


def install_dns_override(force=None):
    socket.getaddrinfo = _patched
    print("  [dns_override] Active: polymarket.com via DoH.", file=sys.stderr)
    return True
