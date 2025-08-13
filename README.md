# Bitbeard

Bitbeard is a Discord bot that integrates with qBittorrent, Jackett, and Plex for automated media management.

## Quick Setup

1. **Environment Configuration**
   - Copy `.env.example` to `.env`
   - Update the environment variables with your specific values
   - Put your VPN config file in ./openvpn; NordVPN included by default

2. **Start Services**
   ```bash
   docker-compose up -d
   ```

3. **Configure Services**
   - **Jackett**: Visit `http://localhost:9117` to add trackers
   - **Plex**: Visit `http://localhost:32400` to complete setup


## Security Warnings

**Bitbeard has some config defaults for jackett and qbittorrent. He's got defaults that can be exploited if you port forward for remote management.**

- **qBittorrent**: If you expose port 8080 externally, **change the default password**.
- **Jackett**: If you expose port 9117 externally, **change the API key**.
