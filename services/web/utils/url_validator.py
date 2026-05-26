import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_NETWORKS = [
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('fd00::/8'),
    ipaddress.ip_network('fe80::/10'),
]


def _is_private(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in _BLOCKED_NETWORKS)
    except ValueError:
        return False


def block_private_url(url: str) -> None:
    """Raises ValueError if url targets a private/internal address (SSRF guard)."""
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError('Dozwolone są tylko adresy http:// i https://.')
    hostname = parsed.hostname
    if not hostname:
        raise ValueError('Brak nazwy hosta w URL.')
    if hostname.lower() == 'localhost':
        raise ValueError('Połączenia do adresów wewnętrznych są niedozwolone.')
    if _is_private(hostname):
        raise ValueError('Połączenia do adresów wewnętrznych są niedozwolone.')
    try:
        resolved = socket.gethostbyname(hostname)
        if _is_private(resolved):
            raise ValueError('Połączenia do adresów wewnętrznych są niedozwolone.')
    except socket.gaierror:
        pass
