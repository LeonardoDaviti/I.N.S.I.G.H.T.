# Docker Networking Configuration

## Cross-Service Communication

INSIGHT needs to access services on different Docker networks:

### Network Architecture

- **insight-network**: INSIGHT's internal network (db, api, frontend)
- **nitter-server_default**: Nitter's network (external)
- **telegram-private-net**: Telegram RSS network (external)

### Ingestion Container

The ingestion container joins **all three networks** to access:

| Service | Network | Internal URL | Why |
|---------|---------|--------------|-----|
| PostgreSQL | insight-network | `postgres:5432` | Save posts to DB |
| Nitter | nitter-server_default | `nitter:8082` | Fetch Twitter/X RSS |
| Telegram RSS | telegram-private-net | `telegram-rss:9504` | Fetch Telegram RSS |

### Source URLs

Use **Docker DNS names**, not IPs:

```json
{
  "platform": "rss",
  "handle_or_url": "http://nitter:8082/karpathy/rss",
  "enabled": true
}
```

**Do NOT use:**
- ❌ `http://localhost:8082` (container's own localhost)
- ❌ `http://192.168.1.164:8082` (won't work, port not exposed externally)
- ✅ `http://nitter:8082` (Docker DNS)

### Port Binding Security

Nitter and Telegram RSS bind to `127.0.0.1` (localhost only):
- Secure: Not accessible from network
- Docker containers can still reach via internal networks
- No need to expose ports to host network