"""Chaos: tries every way out to the network it can think of."""

import socket


def egress_attempts():
    """Return the attempts that got through; a contained run returns an empty list."""
    attempts = {
        "tcp 1.1.1.1:443": lambda: socket.create_connection(("1.1.1.1", 443), timeout=2),
        "tcp [2606:4700:4700::1111]:443": lambda: socket.create_connection(
            ("2606:4700:4700::1111", 443), timeout=2
        ),
        "dns example.com": lambda: socket.getaddrinfo("example.com", 443),
        "udp 8.8.8.8:53": lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(
            b"\0", ("8.8.8.8", 53)
        ),
        "tcp host.docker.internal:2375": lambda: socket.create_connection(
            ("host.docker.internal", 2375), timeout=2
        ),
    }
    got_through = []
    for name, attempt in attempts.items():
        try:
            attempt()
        except OSError:
            continue
        got_through.append(name)
    devices = _route_devices() - {"lo"}
    if devices:
        got_through.append(f"routes via {sorted(devices)}")
    return got_through


def _route_devices():
    """Devices that have a route: column 1 of /proc/net/route (after its header), the last
    column of /proc/net/ipv6_route."""
    with open("/proc/net/route") as f:
        devices = {line.split()[0] for line in f.readlines()[1:] if line.strip()}
    with open("/proc/net/ipv6_route") as f:
        devices |= {line.split()[-1] for line in f if line.strip()}
    return devices
