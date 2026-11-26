"""Which front end a request came through, and from where (step 12b).

People never call the API directly: their browser talks to one of the two
Next.js servers (the applicant portal or the staff app), and that server calls
the API. So the API can't see the browser itself. Each front end's server
says, on every call:

    X-Portal-Key      its own secret key: which front end this is
    X-Forwarded-Host  the address the browser opened (e.g. staff.motie.gov.gm)
    X-Client-IP       the browser's IP address, as the HTTPS proxy (Caddy) saw it

The two forwarded headers are believed only when the key is right: anyone
can type headers, but only our own servers know a key. A request without a
valid key gets no portal, and its IP is the connection's own address.
"""

import hmac
from dataclasses import dataclass
from ipaddress import IPv6Address, ip_address
from typing import Literal

from fastapi import Request

from app.core.config import settings

Portal = Literal["staff", "applicant"]
PORTALS: tuple[Portal, ...] = ("staff", "applicant")


@dataclass(frozen=True)
class Channel:
    portal: Portal | None
    host: str | None  # lower case, without a port
    client_ip: str | None


def _portal_from_key(key: str | None) -> Portal | None:
    if not key:
        return None
    for portal in PORTALS:
        expected = settings.portal_key(portal)
        # compare_digest takes as long whatever the first wrong character is,
        # so timing can't reveal the key one character at a time.
        if expected and hmac.compare_digest(key.encode(), expected.encode()):
            return portal
    return None


def _host_only(value: str | None) -> str | None:
    if not value:
        return None
    host = value.split(",")[0].strip().lower()
    if host.startswith("["):  # an IPv6 address: [::1]:3000
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def read_channel(request: Request) -> Channel:
    portal = _portal_from_key(request.headers.get("x-portal-key"))
    if portal is None:
        return Channel(portal=None, host=None, client_ip=request.client.host if request.client else None)
    ip = (request.headers.get("x-client-ip") or "").strip() or None
    return Channel(portal=portal, host=_host_only(request.headers.get("x-forwarded-host")), client_ip=ip)


def came_through(channel: Channel, portal: Portal) -> bool:
    """Did this request come through `portal`, on one of its own domains?"""
    if channel.portal != portal:
        return False
    # Office mode (step 13a): there is no applicant portal at all.
    if portal == "applicant" and not settings.applicant_portal_on():
        return False
    other = "applicant" if portal == "staff" else "staff"
    # E.g. a staff request "from" the public site's address: the staff app is
    # being reached through the wrong domain. Refuse it.
    if channel.host and channel.host in settings.portal_hosts(other):
        return False
    allowed = settings.portal_hosts(portal)
    return not allowed or channel.host in allowed


def staff_ip_allowed(channel: Channel) -> bool:
    """Is this request from a network staff may work from (STAFF_IP_ALLOWLIST)?
    Always yes when the check is off (development). With it on, a request whose
    IP we don't know is refused: the staff app behind Caddy always knows it."""
    if not settings.staff_ip_check_on():
        return True
    if not channel.client_ip:
        return False
    try:
        ip = ip_address(channel.client_ip)
    except ValueError:
        return False
    # An IPv4 address can arrive written as IPv6 ("::ffff:10.0.0.7").
    if isinstance(ip, IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in network for network in settings.staff_networks())


OUTSIDE_NETWORK_MESSAGE = "The staff app works only on the Ministry network or VPN."


def wrong_portal_message(needed: Portal) -> str:
    if needed == "staff":
        return "Ministry staff sign in through the staff app."
    return "Applicants sign in through the applicant portal."
