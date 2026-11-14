# MT5 Gateway JSON Protocol
## Draft Version 1

### 1. اصول اصلی

این پروتکل ارتباط مطمئن بین MT5، Laravel Gateway و Python Gateway را تعریف می‌کند.

سه شناسه و مفهوم اصلی داریم:

- `client_id`: شناسه ترمینال MT5.
- `request_id`: شناسه یکتای درخواست که MT5 تولید می‌کند و در تمام تلاش‌های مجدد ثابت می‌ماند.
- `response_id`: شناسه یکتای پاسخ که Python پس از تولید و ذخیره پایدار پاسخ ایجاد می‌کند.

**قانون مهم:**

`request_id` از ابتدای چرخه وجود دارد.

`response_id` تا پیش از ایجاد و ذخیره پاسخ وجود ندارد.

وجود `response_id` به معنی آماده‌بودن پاسخ است؛ اما نبود آن به معنی نرسیدن درخواست به Python نیست.

برای تشخیص ثبت درخواست در Python، باید `status=REGISTERED` را بررسی کنیم.

---

### 2. ساختار عمومی پیام

ساختار پیام‌های پروتکل:

```json
{
  "protocol": "mt5-gateway",
  "version": 1,
  "message_type": "INGEST",
  "client_id": "mt5_terminal_01",
  "request_id": "mt5_terminal_01-000001",
  "created_at": "2026-11-15T12:30:00Z",
  "payload": {}
}
```

تعریف فیلدها:

| Field | Description |
|---|---|
| protocol | نام پروتکل |
| version | نسخه پروتکل |
| message_type | نوع عملیات پروتکل |
| client_id | شناسه ترمینال |
| request_id | شناسه پایدار درخواست |
| created_at | زمان ایجاد درخواست |
| payload | اطلاعات اختصاصی پیام |

`request_id` و `created_at` در تمام Retryهای یک درخواست ثابت می‌مانند.

---

### 3. انواع پیام

در نسخه اول سه نوع پیام داریم:

- `INGEST`: ارسال درخواست از MT5 به Python از طریق Laravel.
- `POLL`: بررسی وضعیت درخواست و دریافت پاسخ.
- `ACK`: تأیید دریافت پاسخ توسط MT5.

---

### 4. پیام INGEST

MT5 درخواست را با این ساختار ارسال می‌کند:

```json
{
  "protocol": "mt5-gateway",
  "version": 1,
  "message_type": "INGEST",
  "client_id": "mt5_terminal_01",
  "request_id": "mt5_terminal_01-000001",
  "created_at": "2026-11-15T12:30:00Z",
  "payload": {
    "command": "INIT",
    "symbol": "EURUSD",
    "timeframes": {
      "H1": [],
      "H6": []
    }
  }
}
```

`command` نوع عملیات تجاری MT5 را مشخص می‌کند.

مقادیر اولیه آن:

- `INIT`
- `CANDLE_UPDATE`

این فیلد با `message_type` پروتکل متفاوت است.

#### پاسخ اولیه Python

پس از دریافت و ثبت پایدار درخواست:

```json
{
  "protocol": "mt5-gateway",
  "version": 1,
  "message_type": "INGEST_RESULT",
  "client_id": "mt5_terminal_01",
  "request_id": "mt5_terminal_01-000001",
  "status": "REGISTERED",
  "response_id": null,
  "created_at": "2026-11-15T12:30:00Z",
  "payload": null
}
```

معنی `REGISTERED`:

Python درخواست را دریافت کرده و اطلاعات آن را به‌صورت پایدار ذخیره کرده است.

این وضعیت به معنی پایان پردازش نیست.

---

### 5. پیام POLL

MT5 برای بررسی وضعیت درخواست، از POLL استفاده می‌کند.

در این پیام، `request_id` مشخص می‌کند که MT5 منتظر پاسخ کدام درخواست است.

```json
{
  "protocol": "mt5-gateway",
  "version": 1,
  "message_type": "POLL",
  "client_id": "mt5_terminal_01",
  "request_id": "mt5_terminal_01-000001"
}
```

