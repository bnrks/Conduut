import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

_DENYLIST_HOSTS = {
    "localhost",
    "metadata.google.internal",
}


class N8nUrlValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PinnedN8nUrl:
    """A public target whose HTTP socket cannot perform a second DNS lookup."""

    normalized_url: str
    pinned_url: str
    host_header: str
    sni_hostname: str


def normalize_customer_owned_n8n_url(raw_url: str) -> str:
    value = str(raw_url or "").strip()
    if not value:
        raise N8nUrlValidationError("n8n URL is required.")

    parsed = urlparse(value)
    if parsed.scheme.lower() != "https":
        raise N8nUrlValidationError("Production n8n URL must use HTTPS.")
    if not parsed.hostname:
        raise N8nUrlValidationError("n8n URL must include a hostname.")
    if parsed.username or parsed.password:
        raise N8nUrlValidationError("n8n URL must not include embedded credentials.")
    if parsed.query or parsed.fragment:
        raise N8nUrlValidationError("n8n URL must not include query or fragment parts.")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in _DENYLIST_HOSTS:
        raise N8nUrlValidationError("This n8n hostname is not allowed.")

    _assert_public_hostname(hostname)

    port = f":{parsed.port}" if parsed.port else ""
    normalized_path = parsed.path.rstrip("/")
    if parsed.path and not normalized_path:
        normalized_path = "/"
    if normalized_path == "/":
        normalized_path = ""
    return f"https://{hostname}{port}{normalized_path}"


def _assert_public_hostname(hostname: str) -> None:
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        _assert_public_ip(ip)
        return

    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise N8nUrlValidationError("n8n hostname could not be resolved.") from exc

    if not infos:
        raise N8nUrlValidationError("n8n hostname did not resolve to a public address.")

    for family, _, _, _, sockaddr in infos:
        address = sockaddr[0]
        ip = ipaddress.ip_address(address)
        _assert_public_ip(ip)
        if family not in (socket.AF_INET, socket.AF_INET6):
            raise N8nUrlValidationError("n8n hostname resolved to an unsupported network family.")


def pin_customer_owned_n8n_url(raw_url: str) -> PinnedN8nUrl:
    """Resolve, validate, and pin a customer origin for the immediately following request."""

    normalized_url = normalize_customer_owned_n8n_url(raw_url)
    parsed = urlparse(normalized_url)
    hostname = str(parsed.hostname or "")
    addresses = _public_addresses(hostname)
    address = addresses[0]
    pinned_host = f"[{address}]" if ipaddress.ip_address(address).version == 6 else address
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/")
    original_host = f"[{hostname}]" if ":" in hostname else hostname
    host_header = f"{original_host}{port}"
    return PinnedN8nUrl(
        normalized_url=normalized_url,
        pinned_url=f"https://{pinned_host}{port}{path}",
        host_header=host_header,
        sni_hostname=hostname,
    )


def _public_addresses(hostname: str) -> list[str]:
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise N8nUrlValidationError("n8n hostname could not be resolved.") from exc
        addresses: list[str] = []
        for family, _, _, _, sockaddr in infos:
            if family not in (socket.AF_INET, socket.AF_INET6):
                raise N8nUrlValidationError(
                    "n8n hostname resolved to an unsupported network family."
                )
            address = str(sockaddr[0])
            _assert_public_ip(ipaddress.ip_address(address))
            if address not in addresses:
                addresses.append(address)
        if not addresses:
            raise N8nUrlValidationError("n8n hostname did not resolve to a public address.")
        return addresses
    _assert_public_ip(ip)
    return [str(ip)]


def _assert_public_ip(ip: ipaddress._BaseAddress) -> None:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise N8nUrlValidationError("n8n URL must resolve to a public IP address.")
