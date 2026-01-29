# Security Remediation Implementation Guide

**Version:** 1.0  
**Date:** January 27, 2026  
**Status:** 📋 IMPLEMENTATION READY

---

## Phase 1: Critical Fixes (IMMEDIATE - Day 1-2)

### Issue P0-CRIT-1: Error Message Leakage

**File:** `modules/api/auth/passwords.py`, `modules/api/auth/users.py`

**Current Code:**
```python
async def validate_password(runtime, user_id, password):
    user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
    if not user_data:
        raise NotFoundError("user not found")  # ❌ LEAKS INFO
    
    if not verify_password(password, user_data["password_hash"]):
        raise UnauthorizedError("invalid password")  # ❌ TOO SPECIFIC
```

**Implementation:**
```python
# modules/api/auth/auth_errors.py (NEW)
class AuthenticationError(Exception):
    """Generic auth error - never reveals specifics"""
    def __init__(self):
        super().__init__("Authentication failed")

# modules/api/auth/passwords.py (UPDATED)
async def validate_password(runtime, user_id, password):
    """
    Always return same error regardless of reason.
    Reasons to fail:
    - User not found
    - Password incorrect
    - User disabled
    All return: "Authentication failed"
    """
    user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
    
    # If user not found, still hash password to consume same time
    if not user_data:
        _ = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        raise AuthenticationError()
    
    # If password wrong
    if not verify_password(password, user_data["password_hash"]):
        raise AuthenticationError()
    
    return user_data

# modules/api/auth/utils.py (NEW)
async def ensure_timing_constant(user_id: str, password: str) -> None:
    """Consume time even if user not found"""
    # Force bcrypt to run regardless of path taken
    import bcrypt
    fake_salt = bcrypt.gensalt()
    _ = bcrypt.hashpw(password.encode(), fake_salt)
```

**Tests:**
```python
# tests/security/test_auth_errors.py (NEW)
@pytest.mark.asyncio
async def test_password_validation_error_consistency():
    """Verify same error for user not found vs wrong password"""
    runtime = ...
    
    # Create user
    await create_user(runtime, "test_user", "Test@123")
    
    # Case 1: User not found
    with pytest.raises(AuthenticationError):
        await validate_password(runtime, "nonexistent", "Test@123")
    
    # Case 2: Wrong password
    with pytest.raises(AuthenticationError):
        await validate_password(runtime, "test_user", "WrongPass")
    
    # Case 3: Correct password
    result = await validate_password(runtime, "test_user", "Test@123")
    assert result is not None
```

**Timeline:** 2-4 hours  
**Reviewer Checklist:**
- [ ] All auth endpoints return generic errors
- [ ] All exceptions use AuthenticationError
- [ ] Tests verify error consistency
- [ ] No information leakage in HTTP status codes

---

### Issue P0-CRIT-2: Timing Attack on API Key Validation

**File:** `modules/api/auth/api_keys.py`

**Current Code (partially protected):**
```python
async def validate_api_key(runtime, api_key):
    # Revocation check (timing varies)
    if await is_revoked(runtime, api_key, "api_key"):
        return None
    
    # Storage check
    key_data = await runtime.storage.get(AUTH_API_KEYS_NAMESPACE, api_key)
    
    # Only one branch has timing protection
    if key_data is None:
        _ = secrets.compare_digest(api_key, api_key)
        return None
```

