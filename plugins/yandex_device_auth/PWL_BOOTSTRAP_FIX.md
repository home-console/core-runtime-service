# PWL Bootstrap Fix - Implementation Complete

## Problem
Яндекс возвращал `noPWL:true` флаг потому что **device bootstrap был обязательным** но не выполнялся правильно.

## Solution Implemented

### 1. Changed Device Bootstrap Endpoint ✓
**Before:** `registration-validations/auth/device/start`  
**After:** `https://passport.yandex.ru/auth/device/start`

The correct endpoint for device registration that enables PWL.

### 2. Removed HTML Parsing ✓
**Before:**
- Парсили HTML страницу `pwl-yandex/auth/add`
- Искали `process_uuid` через regex
- Вызывали `/api/v1/magic/init` endpoint

**After:**
- Не парсим HTML - просто проверяем наличие `noPWL:true` флага
- Если флаг есть = bootstrap не сработал, ошибка
- Если флага нет = PWL активен, возвращаем простой QR URL

### 3. Simplified QR Flow ✓
**Before:** `process_uuid={process_uuid}&magic={magic}`  
**After:** `retpath={retpath}` - standard PWL flow

Standard PWL QR URL теперь простая:
```
https://passport.yandex.ru/pwl-yandex/auth/add?retpath=https://passport.yandex.ru/pwl-yandex/am/push/qrsecure
```

### 4. Fixed check_qr_status() ✓
**Before:** Попытки различного парсинга и polling по track_id  
**After:** Простой polling - ждем появления cookies в session jar

Когда пользователь скканирует QR:
1. Яндекс приложение на телефоне автоматически подтверждает
2. Браузер/приложение получает cookies
3. Наша session jar их автоматически сохраняет
4. Мы их извлекаем и получаем x_token

## Key Changes in Code

### `yandex_passport_client.py`

**Imports:**
- Removed: `re` (больше не нужен для regex парсинга)

**`DeviceAuthSession` comment:**
- Updated: `pwl_params` теперь содержит `device_id, retpath` вместо `process_uuid, magic, track_id`

**`get_qr_url()` method:**
- Step 1: Device bootstrap to correct endpoint
- Step 2: Get PWL page and verify `noPWL` is NOT true
- Step 3: Return simple QR URL with retpath
- NO magic init, NO HTML parsing, NO complex state

**`check_qr_status()` method:**
- Simplified logic: just extract cookies when they appear
- Auto-approve happens transparently

## Flow Diagram

```
1. start_auth()
   ↓
2. get_qr_url()
   ├─ POST /auth/device/start (bootstrap)
   │  └─ Get device_id
   ├─ GET /pwl-yandex/auth/add (verify noPWL:false)
   └─ Return simple QR URL
   
3. [User scans QR in Yandex app]
   └─ App auto-confirms (no code needed)
   
4. check_qr_status() [polling loop]
   ├─ Wait for cookies in session jar
   ├─ Extract cookies → get x_token
   └─ Return auth data with x_token
```

## Benefits

✓ **No HTML scraping** - no fragile regex patterns  
✓ **No OAuth flow** - pure PWL  
✓ **No manual code entry** - auto-approve on app side  
✓ **Clean separation** - bootstrap is separate from QR flow  
✓ **Follows Home Assistant pattern** - same approach as working implementation  

## Testing

1. Call `start_auth()` - should return valid QR URL
2. Scan QR in Yandex app
3. Call `check_qr_status()` in loop - should return auth data after confirmation
4. Verify x_token is extracted correctly

## Notes

- Device bootstrap is **MANDATORY** - without it Yandex sets `noPWL:true`
- The endpoint `/auth/device/start` (not `registration-validations/...`)
- If `noPWL:true` appears in PWL page response = something wrong with bootstrap
- Session cookies are auto-approved by Yandex app - no additional server action needed
