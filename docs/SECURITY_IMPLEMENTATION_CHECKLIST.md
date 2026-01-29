# Security Hardening Checklist & Quick Start Guide

**Status:** 📋 READY FOR IMPLEMENTATION  
**Last Updated:** January 27, 2026  
**Target:** Full Security Hardening in 3-4 weeks

---

## 🚨 CRITICAL - DO FIRST (Today - 8 hours)

### ✅ Task 1: Fix Error Message Leakage
**Ticket:** SECURITY-001  
**Effort:** 2-4 hours

**Files to Change:**
- [ ] `modules/api/auth/passwords.py` — Add generic error
- [ ] `modules/api/auth/users.py` — Use AuthenticationError everywhere
- [ ] `modules/api/auth/api_keys.py` — Consistent error messages

**Testing:**
```bash
# Run new tests
pytest tests/security/test_auth_errors.py -v

# Verify no information leakage in responses
python tests/security/test_error_messages.py
```

**Definition of Done:**
- [ ] All auth failures return same error
- [ ] No user existence leaks
- [ ] No password/format hints
- [ ] Tests verify consistency
- [ ] Code reviewed

---

### ✅ Task 2: Fix Timing Attacks on API Key Validation
**Ticket:** SECURITY-002  
**Effort:** 4-6 hours

**Files to Create/Modify:**
- [ ] Create `modules/api/security/constant_time.py`
- [ ] Update `modules/api/auth/api_keys.py` — Use constant-time validation
- [ ] Update `modules/api/auth/jwt_tokens.py` — Apply same pattern

**Code Changes:**
```python
# OLD (variable timing):
if key_data is None:
    return None

# NEW (constant timing):
from modules.api.security.constant_time import ConstantTimeOperations
result = await ConstantTimeOperations.validate_api_key_constant_time(...)
```

**Testing:**
```bash
# Run timing tests
pytest tests/security/test_timing_attacks.py -v
```

**Definition of Done:**
- [ ] All branches take ~same time (±10%)
- [ ] Uses secrets.compare_digest
- [ ] Timing tests added
- [ ] Load tested (no performance regression)

---

### ✅ Task 3: Add JWT Compromise Recovery Plan
**Ticket:** SECURITY-003  
**Effort:** 1 day (planning phase)

**Deliverables (for next week):**
- [ ] Design multi-key JWT support (with `kid`)
- [ ] Design grace period mechanism
- [ ] Create migration script
- [ ] Plan key rotation cron job

**Action Items:**
```
1. Design document: How to handle old keys during rotation?
2. Implementation: Multi-key validation
3. Testing: Key rotation doesn't invalidate valid tokens
4. Deployment: Plan key rotation in production
```

---

## 🟠 HIGH PRIORITY - Week 1 (Next 3-5 days)

### ✅ Task 4: Input Validation Framework
**Ticket:** SECURITY-004  
**Effort:** 4-6 hours

**Create:**
```python
# modules/api/security/input_validator.py
class InputValidator:
    MAX_JSON_SIZE = 10 * 1024 * 1024
    MAX_JSON_DEPTH = 20
    
    @staticmethod
    def validate_json_input(data) -> None:
        # Prevent: JSON bombs, deep nesting, null bytes
```

**Integration:**
```bash
# All API endpoints should have:
InputValidator.validate_json_input(request.body)
```

**Files to Update:**
- [ ] `modules/api/validation_models.py` — Add validator calls
- [ ] All endpoint handlers — Validate input

**Tests:**
```bash
pytest tests/security/test_input_validator.py -v
```

---

### ✅ Task 5: Sensitive Field Encryption
**Ticket:** SECURITY-005  
**Effort:** 2-3 days

**Create:**
```python
# modules/api/security/encryption.py
class StorageEncryption:
    SENSITIVE_FIELDS = {
        "auth_api_keys": ["secret"],
        "auth_jwt_secrets": ["secret"],
        "auth_refresh_tokens": ["token"],
    }
```

**Integration Steps:**
1. [ ] Generate encryption key
2. [ ] Wrap storage.get/set with encryption/decryption
3. [ ] Create data migration script
4. [ ] Test with both old and new data

**Files to Modify:**
- [ ] `adapters/storage_adapter.py` — Add encryption layer
- [ ] `adapters/sqlite_adapter.py` — Integrate encryption
- [ ] `adapters/postgresql_adapter.py` — Integrate encryption

**Complexity:** HIGH - requires careful migration

---

### ✅ Task 6: Add Password Reset Token Support
**Ticket:** SECURITY-006  
**Effort:** 6-8 hours