**Implementation:**
```python
# modules/api/security/constant_time.py (NEW)
import secrets
import time

class ConstantTimeOperations:
    """Ensure operations take constant time regardless of branch"""
    
    @staticmethod
    async def validate_api_key_constant_time(runtime, api_key):
        """
        ALL operations take same time:
        1. Check revocation
        2. Check storage
        3. Check expiration
        4. Validate scopes
        
        Then branch on results, but timing is constant
        """
        start_time = time.time()
        target_time = 0.100  # 100ms target
        
        # Phase 1: Always do these operations in order
        revocation_check = await is_revoked(runtime, api_key, "api_key")
        key_data = await runtime.storage.get(AUTH_API_KEYS_NAMESPACE, api_key)
        
        # Phase 2: Constant time comparisons
        if key_data is not None:
            scopes = key_data.get("scopes", [])
            _ = secrets.compare_digest(
                str(scopes),  # Hash scopes to consume time
                str(scopes)
            )
        
        # Phase 3: Ensure minimum time
        elapsed = time.time() - start_time
        if elapsed < target_time:
            await asyncio.sleep(target_time - elapsed)
        
        # Phase 4: NOW branch on results
        if revocation_check or key_data is None:
            return None
        
        return RequestContext(...)

# modules/api/auth/api_keys.py (UPDATED)
from modules.api.security.constant_time import ConstantTimeOperations

async def validate_api_key(runtime, api_key):
    return await ConstantTimeOperations.validate_api_key_constant_time(runtime, api_key)
```

**Tests:**
```python
# tests/security/test_timing_attacks.py (NEW)
@pytest.mark.asyncio
async def test_api_key_validation_timing_constant():
    """
    Verify that validation takes approximately same time
    regardless of whether key exists or not
    """
    import time
    runtime = setup_runtime()
    
    # Create a valid key
    valid_key = await create_api_key(runtime, scopes=["read"])
    
    # Invalid key that doesn't exist
    invalid_key = "invalid_key_12345"
    
    # Measure both
    times = []
    for key in [valid_key, invalid_key]:
        start = time.time()
        await validate_api_key(runtime, key)
        times.append(time.time() - start)
    
    # Should be within 10% of each other
    diff = abs(times[0] - times[1]) / max(times) * 100
    assert diff < 10, f"Timing difference: {diff}%"
```

**Timeline:** 4-6 hours  
**Reviewer Checklist:**
- [ ] All branches consume same time
- [ ] Uses secrets.compare_digest for string comparisons
- [ ] Minimum sleep time enforced
- [ ] Timing tests added and passing

---

## Phase 2: High Priority Fixes (Week 1)

### Issue P1-HIGH-1: Input Validation Framework

**Create:** `modules/api/security/input_validator.py`

```python
"""
Comprehensive input validation framework.

Prevents:
- JSON bombs (excessive size)
- Deep nesting attacks (stack overflow)
- Unicode/encoding attacks (null bytes, etc.)
- Type confusion
"""

import json
from typing import Any, Dict

class InputValidator:
    """Input validation with configurable limits"""
    
    # Configuration
    MAX_JSON_SIZE = 10 * 1024 * 1024  # 10 MB
    MAX_JSON_DEPTH = 20
    MAX_ARRAY_LENGTH = 10000
    MAX_STRING_LENGTH = 1024 * 1024  # 1 MB
    ALLOWED_KEY_PATTERN = r'^[a-zA-Z0-9_\-\.]+$'
    
    @staticmethod
    def validate_json_input(data: Any) -> None:
        """
        Validate JSON data before processing.
        
        Raises:
            BadRequestError: if validation fails
        """
        if not isinstance(data, (dict, list)):
            raise BadRequestError("Input must be JSON object or array")
        
        # Check size
        json_str = json.dumps(data)
        if len(json_str.encode()) > InputValidator.MAX_JSON_SIZE:
            raise BadRequestError(f"Input exceeds max size ({InputValidator.MAX_JSON_SIZE} bytes)")
        
        # Check depth and keys
        InputValidator._validate_structure(data, depth=0)
    
    @staticmethod
    def _validate_structure(data: Any, depth: int = 0) -> None:
        """Recursively validate JSON structure"""
        if depth > InputValidator.MAX_JSON_DEPTH:
            raise BadRequestError("JSON nested too deep")
        
        if isinstance(data, dict):
            if len(data) > InputValidator.MAX_ARRAY_LENGTH:
                raise BadRequestError("Dictionary too large")
            
            for key, value in data.items():
                # Validate key format (no null bytes, etc)
                if not isinstance(key, str):
                    raise BadRequestError("Dictionary keys must be strings")
                if '\x00' in key:
                    raise BadRequestError("Null bytes not allowed in keys")
                
                # Recurse into value
                InputValidator._validate_structure(value, depth + 1)
        
        elif isinstance(data, list):
            if len(data) > InputValidator.MAX_ARRAY_LENGTH:
                raise BadRequestError("Array too large")
            
            for item in data:
                InputValidator._validate_structure(item, depth + 1)
        
        elif isinstance(data, str):
            if len(data.encode()) > InputValidator.MAX_STRING_LENGTH:
                raise BadRequestError("String too long")
            if '\x00' in data:
                raise BadRequestError("Null bytes not allowed in strings")
        
        elif not isinstance(data, (int, float, bool, type(None))):
            raise BadRequestError(f"Invalid JSON type: {type(data)}")
    
    @staticmethod
    def validate_field(field_name: str, field_type: type, value: Any) -> None:
        """
        Validate individual field.
        
        Usage:
            InputValidator.validate_field("user_id", str, user_id)
            InputValidator.validate_field("count", int, count)
        """
        if not isinstance(value, field_type):
            raise BadRequestError(f"{field_name} must be {field_type.__name__}")
        
        if field_type == str and not value.strip():
            raise BadRequestError(f"{field_name} cannot be empty")
        
        if field_type == str and len(value) > 1000:
            raise BadRequestError(f"{field_name} too long (max 1000 chars)")
        
        if field_type == int and (value < 0 or value > 2**31 - 1):
            raise BadRequestError(f"{field_name} out of valid range")
```

