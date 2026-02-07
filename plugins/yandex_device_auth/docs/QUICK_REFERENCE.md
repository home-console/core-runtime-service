# 🚀 PWL Bootstrap Fix - Quick Reference

## What Changed?

### ✅ ADDED
- ✅ Device bootstrap to correct endpoint
- ✅ Proper noPWL flag checking
- ✅ Clear step-by-step logging

### ❌ REMOVED
- ❌ HTML parsing for process_uuid
- ❌ /api/v1/magic/init endpoint
- ❌ Complex magic/track_id parameters
- ❌ Fragile regex patterns

---

## The Flow (Simple Version)

```
1. Bootstrap device (POST /auth/device/start)
   └─ Get device_id

2. Get PWL page (GET /pwl-yandex/auth/add?retpath=...)
   └─ Check noPWL is NOT true

3. Return QR URL to user
   └─ User scans in Yandex app

4. User confirms in app
   └─ Cookies appear in session

5. Extract x_token from cookies
   └─ Use for API access
```

---

## Bootstrap Request

```http
POST https://passport.yandex.ru/auth/device/start

device_name=HomeConsole
&device_type=smart_speaker
&retpath=https://passport.yandex.ru/pwl-yandex/am/push/qrsecure
```

**Response:**
```json
{
  "status": "ok",
  "device_id": "abc123..."
}
```

---

## QR URL

```
https://passport.yandex.ru/pwl-yandex/auth/add?retpath=https://passport.yandex.ru/pwl-yandex/am/push/qrsecure
```

That's it! No magic parameters.

---

## Success Indicators

### ✅ If It Works:
- Device bootstrap returns device_id
- PWL page HTML does NOT contain `noPWL:true`
- QR URL is generated correctly
- User can scan QR in Yandex app
- Cookies appear after user confirms
- x_token is extracted successfully

### ❌ If It Fails:
- Device bootstrap returns error
- PWL page contains `noPWL:true` → Bootstrap failed!
- QR URL not generated
- User can't scan QR
- No cookies appear
- x_token extraction fails

---

## Key Files

| File | What Changed | Status |
|------|-------------|--------|
| `yandex_passport_client.py` | Complete rewrite | ✏️ 150 lines |
| `device_session.py` | Simplified models | ✏️ 60 lines |
| `yandex_api_client.py` | Deprecated | ⚠️ Removed |
| `device_auth_service.py` | No changes | ✅ Compatible |

---

## Testing Quick Checklist

```bash
# 1. Start auth
curl -X POST http://localhost:8000/yandex/auth/start

# Expected:
# { "qr_url": "https://...", "oauth_url": "https://...", "track_id": "..." }

# 2. Scan QR in Yandex app and confirm

# 3. Check status (poll in loop)
curl http://localhost:8000/yandex/auth/status

# Expected after confirmation:
# { "status": "approved", "quasar_ready": true, "x_token": "..." }
```

---

## Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| `noPWL:true` in response | ❗ Bootstrap failed - check endpoint |
| Device bootstrap 400 | Check parameters: device_name, device_type, retpath |
| Device bootstrap 403 | Device might be blocked - try different device_type |
| QR not scanning | Ensure retpath is exactly correct |
| No cookies appear | User didn't confirm in app or session expired |
| x_token extraction fails | Check session has cookies, not just looking for wrong names |

---

## Code Reference

### Main Entry Point
```python
# File: device_auth_service.py
async def start_auth(self, method: str = "qr") -> Dict[str, Any]:
    """Start QR auth"""
    auth_session = DeviceAuthSession(aiohttp.ClientSession())
    qr_result = await self.passport_client.get_qr_url(auth_session)
    return {
        "qr_url": qr_result.get("qr_url"),
        "track_id": qr_result.get("track_id"),
    }

async def check_qr_status(self) -> Optional[Dict[str, Any]]:
    """Poll for user confirmation"""
    result = await self.passport_client.check_qr_status(self._auth_session)
    if result:
        await self._save_account_session(result)
        return {"status": "approved", "x_token": result.get("x_token")}
    return {"status": "pending"}
```

### Implementation Details
```python
# File: yandex_passport_client.py

async def get_qr_url(self, auth_session: DeviceAuthSession):
    """
    1. Bootstrap device
    2. Verify PWL enabled
    3. Return QR URL
    """
    
async def check_qr_status(self, auth_session: DeviceAuthSession):
    """
    1. Check session cookies
    2. Extract x_token
    3. Return auth data
    """
```

---

## Important Endpoints

### Correct Endpoint (USE THIS)
```
https://passport.yandex.ru/auth/device/start
```

### Wrong Endpoint (DON'T USE)
```
https://passport.yandex.ru/registration-validations/auth/device/start
```

---

## Parameters Explained

| Param | Value | Purpose |
|-------|-------|---------|
| `device_name` | "HomeConsole" | Display name for user |
| `device_type` | "smart_speaker" | Device category |
| `retpath` | "https://passport.yandex.ru/pwl-yandex/am/push/qrsecure" | Return path after auth |

---

## Next Steps

1. ✅ Review the changes above
2. ✅ Test with `start_auth()` endpoint
3. ✅ Scan QR in Yandex app
4. ✅ Verify cookies appear
5. ✅ Extract and use x_token
6. ✅ Deploy to production

---

## Status: READY ✅

All code is clean, tested for syntax, and ready for functional testing.
