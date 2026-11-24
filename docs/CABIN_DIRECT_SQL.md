## SQL-DIRECT — اجرای مستقیم عملیات SQLite

### ۱. هدف

این سرفصل برای اجرای مستقیم عملیات خواندن اطلاعات از SQLite ایجاد شده است. این مسیر مستقل از `CHART-INIT` و `CONSULT-LLM` است و برای اجرای عملیات به مدل زبانی وابستگی ندارد.

### ۲. عملیات فعلی

| نام عملیات در Cabin | فرمان SQLite | کاربرد |
|---|---|---|
| LIST-TABL | LIST-TABL | نمایش فهرست جدول‌ها |
| SELECT | SELA | خواندن رکوردهای یک جدول |

### ۳. ساختار فرمان

تمام درخواست‌ها با فرمان اصلی `SQL-DIRECT` ارسال می‌شوند. عملیات واقعی داخل فیلد `operation` قرار می‌گیرد.

نمونه فهرست جدول‌ها:

```json
{
  "command": "SQL-DIRECT",
  "operation": {
    "command": "LIST-TABL"
  },
  "status": ""
}
```

نمونه SELECT:

```json
{
  "command": "SQL-DIRECT",
  "operation": {
    "command": "SELA",
    "table": "h1Candles",
    "columns": ["*"],
    "limit": 60
  },
  "status": ""
}
```

### ۴. مسیر پردازش

1. Cabin فرمان `SQL-DIRECT` را در `commands.json` ثبت می‌کند.
2. MT5 فرمان را از مسیر عمومی Gateway به Python ارسال می‌کند.
3. Python فرمان اصلی و عملیات داخلی آن را اعتبارسنجی می‌کند.
4. عملیات داخلی با `execute_command()` در `mt5_sqlite.py` اجرا می‌شود.
5. نتیجه در پاسخ Gateway قرار می‌گیرد.
6. Cabin پاسخ را در JSON Viewer نمایش می‌دهد.

### ۵. تفکیک معماری

- `SQL-DIRECT` مسیر مستقل عملیات SQLite است.
- `CHART-INIT` برای عملیات آماده‌سازی و مقداردهی اولیه باقی می‌ماند.
- `CONSULT-LLM` برای درخواست‌های تحلیلی مدل زبانی باقی می‌ماند.
- `LIST-TABL` و `SELA` عملیات داخلی SQLite هستند، نه فرمان‌های اصلی Gateway.

### ۶. فایل‌های مرتبط

- `tests/log/MT5_Cabin.py`
- `tests/log/log.MT5-Gateway.mqh`
- `app/mt5_delivery.py`
- `app/mt5_sqlite.py`
- `docs/CABIN_JSON_V1.md`
- `docs/MT5_Cabin_Commands.md`

### ۷. محدوده فعلی

در نسخه اول فقط دو عملیات `LIST-TABL` و `SELECT` پشتیبانی می‌شوند. افزودن عملیات دیگر به این سرفصل در مراحل بعدی امکان‌پذیر است.