**Files to Create:**
- [ ] `modules/api/auth/password_reset.py`
  - Generate cryptographic reset tokens
  - Store with TTL (1 hour)
  - Verify tokens

**Features:**
```python
# Generate reset token
token = await create_password_reset_token(runtime, user_id)

# Send to email (if email service exists)
# Verify token + set new password
await verify_reset_token_and_set_password(runtime, token, new_password)
```

**Tests:**
```bash
pytest tests/auth/test_password_reset.py -v
```

---

### ✅ Task 7: Webhook Signing Support
**Ticket:** SECURITY-007  
**Effort:** 4 hours

**Create:**
```python
# modules/api/security/webhook_signing.py
class WebhookSigner:
    @staticmethod
    def sign_payload(payload: str, secret: str) -> str:
        return hmac.new(...).hexdigest()
    
    @staticmethod
    def verify_signature(payload, signature, secret) -> bool:
        return hmac.compare_digest(...)
```

**Implementation (when webhooks added):**
```python
# Send webhook
signature = WebhookSigner.sign_payload(json.dumps(event), webhook_secret)
response = requests.post(
    webhook_url,
    json=event,
    headers={"X-Webhook-Signature": f"sha256={signature}"}
)

# Receive webhook
signature = request.headers.get("X-Webhook-Signature")
if not WebhookSigner.verify_signature(...):
    return 401
```

---

## 🟡 MEDIUM PRIORITY - Month 1

### ✅ Task 8: HTTPS Enforcement
**Ticket:** SECURITY-008  
**Effort:** 2 hours

**Changes:**
```python
# core/config.py
if env == "production":
    assert cookies_secure is True, "HTTPS required in production"
    assert csp_mode == "strict", "Strict CSP required in production"

# modules/api/security_headers.py
response.headers["Strict-Transport-Security"] = \
    "max-age=31536000; includeSubDomains"
```

**Configuration:**
```bash
# .env.production
RUNTIME_ENV=production
RUNTIME_COOKIES_SECURE=true
RUNTIME_COOKIES_SAMESITE=strict
RUNTIME_CSP_MODE=strict
RUNTIME_LOG_FORMAT=json
RUNTIME_TRUST_PROXY_HEADERS=false
```

---

### ✅ Task 9: Per-User Rate Limiting
**Ticket:** SECURITY-009  
**Effort:** 8-10 hours

**Create:**
```python
# modules/api/security/rate_limiter_advanced.py
class AdvancedRateLimiter:
    USER_REQUESTS_PER_MINUTE = 100
    IP_REQUESTS_PER_MINUTE = 1000
    
    async def check_rate_limit(self, request):
        # Check per-user, per-IP, per-endpoint
```

**Middleware:**
```python
async def rate_limit_middleware(request, call_next):
    allowed, info = await limiter.check_rate_limit(request)
    if not allowed:
        return JSONResponse(429, {...})
```

---

### ✅ Task 10: IPv6 Normalization
**Ticket:** SECURITY-010  
**Effort:** 2-3 hours

**File:** `modules/api/admin_access_middleware.py`

```python
# OLD:
def is_private_ip(ip: str) -> bool:
    if ip == "::1":
        return True

# NEW:
def is_private_ip(ip: str) -> bool:
    import ipaddress
    try:
        ip_obj = ipaddress.ip_address(ip)
        return ip_obj.is_private or ip_obj.is_loopback
    except ValueError:
        return False
```

**Tests:**
```bash
pytest tests/security/test_ipv6_normalization.py -v
```

---

### ✅ Task 11: Strict CSP Enforcement
**Ticket:** SECURITY-011  
**Effort:** 2-3 hours

**Update:** `modules/api/security_headers.py`

```python
STRICT_CSP = """
script-src 'self';
style-src 'self' https://fonts.googleapis.com;
img-src 'self' data: https:;
connect-src 'self';
default-src 'none';
"""

# Validate in production
if env == "production":
    config.csp = STRICT_CSP
```

---

### ✅ Task 12: Sensitive Data in Logs
**Ticket:** SECURITY-012  
**Effort:** 4-6 hours

**Update:** All logging statements

```python
# OLD:
logger.info(f"API key: {api_key}")

# NEW:
logger.info(f"API key used: {api_key[:8]}***")
# Or use logger.debug() with separate sensitive log level
```

**Implementation:**
```python
# modules/api/security/secure_logger.py
class SecureLogger:
    @staticmethod
    def mask_sensitive(value: str, prefix_len: int = 8) -> str:
        """Mask sensitive values: show first N chars only"""
        if len(value) <= prefix_len:
            return "***"
        return f"{value[:prefix_len]}***"
```

---

## 📊 Progress Tracking

