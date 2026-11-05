# دفترچه وضعیت پروژه Rezvan – LLM Gateway

**تاریخ آخرین به‌روزرسانی:** ۶ نوامبر ۲۰۲۶  
**وضعیت:** Laravel بازیابی شده؛ FastAPI هنوز از طریق وب قابل دسترسی نیست.

---

## ۱. هدف اصلی پروژه

ساخت یک درگاه واسط هوش مصنوعی (Multi-Model Gateway) که بتواند درخواست‌های برنامه‌های مختلف را دریافت کند و از میان تعداد زیادی مدل هوش مصنوعی، مدلی را که پاسخ معتبر می‌دهد انتخاب کند.

دو مصرف‌کنندهٔ اصلی پروژه:

1. **Codex در ویندوز**
   - کاربر در ترمینال ویندوز با Codex کار می‌کند.
   - Codex درخواست را از طریق Responses API به Gateway می‌فرستد.
   - Gateway مدل‌های مختلف را امتحان می‌کند.
   - در صورت دریافت پاسخ معتبر، پاسخ را به شکل Stream به Codex برمی‌گرداند.

2. **MetaTrader**
   - اتصال آن در حال پیاده‌سازی است.
   - قرار است از همان موتور انتخاب مدل و مدیریت ارائه‌دهندگان استفاده کند.

هدف این است که یک Gateway مشترک برای چند مصرف‌کننده داشته باشیم.

## ۲. مخزن GitHub

آدرس مخزن:

https://github.com/farshad-ir/work-with-LLMs

ساختار اصلی برنامه Python:

- `app/main.py`
- `app/model_rotation.py`
- `app/responses_adapter.py`
- `passenger_wsgi.py`

فایل‌های مهم دیگر شامل تنظیمات و فهرست مدل‌ها هستند که باید در بررسی کامل مخزن شناسایی شوند.

## ۳. معماری فعلی Gateway

Gateway فعلی با Python و FastAPI نوشته شده است.

قابلیت‌های مهم:

- دریافت درخواست از مسیر `POST /v1/responses`
- سازگاری با قالب Responses API مورد انتظار Codex
- تبدیل درخواست‌ها به قالب Chat Completions برای ارائه‌دهندگان مختلف
- مدیریت فهرست مدل‌ها و ارائه‌دهندگان
- انتخاب مدل بعدی در صورت شکست مدل قبلی
- بررسی خطاهای HTTP و خطاهای اتصال
- تبدیل پاسخ ارائه‌دهندگان به قالب مورد انتظار Codex
- پشتیبانی از SSE و Stream
- مدیریت وضعیت مدل‌ها با وضعیت‌هایی مانند:
  - `untested`
  - `in_progress`
  - `confirmed`
  - `failed`

نکتهٔ فنی مهم:

اگر ارائه‌دهنده قبل از شروع Stream خطای HTTP بدهد، Gateway می‌تواند مدل بعدی را امتحان کند.

اما پس از شروع ارسال Stream به Codex، تغییر مدل به‌سادگی ممکن نیست؛ زیرا بخشی از پاسخ قبلاً ارسال شده است.

این رفتار باید در هر تغییر معماری حفظ شود.

## ۴. مشخصات سرور و میزبانی

- دامنه: `rezvan.biz`
- سرور: `nhs03.azaronline.com`
- حساب cPanel: `yhkcinki`
- IP ثبت‌شده در cPanel: `85.17.55.241`

مسیر Laravel:

`/home/yhkcinki/rezvan`

مسیر Public پروژه Laravel:

`/home/yhkcinki/rezvan/public`

Document Root دامنه در cPanel:

`/home/yhkcinki/rezvan/public`

مسیر FastAPI:

`/home/yhkcinki/apps/work-with-LLMs`

محیط مجازی Python:

`/home/yhkcinki/virtualenv/apps/work-with-LLMs/3.12`

نسخه Python:

`3.12.16`

نکته: پوشه `public_html` مستقل از پوشه `rezvan/public` است و نباید فایل‌های Laravel را به آن منتقل کرد.

دسترسی مدیریتی WHM و root هنوز مشخص نشده است.

## ۵. وضعیت Laravel