**Usage Examples:**
```python
# In API endpoints
from modules.api.security import InputValidator

@app.post("/api/devices/set_state")
async def set_device_state(device_id: str, state: dict):
    # Validate inputs
    InputValidator.validate_field("device_id", str, device_id)
    InputValidator.validate_json_input(state)  # Max size, depth, etc
    
    # Now safe to process
    ...
```

**Tests:**
```python
# tests/security/test_input_validator.py (NEW)
def test_json_bomb_protection():
    """Reject extremely large JSON"""
    huge_dict = {"key": "x" * (20 * 1024 * 1024)}  # 20 MB
    
    with pytest.raises(BadRequestError):
        InputValidator.validate_json_input(huge_dict)

def test_deep_nesting_protection():
    """Reject deeply nested JSON"""
    deeply_nested = {"level1": {"level2": ...}}  # 30 levels deep
    
    with pytest.raises(BadRequestError):
        InputValidator.validate_json_input(deeply_nested)

def test_null_byte_protection():
    """Reject strings with null bytes"""
    bad_input = {"key\x00name": "value"}
    
    with pytest.raises(BadRequestError):
        InputValidator.validate_json_input(bad_input)
```

**Timeline:** 4-6 hours  
**Files to Update:**
- [ ] `modules/api/validation_models.py` — Add InputValidator calls
- [ ] All endpoints handling JSON input

---

### Issue P1-HIGH-2: Encryption at Rest

**Create:** `modules/api/security/encryption.py`