POLL می‌تواند از طریق HTTP GET انجام شود و لازم نیست حتماً JSON در Body داشته باشد. شکل بالا قرارداد منطقی پیام را نشان می‌دهد.

#### حالت اول: درخواست در حال پردازش است

```json
{
  "protocol": "mt5-gateway",
  "version": 1,
  "message_type": "POLL_RESULT",
  "client_id": "mt5_terminal_01",
  "request_id": "mt5_terminal_01-000001",
  "status": "PROCESSING",
  "response_id": null,
  "payload": null
}
```

در این مرحله:

- درخواست در Python ثبت شده است.
- پردازش هنوز تمام نشده است.
- هنوز پاسخی ایجاد نشده است.
- `response_id` وجود ندارد.

#### حالت دوم: پردازش موفق و پاسخ ذخیره شده است

```json
{
  "protocol": "mt5-gateway",
  "version": 1,
  "message_type": "POLL_RESULT",
  "client_id": "mt5_terminal_01",
  "request_id": "mt5_terminal_01-000001",
  "status": "COMPLETED",
  "response_id": "resp-000001",
  "created_at": "2026-11-15T12:31:00Z",
  "payload": {
    "result": "Analysis completed",
    "data": {}
  }
}
```

در این مرحله:

- Python پردازش را تمام کرده است.
- پاسخ را به‌صورت پایدار ذخیره کرده است.
- `response_id` ایجاد شده است.
- MT5 می‌تواند پاسخ را دریافت و بررسی کند.

#### حالت سوم: پردازش با خطا تمام شده است

```json
{
  "protocol": "mt5-gateway",
  "version": 1,
  "message_type": "POLL_RESULT",
  "client_id": "mt5_terminal_01",
  "request_id": "mt5_terminal_01-000001",
  "status": "FAILED",
  "response_id": "resp-000002",
  "created_at": "2026-11-15T12:31:00Z",
  "payload": {
    "error": {
      "code": "PROCESSING_ERROR",
      "message": "Processing failed"
    }
  }
}
```

نکته مهم:

`FAILED` به معنی پایان چرخه تحویل نیست.

حتی پاسخ خطا نیز باید به MT5 تحویل داده شود و ACK دریافت کند.

---

### 6. پیام ACK

پس از اینکه MT5 پاسخ را دریافت و مصرف کرد، ACK ارسال می‌کند.

```json
{
  "protocol": "mt5-gateway",
  "version": 1,
  "message_type": "ACK",
  "client_id": "mt5_terminal_01",
  "request_id": "mt5_terminal_01-000001",
  "response_id": "resp-000001",
  "created_at": "2026-11-15T12:32:00Z"
}
```

وجود هر دو شناسه ضروری است:

- `request_id` مشخص می‌کند پاسخ متعلق به کدام درخواست است.
- `response_id` مشخص می‌کند دقیقاً کدام پاسخ تأیید می‌شود.

#### پاسخ Python به ACK

```json
{
  "protocol": "mt5-gateway",
  "version": 1,
  "message_type": "ACK_RESULT",
  "client_id": "mt5_terminal_01",
  "request_id": "mt5_terminal_01-000001",
  "response_id": "resp-000001",
  "status": "ACKNOWLEDGED"
}
```

MT5 فقط پس از دریافت و اعتبارسنجی این تأییدیه اجازه دارد درخواست مربوطه را از صف محلی حذف کند.

---

### 7. چرخه کامل وضعیت درخواست

چرخه کامل از ابتدا به این شکل تعریف می‌شود:

```text
CREATED
   ↓
SENDING
   ↓
SENT
   ↓
REGISTERED
   ↓
PROCESSING
   ↓
COMPLETED / FAILED
   ↓
RESPONSE_RECEIVED
   ↓
ACK_SENT
   ↓
ACKNOWLEDGED
```

مالکیت وضعیت‌ها:

| Status | Owner | Meaning |
|---|---|---|
| CREATED | MT5 | درخواست ساخته و محلی ذخیره شده |
| SENDING | MT5 | ارسال در حال انجام است |
| SENT | MT5 | ارسال از دید لایه ارتباطی انجام شده |
| REGISTERED | Python | درخواست به‌صورت پایدار ثبت شده |
| PROCESSING | Python | پردازش درخواست در جریان است |
| COMPLETED | Python | پردازش موفق و پاسخ ذخیره شده |
| FAILED | Python | پردازش ناموفق و پاسخ خطا ذخیره شده |
| RESPONSE_RECEIVED | MT5 | پاسخ دریافت و اعتبارسنجی شده |
| ACK_SENT | MT5 | پیام ACK ارسال شده |
| ACKNOWLEDGED | MT5 / Python | تأیید ACK از Python دریافت شده |

توجه:

`SENT` به معنی `REGISTERED` نیست.

`COMPLETED` یا `FAILED` به معنی `ACKNOWLEDGED` نیست.

---

### 8. قوانین تحویل مطمئن

1. MT5 باید قبل از اولین ارسال، درخواست را در ذخیره‌سازی محلی ثبت کند.

2. هر درخواست باید `request_id` یکتا داشته باشد.

3. تمام Retryهای یک درخواست باید همان `request_id` را حفظ کنند.

4. Python باید درخواست‌های تکراری را تشخیص دهد.

5. اگر `request_id` تکراری با محتوای یکسان دریافت شد، Python نباید درخواست را دوباره اجرا کند؛ باید وضعیت موجود آن را برگرداند.

6. اگر `request_id` یکسان با محتوای متفاوت دریافت شد، درخواست باید رد شود.

7. Python فقط پس از ذخیره پایدار درخواست می‌تواند `REGISTERED` برگرداند.

8. Python فقط پس از ایجاد و ذخیره پایدار پاسخ می‌تواند `response_id` اختصاص دهد.

9. پاسخ باید همیشه به `request_id` اصلی متصل باشد.

10. ACK باید هم `request_id` و هم `response_id` را مشخص کند.

11. دریافت پاسخ توسط MT5 بدون تأیید ACK به معنی پایان چرخه نیست.

12. MT5 فقط پس از دریافت `ACKNOWLEDGED` می‌تواند درخواست محلی را حذف کند.

13. Timeout یا قطع ارتباط به معنی شکست قطعی پردازش نیست؛ ممکن است عملیات در سمت Python انجام شده باشد.

14. درخواست‌ها در نسخه اول ترتیبی پردازش می‌شوند و فقط یک درخواست حل‌نشده در هر لحظه مجاز است.

---

### 9. قواعد شناسه‌ها

| Identifier | Generated By | Created When | Lifetime |
|---|---|---|---|
| client_id | MT5 | زمان راه‌اندازی/پیکربندی ترمینال | پایدار |
| request_id | MT5 | هنگام ایجاد درخواست | از ابتدا تا پایان چرخه |
| response_id | Python | هنگام ایجاد و ذخیره پاسخ | از ایجاد پاسخ تا پایان نگهداری آن |

`response_id` در مراحل REGISTERED و PROCESSING مقدار ندارد.

این موضوع کاملاً طبیعی است و نباید به‌عنوان خطا تفسیر شود.

---

### 10. دامنه پیاده‌سازی نسخه اول

قرارداد از ابتدا چرخه کامل را پوشش می‌دهد، اما پیاده‌سازی مرحله‌ای خواهد بود:

1. تولید و ذخیره پایدار `request_id` در MT5.
2. ارسال INGEST و ثبت پایدار درخواست در Python.
3. تأیید REGISTERED.
4. پیاده‌سازی پردازش ترتیبی.
5. ذخیره پایدار پاسخ و تولید `response_id`.
6. پیاده‌سازی POLL و دریافت پاسخ.
7. پیاده‌سازی ACK و تأیید ACKNOWLEDGED.
8. حذف امن درخواست از ذخیره‌سازی محلی MT5.

هدف این است که از ابتدا قرارداد کامل و قابل توسعه داشته باشیم، اما هر مرحله را جداگانه آزمایش کنیم.
