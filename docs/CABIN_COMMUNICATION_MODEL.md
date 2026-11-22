# CABIN_COMMUNICATION_MODEL
## معماری ارتباطی Cabin، MetaTrader و Python

### 1. اعضای سیستم

**Cabin**
رابط کاربر برای ایجاد درخواست، ثبت فرمان‌ها و دریافت پاسخ‌هاست.

**MetaTrader**
میزبان زیرساخت Gateway و مجری عملیات اکسپرت است. درخواست‌های Cabin را دریافت می‌کند، به سرور منتقل می‌کند و پاسخ‌ها را دریافت و ذخیره می‌کند.

**Python**
درخواست‌های منتقل‌شده را پردازش می‌کند و پاسخ را برای بازگشت به MetaTrader آماده می‌سازد.

### 2. ساختار Gateway

Gateway روی سیستم MetaTrader و در مسیر مشترک فایل‌های MT5 قرار دارد.

ساختار فعلی:

```text
LLM-LQ/
└── LLM-B/
    ├── mt5_feed.json
    └── Gateway/
        ├── commands/
        │   └── commands.json
        ├── control/
        │   └── control.json
        ├── received/
        └── temp/
            ├── current_request.json
            ├── current_state.txt
            └── current_response.json
```

کاربرد فولدرها:

| مسیر | مسئولیت |
|---|---|
| `Gateway/commands` | ثبت درخواست‌های Cabin برای دریافت توسط اکسپرت |
| `Gateway/control` | ثبت فرمان‌های کنترلی |
| `Gateway/received` | ذخیره پاسخ‌های دریافت‌شده از سرور توسط اکسپرت |
| `Gateway/temp` | نگهداری فایل‌های موقت و وضعیت درخواست جاری |

### 3. مسیر ارتباط Cabin و Python

Cabin برای درخواست اطلاعاتی مانند فهرست جدول‌ها، نیازی به اجرای عملیات چارت ندارد.

مسیر درخواست:

```text
Cabin
  → Gateway/commands/commands.json
  → MetaTrader Expert
  → mt5_feed.json
  → egg.dll
  → Laravel Gateway
  → Python
```

مسیر پاسخ:

```text
Python
  → Laravel Gateway
  → egg.dll
  → MetaTrader Expert
  → Gateway/received/
  → Cabin
```

بنابراین ارتباط منطقی Cabin و Python از طریق قرارداد پیام‌ها انجام می‌شود؛ MetaTrader زیرساخت انتقال و دریافت فایل‌ها را فراهم می‌کند.

### 4. درخواست فهرست جدول‌ها

Cabin فرمان زیر را در `commands.json` ثبت می‌کند:

```json
{
  "command": "LIST-TABL",
  "status": ""
}
```

اکسپرت این فرمان را برای ارسال به Python در قالب زیر قرار می‌دهد:

```json
{
  "command": "CHART-INIT",
  "operations": [
    {
      "command": "LIST-TABL"
    }
  ]
}
```

در این مسیر:

- `LIST-TABL` فرمان درخواست‌شده توسط Cabin است.
- `CHART-INIT` پوشش عملیاتی پیام ارسالی به Python است.
- Python عملیات `LIST-TABL` را پردازش می‌کند.
- پاسخ از طریق MetaTrader به `Gateway/received` می‌رسد.

این کاربرد `CHART-INIT` به معنی آماده‌سازی چارت MT5 نیست.

### 5. آماده‌سازی و ارسال داده‌های کندل

Cabin به‌تنهایی قادر به تهیه داده‌های واقعی کندل نیست؛ این کار به قابلیت‌های MetaTrader نیاز دارد.

در این فرایند:

1. Cabin بازه زمانی را با تاریخ شروع و پایان تعیین می‌کند.
2. درخواست را به MetaTrader می‌دهد.
3. MetaTrader عملیات آماده‌سازی چارت و تهیه داده را انجام می‌دهد.
4. داده‌های کندل را برای Python ارسال می‌کند.
5. Python داده‌ها را دریافت و پردازش می‌کند.

در این کاربرد، `CHART-INIT` عملیات واقعی در محیط MetaTrader است و با عملیات `MAKE` و `INSR` ارتباط دارد.

### 6. دو کاربرد CHART-INIT

| مورد | کاربرد در درخواست فهرست جدول‌ها | کاربرد در آماده‌سازی چارت |
|---|---|---|
| آغازکننده | Cabin | MetaTrader |
| هدف | دریافت فهرست جدول‌ها | آماده‌سازی و ارسال داده کندل |
| عملیات اصلی | `LIST-TABL` | `MAKE` و `INSR` |
| محل اجرا | Python | MetaTrader |

نام `CHART-INIT` در هر دو مسیر استفاده می‌شود؛ اما مفهوم و مسئولیت آن‌ها متفاوت است.

### 7. وضعیت توسعه

**مرحله فعلی**

زیرساخت Gateway، تبادل فرمان‌ها، انتقال درخواست به Python و دریافت پاسخ در MetaTrader وجود دارد.

**مرحله بعد**

قابلیت `MT5-RESEND` با دو عملیات زیر طراحی و پیاده‌سازی خواهد شد:

- `TAKE-DATES`: دریافت بازه زمانی از Cabin و آماده‌سازی داده‌های کندل.
- `SEND-NEXT`: ارسال مرحله‌ای کندل‌های بعدی.

این قابلیت‌ها هنوز جزو پیاده‌سازی فعلی نیستند.

### 8. اسناد مرتبط

- `CABIN_JSON_V1.md` — قرارداد پیام‌ها و ساختار JSON.
- `MT5_Cabin_Commands.md` — شرح فرمان‌ها و عملیات MT5.
- `CABIN_COMMUNICATION_MODEL.md` — معماری ارتباطی سه عضو سیستم.
