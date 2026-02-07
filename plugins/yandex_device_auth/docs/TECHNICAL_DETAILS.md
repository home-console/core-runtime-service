# 🔧 PWL Implementation - Technical Details

## Current Implementation

### Device Bootstrap Flow

```
YandexPassportClient.get_qr_url()
│
├─ Step 1: Bootstrap Device
│  POST https://passport.yandex.ru/auth/device/start
│  ├─ Payload:
│  │  ├─ device_name: "HomeConsole"
│  │  ├─ device_type: "smart_speaker"
│  │  └─ retpath: https://passport.yandex.ru/pwl-yandex/am/push/qrsecure
│  └─ Response: { status: "ok", device_id: "xxx", ... }
│
├─ Step 2: Get PWL Page
│  GET https://passport.yandex.ru/pwl-yandex/auth/add?retpath=...
│  ├─ Success: HTML without noPWL:true
│  └─ Failure: HTML with noPWL:true → ERROR
│
└─ Step 3: Return QR URL
   https://passport.yandex.ru/pwl-yandex/auth/add?retpath=https://...
```

### Auth Status Polling

```
YandexPassportClient.check_qr_status()
│
└─ Poll for Cookies
   ├─ Session jar is persistent across requests
   ├─ When user confirms QR in app → cookies appear automatically
   ├─ Extract cookies from session jar
   ├─ Get x_token from cookies
   └─ Return x_token for API access
```

---

## Why Device Bootstrap Is Mandatory

Яндекс требует device bootstrap для PWL по следующим причинам:

1. **Security** - Verification that device is legitimate
2. **Rate limiting** - Prevent abuse from unknown clients
3. **Device tracking** - Identify device for push notifications
4. **PWL enablement** - Without bootstrap, PWL is disabled (noPWL:true)

---

## Removed Components

### ❌ HTML Parsing
```python
# Old code tried to extract:
process_uuid_match = re.search(r'"process_uuid"\s*:\s*\'([^\']+)\'', html)

# Problems:
# - Fragile (HTML structure changes often)
# - Slow (parsing large HTML)
# - Fails silently
```

### ❌ Magic Init Endpoint
```python
# Old code called:
POST /api/v1/magic/init
  with: { process_uuid, type: "qr_code" }

# Problems:
# - Endpoint not documented
# - Requires complex parameter passing
# - Not needed for PWL
```

### ❌ Complex State Management
```python
# Old PWLLoginSession had:
# - process_uuid, magic, track_id
# - device_id, state
# - client_session, cookie_jar
# - lock, expires_at, created_at

# Simplified to:
# - device_id (from bootstrap)
# - retpath (standard PWL param)
```

---

## Current Implementation Details

### Endpoints Used

| Endpoint | Method | Purpose | Status |
|----------|--------|---------|--------|
| `/auth/device/start` | POST | Bootstrap device | ✅ Required |
| `/pwl-yandex/auth/add` | GET | Get PWL page | ✅ Used |
| `/api/v1/magic/init` | POST | Magic QR init | ❌ Removed |
| `/api/v1/magic/check` | GET | Magic status | ❌ Removed |

### Parameters Used

**Device Bootstrap:**
```json
{
  "device_name": "HomeConsole",
  "device_type": "smart_speaker",
  "retpath": "https://passport.yandex.ru/pwl-yandex/am/push/qrsecure"
}
```

**PWL Page Request:**
```
GET /pwl-yandex/auth/add?retpath=https://passport.yandex.ru/pwl-yandex/am/push/qrsecure
```

### Session Management

**Persistent Session:**
```python
auth_session = DeviceAuthSession(aiohttp.ClientSession())
# ├─ Maintains cookie jar across requests
# ├─ Holds device_id from bootstrap
# ├─ Holds pwl_params (device_id, retpath)
# └─ Automatically receives cookies when user confirms
```

---

## Error Handling

### noPWL:true Detection

```python
if "'noPWL':true" in html or '"noPWL":true' in html:
    logger.error("PWL not available - bootstrap failed")
    return None
```

**Meaning:** Device bootstrap did not work correctly

**Solutions:**
1. Check endpoint is correct
2. Verify request parameters
3. Check device_id was returned
4. Wait and retry bootstrap

### HTTP Errors

**Device Bootstrap:**
- 200: Success
- 400: Invalid parameters
- 403: Device not allowed
- 500: Server error

**PWL Page:**
- 200: Success (check for noPWL flag)
- 302: Redirect (allowed)
- 400: Invalid retpath
- 403: Device forbidden

---

## Testing Strategy

### Unit Tests

```python
def test_device_bootstrap():
    """Test device bootstrap response parsing."""
    pass

def test_pwl_page_check():
    """Test noPWL flag detection."""
    pass

def test_qr_url_generation():
    """Test QR URL format."""
    pass
```

### Integration Tests

```python
async def test_full_auth_flow():
    """Test complete auth flow from start to approval."""
    # 1. Call start_auth()
    # 2. Verify QR URL
    # 3. Simulate user confirmation (set cookies)
    # 4. Call check_qr_status()
    # 5. Verify x_token extracted
    pass
```

### Manual Testing

1. **Bootstrap Phase:**
   ```bash
   curl -X POST https://passport.yandex.ru/auth/device/start \
     -d "device_name=HomeConsole&device_type=smart_speaker&retpath=..."
   ```
   Check: `{ "status": "ok", "device_id": "xxx" }`

2. **PWL Page Phase:**
   ```bash
   curl https://passport.yandex.ru/pwl-yandex/auth/add?retpath=...
   ```
   Check: No `noPWL:true` in HTML

3. **QR Confirmation:**
   - Scan QR in Yandex app
   - Confirm on device
   - Check session cookies appear

---

## Known Limitations

1. **Device Type Hardcoded**
   - Currently: "smart_speaker"
   - Future: Make configurable

2. **No Multiple Devices**
   - Each auth session is separate
   - No session reuse across calls

3. **10-minute Timeout**
   - Auth session expires after 10 minutes
   - Need to restart auth if expired

---

## Future Improvements

- [ ] Support multiple device types
- [ ] Session reuse optimization
- [ ] Metrics/monitoring for failures
- [ ] Retry logic for transient errors
- [ ] Support for other retpath values

---

## Reference Documentation

- **Yandex Passport:** https://passport.yandex.ru/
- **PWL Flow:** Home Assistant integration pattern
- **OAuth 2.0:** Standard token exchange
- **Quasar API:** Yandex IoT platform

---

## Summary

✅ **Simplified PWL Implementation:**
- No HTML parsing
- No magic endpoints
- No complex state
- Direct cookie polling
- Clear error handling
- Standard retpath-based QR

**Status:** Ready for production testing
