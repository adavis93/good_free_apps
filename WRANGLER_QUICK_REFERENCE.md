# Cloudflare Worker Quick Reference
## Common Commands for Good Free Apps

---

## Setup (One-time)

```bash
# Install Wrangler globally
npm install -g wrangler

# Login to Cloudflare
wrangler login

# Create KV namespace
wrangler kv:namespace create "ANALYTICS_KV"

# Set admin token (environment variable)
wrangler secret put ADMIN_TOKEN
```

---

## Deployment

```bash
# Deploy Worker (from directory with wrangler.toml)
wrangler deploy

# Deploy with verbose output
wrangler deploy --verbose
```

---

## Monitoring & Debugging

```bash
# View live Worker logs (leave running in a terminal)
wrangler tail

# View recent logs
wrangler tail --tail 100

# Filter logs by status code
wrangler tail --status error
```

---

## KV Data Management

```bash
# List all keys in KV namespace
wrangler kv:key list --binding ANALYTICS_KV

# Get a specific key's value
wrangler kv:key get "events:2026-02-12:123456:abc" --binding ANALYTICS_KV

# Delete a specific key
wrangler kv:key delete "events:2026-02-12:123456:abc" --binding ANALYTICS_KV

# List keys with a prefix (e.g., all feedback)
wrangler kv:key list --binding ANALYTICS_KV --prefix "feedback:"

# List all stats for a specific date
wrangler kv:key list --binding ANALYTICS_KV --prefix "stats:2026-02-12"
```

---

## Managing Secrets

```bash
# Set/update admin token
wrangler secret put ADMIN_TOKEN

# List all secrets (shows names only, not values)
wrangler secret list

# Delete a secret
wrangler secret delete ADMIN_TOKEN
```

---

## Rollback & Version Management

```bash
# Rollback to previous deployment
wrangler rollback

# List deployment history
wrangler deployments list
```

---

## Development & Testing

```bash
# Run Worker locally for testing
wrangler dev

# Run with specific port
wrangler dev --port 8787

# Test with local KV preview
wrangler dev --local
```

---

## Common Tasks

### Export all feedback to a file
```bash
wrangler kv:key list --binding ANALYTICS_KV --prefix "feedback:" > feedback-keys.txt
```

Then manually fetch each key and save to a file.

### Check how much KV storage you're using
Go to Cloudflare Dashboard → Workers & Pages → KV → View namespace

Or count keys:
```bash
wrangler kv:key list --binding ANALYTICS_KV | wc -l
```

### Clear all data (DANGEROUS - use carefully!)
```bash
# Get list of all keys
wrangler kv:key list --binding ANALYTICS_KV

# Then delete each key manually, or write a script
```

---

## Troubleshooting

### Worker won't deploy
```bash
# Check wrangler.toml syntax
wrangler deploy --dry-run

# Update Wrangler
npm update -g wrangler
```

### Can't access KV data
```bash
# Verify binding name matches wrangler.toml
cat wrangler.toml | grep binding

# Check namespace ID
cat wrangler.toml | grep id
```

### Logs aren't showing
```bash
# Make sure you're in the right project
wrangler whoami

# Try with account/worker name explicitly
wrangler tail --name good-free-apps-api
```

---

## Useful Links

- **Cloudflare Dashboard**: https://dash.cloudflare.com/
- **Workers Docs**: https://developers.cloudflare.com/workers/
- **KV Docs**: https://developers.cloudflare.com/kv/
- **Wrangler Docs**: https://developers.cloudflare.com/workers/wrangler/

---

## Emergency Commands

```bash
# Disable Worker (delete it)
wrangler delete

# Re-deploy from scratch
wrangler deploy --force
```

---

## Pro Tips

1. **Keep `wrangler tail` running** in a terminal when testing
2. **Use meaningful KV key names** - they're easier to debug
3. **Check your usage** regularly: Dashboard → Workers & Pages → Usage
4. **Backup important data** before major changes
5. **Test in incognito** to avoid caching issues

---

## Daily Workflow

When actively working on the Worker:

```bash
# Terminal 1: Edit code
vim worker.js

# Terminal 2: Watch logs
wrangler tail

# Terminal 3: Deploy & test
wrangler deploy
curl https://good-free-apps-api.YOUR-SUBDOMAIN.workers.dev/api/dashboard
```
