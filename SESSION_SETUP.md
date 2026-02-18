# LinkedIn Session Setup Guide - Local Persistent Browser Context

This guide explains how to set up persistent LinkedIn authentication using local browser session storage.

## How It Works

The tool uses Playwright's persistent browser context to save cookies, localStorage, and session data locally. Once you log into LinkedIn once, your session will be automatically reused on subsequent runs.

## Setup Steps

### 1. First Run - Login Manually

On your first run, the browser will open and you'll need to log into LinkedIn:

```bash
# Run the scraper (browser will open)
python main.py --keywords "test" --location "test"
```

**What happens:**
- Browser opens automatically
- Navigate to LinkedIn and log in manually
- Your session cookies are saved to `.browser_data/` directory
- Close the browser when done

### 2. Subsequent Runs

After the first login, your session is saved. Future runs will automatically use your saved session:

```bash
# Browser will open already logged into LinkedIn
python main.py --keywords "software engineer" --location "San Francisco"
```

**No need to log in again!** The browser will use your saved cookies automatically.

## Configuration

### Default Behavior

By default, session data is saved in `.browser_data/` directory in your project root.

### Custom Session Directory

To use a custom directory for browser data:

```bash
# In your .env file
BROWSER_USER_DATA_DIR=/path/to/your/browser/data
```

## How Session Persistence Works

1. **First Run:**
   - Browser opens with a new context
   - You log into LinkedIn manually
   - Cookies (especially `li_at`) are saved to `.browser_data/`
   - Browser closes

2. **Subsequent Runs:**
   - Browser opens using the saved context from `.browser_data/`
   - Cookies are automatically loaded
   - You're already logged into LinkedIn
   - No manual login required

## Troubleshooting

### Session Expired

If LinkedIn says your session expired:

1. Delete the browser data directory:
   ```bash
   rm -rf .browser_data/
   ```

2. Run again and log in fresh:
   ```bash
   python main.py --keywords "test"
   ```

### LinkedIn Requires 2FA

If LinkedIn requires two-factor authentication:

1. Complete 2FA manually on first login
2. Check "Keep me logged in" if available
3. Session will persist after 2FA

### Cookies Not Persisting

**Check:**
- `.browser_data/` directory exists and is writable
- Browser process closes cleanly (don't force-kill)
- No permission errors in logs

**Solution:**
- Delete `.browser_data/` and try again
- Check disk space
- Ensure you have write permissions

### Multiple LinkedIn Accounts

To use different LinkedIn accounts:

1. Use different `BROWSER_USER_DATA_DIR` values:
   ```bash
   # Account 1
   BROWSER_USER_DATA_DIR=.browser_data_account1
   
   # Account 2  
   BROWSER_USER_DATA_DIR=.browser_data_account2
   ```

2. Or manually switch directories between runs

## Security Notes

⚠️ **Important Security Considerations:**

- **Never commit** `.browser_data/` to git (already in `.gitignore`)
- LinkedIn cookies are sensitive - treat them like passwords
- The `li_at` cookie provides full access to your LinkedIn account
- Keep your `.browser_data/` directory secure
- Rotate sessions periodically for security

## What Gets Saved

The `.browser_data/` directory contains:
- Cookies (including LinkedIn authentication cookies)
- LocalStorage data
- SessionStorage data
- Browser preferences
- Cache files

## Verification

To verify your session is working:

1. Run a simple scrape:
   ```bash
   python main.py --keywords "test" --max-results 5
   ```

2. Check if browser opens already logged in
3. If you see LinkedIn login page, session wasn't saved - log in again

## Next Steps

After setting up your session:
- Your automation will skip LinkedIn login automatically
- All browser-use agents will use the same authenticated session
- Session persists across multiple runs
- No need to handle authentication manually

## Tips

- **Keep session fresh:** Log in periodically to refresh cookies
- **Monitor session:** Check LinkedIn occasionally to ensure you're still logged in
- **Backup:** If you have a working session, you can backup `.browser_data/` (but keep it secure!)
- **Clean up:** Periodically delete old browser data if you switch accounts
