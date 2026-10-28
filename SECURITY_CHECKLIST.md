# 🔒 Security Checklist

## ✅ Already Protected

### 1. Environment Variables (.env file)
- ✅ `.env` file is in `.gitignore` - **will NOT be committed to GitHub**
- ✅ All sensitive credentials are stored in `.env`:
  - MongoDB connection string
  - Email credentials (MAIL_USERNAME, MAIL_PASSWORD)
  - Stripe API keys (SECRET_KEY, PUBLISHABLE_KEY)
  - Flask SECRET_KEY

### 2. Upload Directory
- ✅ `static/uploads/*` is in `.gitignore` - user uploaded files won't be committed

### 3. Database Files
- ✅ Local database files (*.db, *.sqlite, mongo/) are excluded

### 4. Python Cache
- ✅ `__pycache__/` and compiled Python files are excluded

## ⚠️ Action Required

### Before Pushing to GitHub:

1. **Verify .gitignore is working:**
   ```bash
   git status
   ```
   Make sure `.env` file is NOT listed in "Changes to be committed"

2. **If .env was previously committed, remove it from Git history:**
   ```bash
   git rm --cached .env
   git commit -m "Remove .env from repository"
   ```

3. **Create .env.example for documentation:**
   - Already exists! (`c:\Users\darpa\OneDrive\Desktop\Health-Management-System\.env.example`)
   - Contains placeholder values only (no real credentials)

### For Production Deployment:

1. **Use MongoDB Atlas (cloud database):**
   - Sign up: https://cloud.mongodb.com/
   - Create a free cluster
   - Get connection string and add to `.env` on server
   - Example: `MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/dbname`

2. **Rotate all API keys:**
   - Generate new Stripe keys for production
   - Use Stripe LIVE keys (starts with `sk_live_` and `pk_live_`)
   - Create new Gmail App Password for production email

3. **Generate strong Flask SECRET_KEY:**
   ```python
   import secrets
   print(secrets.token_hex(32))
   ```
   Update `.env` with the generated key

4. **Enable HTTPS:**
   - Use SSL/TLS certificates (Let's Encrypt is free)
   - Never send credentials over HTTP

5. **Set environment variables on hosting platform:**
   - Heroku: Use Config Vars
   - AWS: Use Systems Manager Parameter Store
   - Azure: Use App Settings
   - Railway/Render: Use Environment Variables section

## 🔍 How to Verify Security

### Check if .env is exposed:
```bash
# This should return empty (file not tracked):
git ls-files | grep .env

# This should show .env is ignored:
git check-ignore -v .env
```

### Check for sensitive data in commits:
```bash
# Search for potential secrets in history:
git log -S "mongodb://" --all
git log -S "STRIPE_SECRET_KEY" --all
```

## 📝 Best Practices

1. ✅ **Never hardcode credentials** - always use environment variables
2. ✅ **Use different credentials** for development and production
3. ✅ **Rotate keys regularly** - especially if compromised
4. ✅ **Limit API key permissions** - use read-only keys where possible
5. ✅ **Monitor access logs** - detect unusual activity
6. ✅ **Use .env.example** - document required variables without exposing values

## 🆘 If Credentials Were Exposed

### If you accidentally committed .env to GitHub:

1. **Immediately rotate ALL credentials:**
   - Change MongoDB password
   - Revoke and create new Stripe keys
   - Generate new Gmail App Password
   - Regenerate Flask SECRET_KEY

2. **Remove from Git history:**
   ```bash
   # Remove file from all commits (WARNING: rewrites history)
   git filter-branch --force --index-filter \
     "git rm --cached --ignore-unmatch .env" \
     --prune-empty --tag-name-filter cat -- --all
   
   # Force push (only if safe to do so)
   git push origin --force --all
   ```

3. **Alternative (safer) - use BFG Repo-Cleaner:**
   ```bash
   # Download from: https://rtyley.github.io/bfg-repo-cleaner/
   java -jar bfg.jar --delete-files .env
   git reflog expire --expire=now --all
   git gc --prune=now --aggressive
   ```

4. **Make repository private** (if not already) while cleaning up

## ✅ Current Status

- 🟢 MongoDB connection: Using environment variable ✓
- 🟢 .env file: Excluded from Git ✓
- 🟢 .gitignore: Properly configured ✓
- 🟢 Stripe keys: In environment variables ✓
- 🟢 Email credentials: In environment variables ✓
- 🟢 API keys: In environment variables ✓

**Your credentials are secure!** Just make sure you never commit the `.env` file.
