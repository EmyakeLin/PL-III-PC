"""Select a local listening interface and the browser origins for one room."""

import ipaddress
import re
import socket
from urllib.parse import urlsplit

_PRIVATE_LANS = tuple(map(ipaddress.IPv4Network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))


def ipv4_address(value):
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        raise ValueError("监听地址须为本机网卡的 IPv4 地址。") from None
    if address.is_unspecified or address.is_multicast or address.is_reserved:
        raise ValueError("请选择一张本机网卡的具体 IPv4 地址。")
    return str(address)


def lan_address():
    # Ask the OS which interface it would route through. UDP connect does not send a packet.
    candidates = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect(("192.0.2.1", 9))
            candidates.append(route.getsockname()[0])
    except OSError:
        pass
    # Also works on an isolated LAN with no default route.
    try:
        interfaces = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
        candidates.extend(sockaddr[0] for *_, sockaddr in interfaces)
    except OSError:
        pass
    fallback = None
    for host in dict.fromkeys(candidates):
        try:
            address = ipv4_address(host)
            if ipaddress.IPv4Address(address).is_loopback:
                continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind((address, 0))
            # A VPN can own the default route even when another interface is on the home LAN.
            if any(ipaddress.IPv4Address(address) in lan for lan in _PRIVATE_LANS):
                return address
            fallback = fallback or address
        except (OSError, ValueError):
            continue
    if fallback:
        return fallback
    raise ValueError("未找到可供其他设备访问的 IPv4 地址，请用 --address 指定本机局域网网卡。")


def https_origin(value):
    """Canonical HTTPS origin of an explicitly configured reverse proxy."""
    error = "公开地址应为 HTTPS 来源，例如 https://game.example，可附端口。"
    if not value or any(c in value for c in "?#\\%") or any(
            c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(error)
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username is not None
                or url.password is not None or url.path not in ("", "/") or url.port == 0
                or url.netloc.endswith(":")):
            raise ValueError(error)
        port = url.port
        host = url.hostname.encode("idna").decode("ascii")
        if url.netloc.startswith("["):
            if not re.fullmatch(r"\[[a-fA-F0-9:.]+\](?::[0-9]+)?", url.netloc):
                raise ValueError(error)
            host = "[" + str(ipaddress.IPv6Address(host)) + "]"
        elif len(host) > 253 or any(not re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
            raise ValueError(error)
    except (ValueError, UnicodeError):
        raise ValueError(error) from None
    return "https://" + host + (f":{port}" if port not in (None, 443) else "")


def http_origin(address, port):
    return f"http://{address}" + (f":{port}" if port != 80 else "")


def allowed_origins(address, port, public_url):
    # Keep localhost aliases in local mode. A LAN listener is bound to its one interface.
    hosts = (address, "localhost") if address == "127.0.0.1" else (address,)
    origins = {http_origin(host, port) for host in hosts}
    if public_url:
        origins.add(public_url)
    allowed = set()
    for origin in origins:
        url = urlsplit(origin)
        allowed.add((url.netloc, origin))
        if url.port is None:
            default = 443 if url.scheme == "https" else 80
            allowed.add((f"{url.netloc}:{default}", origin))
    return allowed