```python
"""
Encryption for sensitive data at rest.

Encrypts:
- API keys
- JWT secrets
- Refresh tokens
- Password reset tokens
"""

from cryptography.fernet import Fernet
from typing import Dict, Any

class StorageEncryption:
    """Encrypt/decrypt sensitive fields"""
    
    SENSITIVE_FIELDS = {
        "auth_api_keys": ["secret"],  # API key secrets
        "auth_jwt_secrets": ["secret"],  # JWT secrets
        "auth_refresh_tokens": ["token"],  # Refresh tokens
    }
    
    def __init__(self, encryption_key: bytes):
        """
        Args:
            encryption_key: 32 bytes (256-bit) key for Fernet
        """
        self.cipher = Fernet(encryption_key)
    
    def encrypt_value(self, plaintext: str) -> str:
        """Encrypt a value"""
        return self.cipher.encrypt(plaintext.encode()).decode()
    
    def decrypt_value(self, ciphertext: str) -> str:
        """Decrypt a value"""
        return self.cipher.decrypt(ciphertext.encode()).decode()
    
    def encrypt_record(self, namespace: str, record: Dict[str, Any]) -> Dict[str, Any]:
        """Encrypt sensitive fields in a storage record"""
        encrypted = record.copy()
        
        if namespace in self.SENSITIVE_FIELDS:
            for field in self.SENSITIVE_FIELDS[namespace]:
                if field in encrypted:
                    encrypted[field] = self.encrypt_value(encrypted[field])
        
        return encrypted
    
    def decrypt_record(self, namespace: str, record: Dict[str, Any]) -> Dict[str, Any]:
        """Decrypt sensitive fields in a storage record"""
        decrypted = record.copy()
        
        if namespace in self.SENSITIVE_FIELDS:
            for field in self.SENSITIVE_FIELDS[namespace]:
                if field in decrypted:
                    try:
                        decrypted[field] = self.decrypt_value(decrypted[field])
                    except:
                        # Decryption failed (corrupted data?)
                        raise ValueError(f"Failed to decrypt {field}")
        
        return decrypted

# Usage in storage adapters
# OLD:
async def get(self, namespace, key):
    data = await runtime.storage._get_raw(namespace, key)
    return data

# NEW:
async def get(self, namespace, key):
    data = await runtime.storage._get_raw(namespace, key)
    return encryption.decrypt_record(namespace, data)
```

**Integration:**
```python
# core/runtime.py (UPDATED)
from modules.api.security.encryption import StorageEncryption

class CoreRuntime:
    def __init__(self):
        # Generate or load encryption key
        self.encryption_key = self._load_encryption_key()
        self.encryption = StorageEncryption(self.encryption_key)
    
    async def storage_get(self, namespace, key):
        raw_data = await self.storage.get(namespace, key)
        return self.encryption.decrypt_record(namespace, raw_data)
```

**Timeline:** 2-3 days (major refactoring)  
**Complexity:** HIGH
**Reviewer Checklist:**
- [ ] All API key fields encrypted
- [ ] Key rotation mechanism implemented
- [ ] Decryption errors handled gracefully
- [ ] Migration script for existing data

---

## Phase 3: Medium Priority Fixes (Month 1)

### Issue P2-MEDIUM-1: Comprehensive Rate Limiting

**Create:** `modules/api/security/rate_limiter_advanced.py`

```python
"""
Advanced rate limiting with per-user, per-IP, and per-endpoint limits.
Supports distributed deployment via Redis or in-memory for single-process.
"""

from typing import Dict, Tuple
import time
from datetime import datetime, timedelta

class RateLimitConfig:
    # Per-user limits
    USER_REQUESTS_PER_MINUTE = 100
    USER_AUTH_ATTEMPTS_PER_HOUR = 10
    
    # Per-IP limits
    IP_REQUESTS_PER_MINUTE = 1000
    
    # Per-endpoint limits
    ENDPOINT_LIMITS = {
        "/api/login": 5,  # attempts per minute
        "/api/password/reset": 3,  # per hour
        "/api/devices/*": 100,  # per minute per user
    }

class AdvancedRateLimiter:
    """Rate limiter with multiple strategies"""
    
    def __init__(self, storage):
        self.storage = storage
    
    async def check_rate_limit(self, request) -> Tuple[bool, Dict]:
        """
        Check if request should be rate limited.
        
        Returns:
            (allowed: bool, info: {remaining, retry_after, ...})
        """
        # Extract identifiers
        user_id = request.user_id if hasattr(request, 'user_id') else None
        ip_addr = request.client.host
        endpoint = request.url.path
        
        results = []
        
        # Check per-user limit
        if user_id:
            user_limited = await self._check_user_limit(user_id)
            results.append(user_limited)
        
        # Check per-IP limit
        ip_limited = await self._check_ip_limit(ip_addr)
        results.append(ip_limited)
        
        # Check per-endpoint limit
        endpoint_limited = await self._check_endpoint_limit(endpoint, user_id, ip_addr)
        results.append(endpoint_limited)
        
        # If ANY limit exceeded, deny
        if not all(r[0] for r in results):
            # Return most restrictive rate limit info
            most_restrictive = max(results, key=lambda r: r[1].get('retry_after', 0))
            return False, most_restrictive[1]
        
        return True, {}
    
    async def _check_user_limit(self, user_id: str) -> Tuple[bool, Dict]:
        """Check per-user rate limit"""
        key = f"ratelimit:user:{user_id}"
        # Implement sliding window counter
        ...
    
    async def _check_ip_limit(self, ip_addr: str) -> Tuple[bool, Dict]:
        """Check per-IP rate limit"""
        key = f"ratelimit:ip:{ip_addr}"
        # Implement sliding window counter
        ...
    
    async def _check_endpoint_limit(self, endpoint: str, user_id: str, ip_addr: str) -> Tuple[bool, Dict]:
        """Check per-endpoint rate limit"""
        key = f"ratelimit:endpoint:{endpoint}:{user_id or ip_addr}"
        # Implement sliding window counter
        ...
```

