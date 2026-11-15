# دليل الاختبار والفحص (Testing Guide) — VocalPro v3.0.0

يغطي هذا الدليل كل ما يحتاجه المستخدم أو المطور للتحقق من سلامة التطبيق قبل الاستخدام أو بعد تعديل الكود:
1. الفحص الذاتي السريع للبرنامج المثبّت (`--selftest`).
2. تشغيل حزم الاختبارات الآلية (Frontend، Python Worker، Packaging، E2E، Rust Core).
3. قائمة التحقق اليدوية على نظام Windows 10/11.

---

## 1. الفحص الذاتي الفوري للنسخة المثبّتة (`--selftest`)

بعد تثبيت البرنامج عبر `VocalPro-v3.0.0-AllInOne-Setup.exe` أو تشغيله من مجلد `release/`، يمكنك التحقق من سلامة النواة، وقاعدة البيانات، وتسجيل النماذج الـ 8، وتشغيل محرك Python الفعلي بالأمر التالي في PowerShell:

```powershell
python -c "import subprocess; r = subprocess.run([r'vocalpro.exe', '--selftest'], capture_output=True, text=True); print(r.stdout); print('Exit:', r.returncode)"
```

*(نستخدم `subprocess` لالتقاط المخرجات لأن `vocalpro.exe` يعمل بوضع نافذة Windows GUI).*

النتيجة السليمة تُظهر:
- `"selftest": "PASS"`
- `"status": "READY_FOR_SHIPPING"`
- `"worker_running": true`
- رمز خروج `0`.

---

## 2. الاختبارات الآلية من الكود المصدري (Automated Suites)

### أ. اختبارات واجهة المستخدم وTypeScript
```bash
npm install
npm run typecheck
npm run build
```
وتوجد اختبارات حالة الواجهة والميكسر في مجلد `tests/`:
```bash
node tests/test_frontend_state_adversarial.mjs
node tests/adversarial_m4_verification.mjs
node tests/adversarial_m4_challenger2_verification.mjs
node tests/test_m5_frontend_stress.mjs
```

### ب. اختبارات محرك الذكاء الاصطناعي والـ Packaging (`pytest`)
> تأكد أولاً من توليد ملفات المرجع الصوتية عند تشغيل حزمة الاختبار الكاملة على جهاز جديد:
```bash
python benchmarks/generate_reference_set.py
python -m pytest worker/tests -v
```
ولاختبار قواعد المُثبّت (`installer.iss`) والملفات التنفيذية وسكريبتات `.bat` فقط (سريع ~7 ثوانٍ):
```bash
python -m pytest worker/tests/test_m3_packaging_and_installer.py worker/tests/test_m3_challenger_1_adversarial.py worker/tests/test_m3_challenger_2_adversarial.py -v
```

### ج. اختبارات الـ E2E الشاملة (4 مستويات Black-Box)
```bash
python -m pytest tests/e2e -v
```
أو عبر المشغّل الموحد:
```bash
python tests/e2e/run_e2e.py
```

### د. اختبارات نواة Rust والتكامل (يتطلب Cargo / Rust)
```bash
cargo test --manifest-path src-tauri/Cargo.toml
```

### هـ. فحص الجاهزية الموحد (Shipping Readiness Script)
```bash
python scripts/verify_shipping_readiness.py
```

---

## 3. قائمة الاختبار اليدوي على Windows 10/11

للتأكد العملي من الميزات التي تتطلب تفاعلاً مباشراً مع واجهة ويندوز وعتاد الصوت والشاشة:

- [ ] **التثبيت والتشغيل الأول بدون إنترنت (Offline Verification):**
  1. ثبّت `VocalPro-v3.0.0-AllInOne-Setup.exe` على جهاز نظيف أو افصل الإنترنت.
  2. شغّل التطبيق، وتأكد من ظهور نموذج `htdemucs` جاهزاً دون محاولة تنزيل.
- [ ] **النافذة وصينية النظام (Always on Top & System Tray):**
  1. من **Settings** فعّل **Window Always on Top** وتأكد من بقاء النافذة فوق باقي النوافذ.
  2. فعّل **Minimize to System Tray** وقم بتصغير/إغلاق النافذة للتأكد من بقاء الأيقونة في شريط المهام وإمكانية استعادتها.
- [ ] **السحب والإفلات وربط الصيغ (Drag & Drop / File Associations):**
  1. اسحب ملف `.mp3` أو `.mp4` بمسار يحتوي على أحرف عربية ومسافات من File Explorer مباشرة إلى نافذة التطبيق.
  2. جرّب أزرار **Register File Associations** و**Create Desktop Shortcut** من الإعدادات وتحقق من ظهور الاختصار وعمل الفتح المزدوج.
- [ ] **تشغيل الميكسر الفعلي والسماعات (WASAPI Live Playback):**
  1. افصل أغنية كاملة، وشغّل المسارات في شاشة **Results**.
  2. بدّل بين أزرار **Solo** و**Mute** وغيّر شريط التمرير (**Volume / Pan / Seek**) وتأكد من عدم وجود تقطيع أو فقدان تزامن.
- [ ] **التصدير المتعدد وتحويل MIDI:**
  1. صدّر مزيجاً بصيغ `WAV (24-bit)` و`FLAC` و`MP3`، واستخرج ملف `.mid` من مسار الغناء وتأكد من إمكانية تشغيل جميع الملفات الناتجة.
- [ ] **فيديو السينما (Video Remux):**
  1. أدخل مقطع فيديو `.mp4`، واختر إخراج فيديو بدون غناء (**Instrumental Video**)، وتأكد من تزامن الصورة مع الصوت الناتج.
- [ ] **تسريع البطاقة الرسومية (CUDA GPU — إن وجدت):**
  1. على جهاز به بطاقة NVIDIA متوافقة، شغّل **Auto-Tune for Hardware** وتأكد من استخدام `cuda` وإتمام الفصل بسرعة أعلى مع سلامة الذاكرة في المهام المتتابعة.