Laravel روی دامنه اصلی اجرا می‌شود.

نتیجه اجرای:

```bash
php artisan about
```

اطلاعات مهم:

- Laravel: `13.32.0`
- PHP: `8.4.27`
- Environment: `production`
- Debug Mode: `OFF`
- Maintenance Mode: `OFF`
- Database: `mysql`
- Session: `database`
- Queue: `database`

آدرس زیر با موفقیت پاسخ HTTP 200 داده است:

`https://rezvan.biz/login`

سایت در مرورگر نیز باز شده است.

بنابراین Laravel در وضعیت بازیابی‌شده قرار دارد.

## ۶. وضعیت FastAPI و Passenger

تنظیمات CloudLinux Python Selector:

- Application Root:
  `apps/work-with-LLMs`
- Startup File:
  `passenger_wsgi.py`
- Entry Point:
  `application`
- Python:
  `3.12`
- Application URI:
  `/llm`

فایل فعلی `passenger_wsgi.py`:

```python
import os
import sys

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_ROOT)

from app.main import app as asgi_app
from a2wsgi import ASGIMiddleware

application = ASGIMiddleware(asgi_app)
```

تست Import برنامه موفق بوده است.

دستور تست:

```bash
cd ~/apps/work-with-LLMs && /home/yhkcinki/virtualenv/apps/work-with-LLMs/3.12/bin/python -c "from passenger_wsgi import application; print('WSGI APPLICATION OK')"
```

نتیجه:

`WSGI APPLICATION OK`

همچنین اجرای دستی Uvicorn روی آدرس داخلی `127.0.0.1:8000` موفق بوده و مسیر `/health` پاسخ زیر را داده است:

```json
{
  "status": "ok",
  "app": "MyCode Gateway",
  "version": "0.1.0"
}
```

بنابراین کد FastAPI و Adapter در تست‌های داخلی قابل اجرا بوده‌اند.

مشکل حل‌نشده، اجرای برنامه از طریق وب‌سرور و اتصال Passenger به دامنه است.

## ۷. تغییراتی که برای بازیابی Laravel انجام شد

در جریان آزمایش FastAPI، Application URI موقتاً روی ریشه دامنه (`/`) قرار گرفته بود.

برای بازیابی Laravel، URI به `/llm` برگردانده شد:

```bash
cloudlinux-selector set --json --interpreter python --user yhkcinki --app-root apps/work-with-LLMs --new-app-uri llm --skip-web-check
```

نتیجه:

`success`

سپس فایل `.htaccess` اصلی Laravel بازیابی شد:

```bash
cp -p ~/rezvan/public/.htaccess.before-fastapi-test ~/rezvan/public/.htaccess
```

در فایل `.htaccess` فعلی این قانون وجود دارد:

```apache
RewriteRule ^llm(/|$) - [L]
```

این قانون مسیر `/llm` را از Rewrite مربوط به Laravel مستثنا می‌کند.

## ۸. نسخه‌های پشتیبان

در مسیر:

`~/rezvan/public/`

سه نسخهٔ مهم وجود دارند:

1. `.htaccess.before-fastapi-test`
2. `.htaccess.bak`
3. `.htaccess.after-passenger-root`

فایل فعلی `.htaccess` از نسخهٔ اول بازیابی شده است:

`.htaccess.before-fastapi-test`

هر سه نسخه باید حفظ شوند.

هیچ‌کدام حذف یا بازنویسی نشوند تا ابتدا تفاوت‌هایشان بررسی شود.

همچنین در مسیر:

`~/rezvan/public/llm/`

فایل تولیدشده توسط CloudLinux Passenger وجود دارد.

محتوای تنظیمات آن شامل:

- PassengerAppRoot
- PassengerBaseURI `/llm`
- PassengerPython
- PassengerAppLogFile

این فایل را نباید بدون بررسی تغییر داد یا حذف کرد.

## ۹. تصمیم معماری فعلی

فعلاً بازنویسی Python به Laravel انجام نشود.

پیشنهاد فعلی:

- Python و FastAPI موتور اصلی Gateway باقی بمانند.
- Laravel برای وب‌سایت، مدیریت کاربران، پنل مدیریت و تنظیمات استفاده شود.
- MetaTrader و Codex در نهایت از یک Gateway مشترک استفاده کنند.

