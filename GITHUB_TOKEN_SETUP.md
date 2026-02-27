# GitHub Token Setup Guide

## Why You Need a Token

Without a token, GitHub limits you to **60 requests per hour**. With a token, you get **5000 requests per hour**.

For syncing a repository with hundreds of files, you **need** a token.

---

## Quick Setup (2 minutes)

### Step 1: Create a Personal Access Token

1. Go to: https://github.com/settings/tokens
2. Click **"Generate new token (classic)"**
3. Fill in:
   - **Note**: `CodeParse Agent`
   - **Expiration**: `No expiration` (or your choice)
   - **Scope**: Check `public_repo` (for public repos only)
     - For private repos, check `repo` (full control)

4. Click **"Generate token"** at the bottom
5. **Copy the token immediately** (you won't see it again!)

### Step 2: Add Token to Environment

#### Option A: Export in Terminal (temporary)
```bash
export GITHUB_TOKEN=ghp_your_token_here
```

#### Option B: Add to .env file (permanent)
```bash
# Create/edit .env file
echo "GITHUB_TOKEN=ghp_your_token_here" >> .env

# The system will automatically load it
```

#### Option C: Add to sync_config.yaml
```yaml
# Add at the top of sync_config.yaml
github_token: ghp_your_token_here
```

### Step 3: Verify It Works

```bash
# Check rate limit status
curl -H "Authorization: Bearer ghp_your_token_here" https://api.github.com/rate_limit

# You should see:
# "rate": {
#   "limit": 5000,
#   "remaining": 4999,
#   ...
# }
```

---

## Using the Token

Once set, the token is automatically used:

```bash
# Token loaded from GITHUB_TOKEN env var
uv run python -m services.codeparse.cli sync --codebase olake --verbose

# You'll see in logs:
# GitHub token loaded from environment
# Using authenticated GitHub API (5000 req/hour limit)
```

---

## Token Security

### Best Practices

✅ **DO**:
- Store tokens in `.env` file (gitignored)
- Use environment variables
- Set expiration dates
- Use minimum required scope

❌ **DON'T**:
- Commit tokens to git
- Share tokens publicly
- Use tokens in client-side code
- Give more permissions than needed

### Check Your Token

```bash
# Verify token is working
curl -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/user

# Should return your user info
```

### Revoke a Token

1. Go to: https://github.com/settings/tokens
2. Find the token
3. Click **"Delete"**

---

## Troubleshooting

### "Bad credentials" error
- Token is invalid or expired
- Create a new token at https://github.com/settings/tokens

### "Rate limit exceeded" with token
- Token might not be loaded
- Check logs for "GitHub token loaded from environment"
- Verify `GITHUB_TOKEN` env var: `echo $GITHUB_TOKEN`

### "403 Forbidden" for private repos
- Token needs `repo` scope (not just `public_repo`)
- Create new token with full `repo` scope

---

## Rate Limits Comparison

| Type | Limit | Reset |
|------|-------|-------|
| **Unauthenticated** | 60/hour | Every hour |
| **Authenticated** | 5000/hour | Every hour |

For a repo with 500 files:
- **Without token**: ~8 syncs per hour (60/500 files)
- **With token**: ~10 syncs per hour (5000/500 files)

---

## Example: Complete Setup

```bash
# 1. Create token (via GitHub UI)
# Go to https://github.com/settings/tokens

# 2. Set environment variable
export GITHUB_TOKEN=ghp_abc123xyz

# 3. Verify
uv run python -m services.codeparse.cli status

# Should show:
# ✓ GitHub API: GitHub API is reachable

# 4. Sync
uv run python -m services.codeparse.cli sync --codebase olake --verbose

# Should show:
# GitHub token loaded from environment
# Using authenticated GitHub API (5000 req/hour limit)
```

---

## Alternative: GitHub App Token (Advanced)

For production use, consider creating a GitHub App:

1. Go to: https://github.com/settings/apps
2. Create new app
3. Generate private key
4. Install app on repositories
5. Use JWT to get installation access token

This provides:
- Higher rate limits (15000/hour)
- Per-installation limits
- Better audit trail

But for personal use, **Personal Access Token is sufficient**.

---

## Need Help?

```bash
# Check if token is loaded
uv run python -c "import os; print('Token set:', bool(os.getenv('GITHUB_TOKEN')))"

# Check rate limit
uv run python -c "
import os
import httpx
token = os.getenv('GITHUB_TOKEN', '')
headers = {'Authorization': f'Bearer {token}'} if token else {}
resp = httpx.get('https://api.github.com/rate_limit', headers=headers)
print(resp.json())
"
```