### Phase 1: Critical (Days 1-2)
```
Task 1: Error Messages        [████] 2-4h
Task 2: Timing Attacks        [████] 4-6h
Task 3: JWT Recovery Plan     [██  ] 1d
────────────────────────────────────────
Total Phase 1:                     ~1 day
```

### Phase 2: High Priority (Days 3-8)
```
Task 4: Input Validation      [     ] 4-6h
Task 5: Encryption at Rest    [     ] 2-3d
Task 6: Password Reset        [     ] 6-8h
Task 7: Webhook Signing       [     ] 4h
────────────────────────────────────────
Total Phase 2:              ~4-5 days
```

### Phase 3: Medium Priority (Month 1)
```
Task 8: HTTPS Enforcement     [     ] 2h
Task 9: Advanced Rate Limit   [     ] 8-10h
Task 10: IPv6 Normalization   [     ] 2-3h
Task 11: Strict CSP           [     ] 2-3h
Task 12: Secure Logging       [     ] 4-6h
────────────────────────────────────────
Total Phase 3:               ~1-2 weeks
```

**Overall Timeline:** 3-4 weeks for full remediation

---

## 📋 Daily Standup Template

```
TODAY'S SECURITY WORK:
Date: ___________

Completed Yesterday:
- [ ] Task: _______________

In Progress Today:
- [ ] Task: _______________
  Status: ___%
  Blockers: _______________

Planned Tomorrow:
- [ ] Task: _______________

Risks/Issues:
- [ ] ___________________

Questions:
- [ ] ___________________
```

---

## 🧪 Testing Checklist for Each Task

### Before Marking Complete
- [ ] Unit tests written and passing
- [ ] Integration tests passing
- [ ] Security-specific tests passing
- [ ] Manual testing completed
- [ ] Code review approved
- [ ] Documentation updated
- [ ] No regressions in existing tests

### Final Validation
```bash
# Run full security test suite
pytest tests/security/ -v --tb=short

# Run all auth tests
pytest tests/auth/ -v

# Load test for performance regression
locust -f tests/load/locustfile.py

# Security linting
bandit -r modules/api/auth/ -v
```

---

## 🔄 CI/CD Integration

### Update `.github/workflows/security.yml`

```yaml
name: Security Checks

on: [push, pull_request]

jobs:
  security:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Security Tests
        run: pytest tests/security/ -v
      
      - name: Bandit
        run: pip install bandit && bandit -r modules/ -v
      
      - name: Dependency Audit
        run: pip install pip-audit && pip-audit
      
      - name: Type Checking
        run: pip install pyright && pyright modules/api/
```

---

## 📚 Documentation Updates Required

- [ ] Update README.md with security guidelines
- [ ] Add SECURITY.md (reporting vulnerabilities)
- [ ] Create DEPLOYMENT_SECURITY.md
- [ ] Update API.md with security headers
- [ ] Add examples/ with secure usage patterns

---

## 🎯 Success Criteria

**Phase 1 Complete When:**
- ✅ All P0-CRIT issues fixed
- ✅ All security tests passing
- ✅ No information leakage in errors
- ✅ Timing attacks mitigated

**Phase 2 Complete When:**
- ✅ Input validation in place
- ✅ Encryption at rest working
- ✅ Password reset flow secure
- ✅ Webhook signing ready

**Phase 3 Complete When:**
- ✅ All 12 tasks completed
- ✅ OWASP Top 10 requirements met
- ✅ Follow-up security audit passed
- ✅ Documentation complete

**Production Ready When:**
- ✅ All phases complete
- ✅ Penetration testing passed
- ✅ Compliance checklist verified
- ✅ Monitoring/alerting in place

---

## 🆘 Getting Help

**If stuck on a task:**
1. Check SECURITY_IMPLEMENTATION_GUIDE.md for details
2. Review code examples in SECURITY_DEEP_DIVE_AUDIT.md
3. Check tests/ folder for test patterns
4. Ask team in security working group

**Escalation:**
- Task blockers → Security Lead
- Design questions → Architecture Review
- Deployment issues → DevOps

---

## 📞 Quick References

| Document | Purpose |
|----------|---------|
| SECURITY_AUDIT.md | Initial findings |
| SECURITY_DEEP_DIVE_AUDIT.md | Detailed vulnerability analysis |
| SECURITY_FIXES_ROADMAP.md | Implementation plans |
| SECURITY_IMPLEMENTATION_GUIDE.md | Code examples |
| This checklist | Daily work tracking |

---

**Status:** 🟢 Ready to start  
**Next Action:** Begin Phase 1 (Error Messages) immediately  
**Timeline:** 3-4 weeks to production-ready
