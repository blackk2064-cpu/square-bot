# Binance Square Auto-Poster

بوت بسيط بينشر تحديثات سوق تلقائيًا على حسابك في Binance Square كل ساعة،
باستخدام الـ **Square OpenAPI الرسمي**.

## 1) هات مفتاح الـ API

من تطبيق/موقع باينانس → حسابك على Square → **Creator Center** →
اطلب **Square OpenAPI Key**. احفظه، ومتشاركهوش مع حد.

## 2) الطريقة الأسهل والمجانية للتشغيل 24/7: GitHub Actions

1. اعمل حساب GitHub لو مش عندك، وارفع الملفات دي في repo (يفضل **Private**).
2. من إعدادات الـ repo: **Settings → Secrets and variables → Actions → New repository secret**
   - الاسم: `SQUARE_OPENAPI_KEY`
   - القيمة: المفتاح اللي جبته من باينانس
3. الملف `.github/workflows/hourly_post.yml` هيشغّل البوت تلقائيًا كل ساعة —
   مفيش سيرفر تحتاج تدفع له أو تصلّحه.
4. تقدر تجرب تشغيل يدوي فورًا من تبويب **Actions** في الـ repo
   (زرار "Run workflow").

## 3) بديل: سيرفر/VPS خاص بك

لو عايز تشغله على سيرفر بتديره بنفسك (مثلاً DigitalOcean/AWS):

```bash
pip install -r requirements.txt
export SQUARE_OPENAPI_KEY="your_key_here"
python square_bot.py
```

وضيفه على cron يشتغل كل ساعة:

```
0 * * * * cd /path/to/square_bot && SQUARE_OPENAPI_KEY="your_key" python3 square_bot.py >> bot.log 2>&1
```

## ملاحظات مهمة

- الحد الأقصى الرسمي للنشر: **100 بوست/يوم** — البوت بينشر بوست واحد كل
  ساعة (24 يوميًا)، فمريح جدًا تحت الحد.
- الـ API فيه فلترة محتوى حساسة (sensitive content detection) — لو بوست
  اتحظر، البوت هيطبع رسالة الخطأ من باينانس.
- الأسعار/البيانات بتيجي من الـ Public API المجاني بتاع باينانس (من غير
  أي مفتاح)، فمفيش خطر على حسابك من ناحية القراءة.
- الملف ده بينشر بوستات جديدة بس — مفيش دعم رسمي حاليًا للايك أو الرد
  التلقائي على بوستات تانية، فمتضيفوش ده لوحدك عشان مش هتلاقي API رسمي
  ليه وهيكون ضد شروط الاستخدام.
