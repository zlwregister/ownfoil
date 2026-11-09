# Hardened Ownfoil for your DS218+

This fork reduces specific risks; it is not a security guarantee. Keep independent
backups of important NAS data. A container shares the NAS kernel and its bridge
network can still reach other LAN services.

## Image builds and installation

Every push to `master` runs tests and a dependency audit, builds **linux/amd64**
(DS218+), starts a restricted container for a smoke test, then publishes:

```
ghcr.io/zlwregister/ownfoil:hardened
ghcr.io/zlwregister/ownfoil:sha-FULL_COMMIT_ID
```

Use the commit tag or published image digest when you want a fixed version.
`hardened` moves after a successful build. A fixed version still needs planned
security updates. No Docker Hub password is required by the GitHub build.

The workflow also uploads `ownfoil-synology-amd64`, a ZIP artifact containing
`ownfoil-ds218plus.tar` and its SHA-256 checksum. Download it from your successful
GitHub Actions run and unzip it. In DSM 7.1:

1. Docker > Image > Add > Add from file.
2. Select `ownfoil-ds218plus.tar` and wait for import.
3. Select the imported image and launch it with the settings below.

GitHub Container Registry images do **not** appear in the NAS's default Docker Hub
Registry search. Importing the TAR avoids registry-login and search problems.
Alternatively use SSH: `sudo docker pull ghcr.io/zlwregister/ownfoil:hardened`.
GHCR packages initially may be private, even for a public repository. Set the
package's visibility to Public in GitHub package settings for anonymous pulls, or
authenticate Docker to GHCR with an appropriately scoped token. Never put a token
in a command you share or in this repository. TAR import does not need GHCR access.

## NAS permissions and runtime settings

Create a dedicated NAS user such as `ownfoil-svc`, outside the administrators group.
Grant it read-only access to the exact game directory, read/write access to two
dedicated Ownfoil config/data folders, and no access to private documents/backups.
Do not reuse a DSM admin password for Ownfoil.

The image runs as numeric UID/GID **1000:1000** by default. Synology user IDs are
usually different. For least privilege, use Compose/SSH and set `user: UID:GID` to
the dedicated NAS user's IDs (`id ownfoil-svc`). Do not use PUID/PGID or root: the
old root startup and recursive chown were removed. If the old Synology wizard
cannot set the runtime UID/GID, use Compose instead of granting broad permissions.
Pre-create the two writable directories and give only that user write permission.

Copy `.env.example` to `.env`, fill in IDs, exact paths, NAS LAN IP and unique
passwords. Protect `.env` from other NAS users; Docker administrators can also
inspect environment credentials. The file is gitignored.

With SSH, in the deployment folder containing `.env`, `docker-compose.yml`,
`config/`, and `data/`, run:

```
sudo docker-compose up -d
```

On newer installations use `sudo docker compose up -d` instead. The Compose
configuration includes read-only games, a read-only container root, writable tmpfs,
all capabilities dropped, no-new-privileges, and process/memory limits.

If using the GUI, minimally configure:

| Setting | Value |
| --- | --- |
| High privilege | Off |
| Network | bridge |
| Port | TCP 8465 to 8465 |
| Game folder | `/games`, read-only |
| Dedicated config folder | `/app/config`, read/write |
| Dedicated data folder | `/app/data`, read/write |
| `USER_ADMIN_NAME` / `USER_ADMIN_PASSWORD` | Unique Ownfoil administrator credentials |
| `USER_GUEST_NAME` / `USER_GUEST_PASSWORD` | Separate shop-only Switch credentials |

The GUI setup does not automatically reproduce all Compose hardening controls.
Use Compose for the recommended configuration. The app refuses root and refuses
startup with no admin account; there is no open first-run signup window.

Restrict inbound TCP 8465 with the DSM firewall to your management computer and
Switch IPs. Do not expose it through router forwarding/public reverse proxies.
HTTP on your LAN is unencrypted, so use unique credentials and trusted networks.
Keep bridge networking and enter the NAS address manually in the Switch client;
host networking is unnecessary. Do not mount `/volume1`, `/`, or `docker.sock`.

Open `http://NAS_IP:8465`, sign in, use `/games` as the library path, and follow
the Setup page. Use the shop-only account on your Switch.

## Security changes and compatibility

- Pillow upgraded to 13.0.0. Image input limited to JPEG/PNG/WebP, 10 MiB, 16M pixels.
- Artwork accepts only HTTPS on `nintendo.com`/`nintendo.net` and subdomains by
  default. DNS addresses must all be public; connections pin a validated IP while
  checking TLS against the original hostname. Redirects are revalidated, bodies
  bounded, proxies ignored, and reads timed out. DNS lookup timing is OS-controlled.
- Other trusted CDN domains can be explicitly added with `OWNFOIL_ARTWORK_HOSTS`
  (comma-separated domain roots). Do not add untrusted domains. Non-allowlisted
  artwork will fail to cache; some upstream UI paths may still hotlink artwork.
- CSRF tokens for browser writes; same-origin checks including WebSockets;
  non-browser Basic-auth clients remain supported. Browser cookies use SameSite
  Strict/HttpOnly. Reverse-proxy HTTPS would require deliberate cookie/origin setup.
- Login redirects restricted to local paths, and failed browser/Basic authentication
  limited per client IP (10 failures per five minutes). Limiter state is in-memory
  and resets at restart; it is not a substitute for firewall controls.
- Last admin cannot be deleted through the user API; deployed app returns 503 if
  no admin remains. Startup requires environment credentials or an existing admin.
- Default image is non-root; no runtime recursive ownership changes or sudo.
- Runtime Python packages are version/hash-locked; base image is digest-pinned.
  Build/test actions are pinned where updated. Update these pins for future fixes.

Tests and scans do not establish absence of unknown vulnerabilities. Binary game
parsers, third-party packages, upstream metadata, DSM and Docker remain trust and
maintenance dependencies.
