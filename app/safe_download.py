"""HTTPS artwork downloads: allowlisted hosts, pinned public IPs, bounded bodies.

Resolve once per hop and connect to the validated IP with the original TLS SNI
and certificate hostname. This prevents a second DNS lookup/rebinding and ignores
ambient proxy credentials. Every redirect is independently validated.
"""
import ipaddress
import os
import socket
import time
from urllib.parse import urljoin, urlsplit

import requests
import urllib3

MAX_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 30
MAX_REDIRECTS = 3
DEFAULT_HOSTS = 'nintendo.com,nintendo.net'


def destination(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower().rstrip('.')
    allowed = [h.strip().lower().rstrip('.') for h in
               os.environ.get('OWNFOIL_ARTWORK_HOSTS', DEFAULT_HOSTS).split(',') if h.strip()]
    if (parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or not host
            or not any(host == h or host.endswith('.' + h) for h in allowed)):
        raise ValueError('Artwork URL must use HTTPS on an allowed artwork host')
    addresses = {entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    if not addresses:
        raise ValueError('Artwork host has no addresses')
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (not ip.is_global or ip.is_multicast or ip.is_reserved
                or (ip.version == 6 and ip.ipv4_mapped is not None)):
            raise ValueError('Artwork host must resolve only to public addresses')
    return parsed, host, sorted(addresses)[0]


def fetch_artwork(url):
    deadline = time.monotonic() + MAX_SECONDS
    for _ in range(MAX_REDIRECTS + 1):
        parsed, host, address = destination(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('Artwork download exceeded time limit')
        pool = urllib3.HTTPSConnectionPool(
            address, port=443, assert_hostname=host, server_hostname=host,
            cert_reqs='CERT_REQUIRED', ca_certs=requests.certs.where(),
            timeout=urllib3.Timeout(connect=min(10, remaining), read=min(10, remaining)))
        response = None
        try:
            target = parsed.path or '/'
            if parsed.query:
                target += '?' + parsed.query
            response = pool.urlopen('GET', target, headers={'Host': host, 'Accept-Encoding': 'identity'},
                                    redirect=False, retries=False, preload_content=False)
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get('Location')
                if not location:
                    raise ValueError('Artwork redirect is missing a destination')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(f'Artwork server returned HTTP {response.status}')
            length = response.headers.get('Content-Length')
            if length and int(length) > MAX_BYTES:
                raise ValueError('Artwork exceeds size limit')
            if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise ValueError('Compressed HTTP artwork bodies are not supported')
            body = bytearray()
            while True:
                # read1 returns after one underlying read. stream/read can wait
                # for a whole chunk while a peer drips bytes below the idle timeout.
                if time.monotonic() > deadline:
                    raise ValueError('Artwork download exceeded time limit')
                chunk = response.read1(65536, decode_content=False)
                if not chunk:
                    break
                if len(body) + len(chunk) > MAX_BYTES:
                    raise ValueError('Artwork exceeds size limit')
                body.extend(chunk)
            return bytes(body)
        finally:
            if response is not None:
                response.close()
            pool.close()
    raise ValueError('Too many artwork redirects')