**Integration with FastAPI:**
```python
# middleware
async def rate_limit_middleware(request, call_next):
    limiter = request.app.state.rate_limiter
    allowed, info = await limiter.check_rate_limit(request)
    
    if not allowed:
        retry_after = info.get('retry_after', 60)
        return JSONResponse(
            status_code=429,
            content={"error": "Too many requests"},
            headers={"Retry-After": str(retry_after)}
        )
    
    return await call_next(request)
```

**Timeline:** 8-10 hours  
**Complexity:** MEDIUM-HIGH

---

## Implementation Checklist

### Before Starting
- [ ] Review all documents (SECURITY_AUDIT.md, SECURITY_DEEP_DIVE_AUDIT.md)
- [ ] Create feature branch: `feature/security-hardening`
- [ ] Set up security tests in CI

### Phase 1 Completion
- [ ] P0-CRIT-1 error messages fixed
- [ ] P0-CRIT-2 timing attacks mitigated
- [ ] All tests passing
- [ ] Code review completed

### Phase 2 Completion
- [ ] InputValidator implemented and integrated
- [ ] Encryption at rest implemented
- [ ] API key validation hardened
- [ ] All security tests passing

### Phase 3 Completion
- [ ] Advanced rate limiting deployed
- [ ] Per-user limits enforced
- [ ] IPv6 normalization fixed
- [ ] CSP strict mode enforced

### Final Validation
- [ ] Security audit passed (follow-up)
- [ ] Penetration testing completed
- [ ] Compliance checklist verified
- [ ] Documentation updated

---

## Testing Strategy

### Unit Tests
```bash
pytest tests/security/ -v --cov=modules/api/security
```

### Integration Tests
```bash
# Test end-to-end auth flows
pytest tests/integration/test_auth_flows.py -v
```

### Security Tests
```bash
# Test specific security scenarios
pytest tests/security/ -m security -v
```

### Load Tests with Security
```bash
# Verify rate limiting works under load
locust -f tests/load/locustfile.py --host=http://localhost:8000
```

---

## Deployment Strategy

### Stage 1: Development
- All fixes in dev branch
- Extensive testing
- Security review

### Stage 2: Staging
- Deploy to staging environment
- Run full security audit
- Load testing

### Stage 3: Production
- Phased rollout (canary deployment)
- Monitor for issues
- Have rollback plan

---

## Maintenance After Deployment

### Monthly Reviews
- [ ] Check for new CVEs in dependencies
- [ ] Review security logs for patterns
- [ ] Update encryption keys (if needed)

### Quarterly Audits
- [ ] Full security review
- [ ] Penetration testing
- [ ] Compliance check

### Annual Tasks
- [ ] Comprehensive security audit
- [ ] Architecture review
- [ ] Incident response drill

---

**Next Action:** Start Phase 1 implementation immediately