دلیل حفظ Python:

- منطق اصلی Gateway آماده است.
- Model Rotation پیاده‌سازی شده است.
- Responses API Adapter وجود دارد.
- استریم پاسخ پیاده‌سازی شده است.
- بازنویسی کامل در PHP هزینه و ریسک غیرضروری دارد.

با این حال، Laravel نیز از نظر فنی قادر به اجرای این وظایف است. انتخاب Python به دلیل حفظ کد موجود و معماری فعلی است، نه برتری قطعی سرعت آن.

## ۱۰. برنامه ادامه کار

### مرحله اول: بررسی دسترسی مدیریتی سرور

مشخص شود آیا دسترسی به WHM و root وجود دارد یا فقط cPanel و SSH کاربر `yhkcinki` در اختیار است.

### مرحله دوم: بررسی دقیق وضعیت Passenger

بدون دست‌زدن به Laravel بررسی شود:

- وضعیت واقعی برنامه در CloudLinux Selector
- تنظیمات Passenger
- لاگ‌های جدید
- وضعیت فرایندهای Python
- تنظیمات VirtualHost و وب‌سرور

### مرحله سوم: تست Gateway در مسیر مستقل

آدرس مورد انتظار:

`https://rezvan.biz/llm/health`

این تست فقط پس از تأیید وضعیت Laravel انجام شود.

### مرحله چهارم: انتخاب روش اجرای Python

اولویت‌ها:

1. اصلاح اجرای FastAPI از طریق Passenger در مسیر `/llm`
2. بررسی امکان اجرای پایدار Python از طریق امکانات موجود همین سرور
3. در صورت وجود محدودیت واقعی سرور، بررسی راهکار جایگزین

تا زمانی که امکانات واقعی سرور مشخص نشده‌اند، نباید VPS دیگری خریداری شود یا معماری پروژه تغییر کند.

### مرحله پنجم: اتصال Codex

پس از موفقیت `/llm/health`، اتصال واقعی Codex در ویندوز آزمایش شود.

باید موارد زیر بررسی شوند:

- سازگاری Responses API
- احراز هویت
- انتخاب مدل
- مدیریت خطا
- Stream
- فراخوانی ابزارها

### مرحله ششم: تکمیل اتصال MetaTrader

پس از تثبیت Gateway، اتصال MetaTrader به موتور مشترک تکمیل شود.

## ۱۱. دستورالعمل مهم برای ادامه کار

- ابتدا وضعیت فعلی را بررسی کن؛ هیچ فرضی را قطعی ندان.
- Laravel سالم است؛ تنظیمات آن را بی‌دلیل تغییر نده.
- فایل‌های پشتیبان را حذف نکن.
- Document Root را تغییر نده.
- فایل‌های Laravel را به `public_html` منتقل نکن.
- Passenger و `.htaccess` تولیدشده توسط CloudLinux را بدون بررسی دست‌کاری نکن.
- قبل از هر تغییر، نسخه پشتیبان تهیه کن.
- در هر مرحله فقط یک دستور اجرا شود.
- بعد از اجرای دستور، خروجی آن بررسی شود و سپس مرحله بعد آغاز گردد.
- از تغییر هم‌زمان چند فایل یا تنظیمات خودداری شود.
- هیچ رمز عبور، API Key یا Token در گزارش‌ها و فایل‌های عمومی قرار نگیرد.

## ۱۲. نقطه شروع گفت‌وگوی بعدی

ابتدا این سند و مخزن GitHub را بررسی کن.

سپس با توجه به وضعیت فعلی، بدون تغییر فایل‌ها، بررسی را از این سؤال شروع کن:

**چرا FastAPI که در تست داخلی Python و WSGI سالم است، از طریق Passenger و مسیر `/llm` در وب‌سرور قابل دسترسی نیست؟**

هدف این است که Gateway فعلی روی همین سرور اجرا شود، بدون اینکه Laravel یا سایت اصلی آسیب ببیند.

اصل مهم پروژه:

**اول حفظ وضعیت سالم فعلی، سپس تشخیص دقیق، بعد تغییر کنترل‌شده.**
