# Deployment Guide

## Environments

| Environment | Path | Port | Purpose | Branch |
|------------|------|------|---------|--------|
| Development | `/home/roju/lastfm-dev` | N/A | AI workspace | `ai/development` |
| Staging | `/home/roju/lastfm-staging` | 8002 | Testing environment | Follows `main` |
| Production | `/home/roju/New-Last.FM-Project` | 8001 | Live site | `main` |

## Deployment Workflow

```
┌─────────────────────────┐
│  ai/development branch  │  ← AI makes changes here
└───────────┬─────────────┘
            │ Create PR
            ↓
┌─────────────────────────┐
│   Pull Request #X       │  ← CI runs tests
└───────────┬─────────────┘
            │ Merge to main
            ↓
┌─────────────────────────┐
│   main branch           │  ← PR merged
└───────────┬─────────────┘
            │ Auto-trigger
            ↓
┌─────────────────────────┐
│   Staging deploys       │  ← Automatic (port 8002)
│   (reset to main)       │
└───────────┬─────────────┘
            │ Manual testing
            ↓
┌─────────────────────────┐
│   Manual trigger        │  ← Human approval required
└───────────┬─────────────┘
            │
            ↓
┌─────────────────────────┐
│   Production deploys    │  ← Manual (port 8001)
└─────────────────────────┘
```

## Required GitHub Secrets

Configure these in: **Settings → Secrets and variables → Actions**

| Secret | Description | Example |
|--------|-------------|---------|
| `HOST` | Server hostname/IP | `192.168.1.100` |
| `USERNAME` | SSH username | `roju` |
| `SSH_PRIVATE_KEY` | Private SSH key (contents of ~/.ssh/id_rsa) | `-----BEGIN OPENSSH PRIVATE KEY-----...` |
| `PORT` | SSH port (optional, defaults to 22) | `22` |

The application service must also provide a stable, randomly generated
`SECRET_KEY` environment variable. It signs the admin session used for CSRF
protection. Generate one with `python -c "import secrets; print(secrets.token_hex(32))"`.

Set `SESSION_COOKIE_SECURE=1` when the application is served exclusively over
HTTPS. `TRUSTED_PROXY_HOPS` defaults to `1` for the production topology. Set it
to the exact number of reverse proxies in front of Gunicorn, or `0` when the
application is exposed directly. Each trusted proxy must replace, rather than
append to, forwarding headers supplied by clients.

### Generating SSH Keys

If you don't have SSH keys set up:

```bash
# Generate new key pair
ssh-keygen -t ed25519 -C "github-actions" -f ~/.ssh/github_actions

# Add public key to authorized_keys
cat ~/.ssh/github_actions.pub >> ~/.ssh/authorized_keys

# Copy private key content to GitHub Secrets
cat ~/.ssh/github_actions
```

## Workflows

### 1. CI Workflow (`.github/workflows/ci.yml`)

**Triggers:**
- Pull requests to `main` or `staging`
- Pushes to `main`, `staging`, or `ai/development`

**Actions:**
- Lints code with flake8
- Runs pytest tests
- Runs Bandit security scan

### 2. Staging Deployment (`.github/workflows/deploy-staging.yml`)

**Trigger:** Automatic (when PR to `main` is merged)

**Actions:**
1. Connects to server via SSH
2. Changes to `/home/roju/lastfm-staging`
3. Resets staging branch to match `origin/main`
4. Updates dependencies
5. Restarts `lastfm-staging.service`
6. Runs health check on port 8002

### 3. Production Deployment (`.github/workflows/deploy.yml`)

**Trigger:** Manual only (`workflow_dispatch`)

**Actions:**
1. Connects to server via SSH
2. Changes to `/home/roju/New-Last.FM-Project`
3. Pulls latest from `main`
4. Backs up database
5. Updates dependencies
6. Restarts `lastfm.service`
7. Runs health check on port 8001

## Manual Production Deployment

### Option 1: GitHub Web UI

1. Go to: **Actions → "Deploy to Production"**
2. Click **"Run workflow"**
3. Select `main` branch
4. Click **"Run workflow"**

### Option 2: GitHub CLI

```bash
# Trigger production deployment
gh workflow run deploy.yml

# View workflow run status
gh run watch

# View recent runs
gh run list --workflow=deploy.yml
```

### Option 3: Direct SSH (Emergency Only)

```bash
# SSH into server
ssh roju@your-server

# Change to production directory
cd /home/roju/New-Last.FM-Project

# Pull latest changes
git pull origin main

# Update dependencies
source .venv/bin/activate
pip install -r requirements.txt

# Restart service
sudo systemctl restart lastfm

# Check status
sudo systemctl status lastfm
curl http://localhost:8001
```

## Services

### View Service Status

```bash
# Production
sudo systemctl status lastfm

# Staging
sudo systemctl status lastfm-staging
```

### Restart Services

```bash
# Production
sudo systemctl restart lastfm

# Staging
sudo systemctl restart lastfm-staging
```

### View Logs

```bash
# Application logs (rotating daily)
tail -f logs/app_$(date +%Y%m%d).log

# Service logs
sudo journalctl -u lastfm -f
sudo journalctl -u lastfm-staging -f
```

## Troubleshooting

### Deployment Fails with SSH Error

**Problem:** `Permission denied (publickey)`

**Solution:**
1. Verify SSH private key is in GitHub Secrets
2. Ensure public key is in `~/.ssh/authorized_keys` on server
3. Check SSH key permissions: `chmod 600 ~/.ssh/github_actions`

### Service Fails to Start

**Problem:** `Service failed to start!`

**Solution:**
```bash
# Check detailed error
sudo journalctl -u lastfm -n 50

# Common issues:
# - Port already in use: sudo lsof -i :8001
# - Virtual environment not activated: source .venv/bin/activate
# - Missing dependencies: pip install -r requirements.txt
```

### Health Check Fails

**Problem:** `curl: (22) The requested URL returned error: 404`

**Solution:**
```bash
# Check if service is actually running
curl http://localhost:8001

# Check application logs
tail -f logs/app_$(date +%Y%m%d).log

# Manually restart if needed
sudo systemctl restart lastfm
```

### Database Issues

**Problem:** Deployment succeeds but app errors

**Solution:**
```bash
# Backup current database
python -m app.services.backup_db

# Check database integrity
sqlite3 files/lastfmstats.sqlite "PRAGMA integrity_check;"
```

## Rolling Back

### Staging Rollback

Staging automatically resets to `main`, so to rollback staging:

```bash
cd /home/roju/lastfm-staging
git fetch origin
git reset --hard origin/<commit-hash>
sudo systemctl restart lastfm-staging
```

### Production Rollback

```bash
cd /home/roju/New-Last.FM-Project

# Option 1: Revert to specific commit
git reset --hard <commit-hash>
sudo systemctl restart lastfm

# Option 2: Revert last commit
git revert HEAD
sudo systemctl restart lastfm

# Option 3: Restore from backup
python -m app.services.backup_db --restore files/backups/lastfm_backup_YYYYMMDD_HHMMSS.sqlite
```

## Security Notes

1. **SSH Keys**: Never commit private keys to the repository
2. **Secrets**: Always use GitHub Secrets for sensitive data
3. **Backups**: Database backups run automatically before production deployments
4. **Access**: Production deployments require manual approval
5. **Services**: Services run as non-root user with `sudo` only for restart
