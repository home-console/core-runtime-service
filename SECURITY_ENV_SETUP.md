# P0 Security Hardening - Environment Variables

This file documents required environment variables for P0 security hardening.

## Required Environment Variables

### OAUTH_ENCRYPTION_KEY (P0 - CRITICAL)
**Purpose:** Encrypts OAuth tokens at rest in storage

**Generate:**
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Example:**
```bash
export OAUTH_ENCRYPTION_KEY="your-generated-key-here"
```

**Impact if missing:** OAuth tokens stored in PLAINTEXT → database leak = token leak

---

### CSRF_SECRET (P0 - CRITICAL)
**Purpose:** CSRF token generation/validation for Admin API

**Generate:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Example:**
```bash
export CSRF_SECRET="your-generated-secret-here"
```

**Impact if missing:** Admin API vulnerable to CSRF attacks

---

### YANDEX_CLIENT_SECRET (P0 - CRITICAL)
**Purpose:** Yandex OAuth client secret (replaces hardcoded value)

**Obtain:** From Yandex OAuth application settings

**Example:**
```bash
export YANDEX_CLIENT_SECRET="your-yandex-client-secret"
```

**Impact if missing:** Hardcoded secret used (INSECURE for production)

---

## Optional Environment Variables

### DEBUG (Development)
**Purpose:** Enable request/response body logging in request_logger middleware

**Values:** `true`, `1`, `yes` (case-insensitive)

**Example:**
```bash
export DEBUG=true
```

**Default:** `false` (bodies NOT logged)

**Security:** Even in DEBUG mode, secrets are sanitized before logging

---

## Production Deployment Example

```bash
#!/bin/bash
# production-env.sh

# Generate secrets (do this ONCE, store securely)
export OAUTH_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export CSRF_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"

# Yandex OAuth (from Yandex console)
export YANDEX_CLIENT_SECRET="your-actual-secret-from-yandex"

# Start runtime
python main.py
```

---

## Security Validation

Runtime performs security validation on startup:
- ✅ All P0 env variables present → starts normally
- ❌ Any P0 env variable missing → fails with error message
- ⚠️  Optional env variables missing → starts with warning

Check validation:
```bash
python -m core.security_init
```

---

## Migration from Hardcoded Secrets

### Step 1: Generate keys
```bash
# Generate OAUTH_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Generate CSRF_SECRET
python -c "import secrets; print(secrets.token_hex(32))"
```

### Step 2: Set environment variables
```bash
export OAUTH_ENCRYPTION_KEY="<generated-key>"
export CSRF_SECRET="<generated-secret>"
export YANDEX_CLIENT_SECRET="<your-yandex-secret>"
```

### Step 3: Start runtime
```bash
python main.py
```

Runtime will:
1. ✅ Validate all env variables are set
2. ✅ Encrypt new OAuth tokens before storage
3. ⚠️  Existing plaintext tokens will be read as legacy (still work)
4. ✅ Next token refresh will encrypt and save properly

### Step 4: Re-encrypt existing tokens (optional)
Existing tokens will be automatically re-encrypted on next refresh.
Or manually trigger re-authorization to force re-encryption.

---

## Security Checklist

Before production deployment:
- [ ] OAUTH_ENCRYPTION_KEY generated and set
- [ ] CSRF_SECRET generated and set
- [ ] YANDEX_CLIENT_SECRET obtained from Yandex and set
- [ ] DEBUG=false (or not set) in production
- [ ] Environment variables stored securely (not in code)
- [ ] Runtime starts without security errors
- [ ] Test CSRF protection on Admin API
- [ ] Verify tokens encrypted in storage (check database)

---

## Troubleshooting

### "OAUTH_ENCRYPTION_KEY not set" error
Generate key and set env variable:
```bash
export OAUTH_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

### "CSRF_SECRET not set" error
Generate secret and set env variable:
```bash
export CSRF_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

### "Failed to decrypt token data" error
Token was encrypted with different key. Either:
1. Use correct OAUTH_ENCRYPTION_KEY (if you changed it)
2. Re-authorize to get new tokens with current key

### CSRF validation failing
Check X-CSRF-Token header is sent with POST/PUT/PATCH/DELETE requests to /admin/*

Get CSRF token:
```bash
GET /admin/v1/auth/csrf
```

Use in request:
```bash
curl -X POST /admin/v1/devices/sync \
  -H "X-CSRF-Token: <token-from-csrf-endpoint>" \
  -H "Authorization: Bearer <your-token>"
```
