# دليل المطورين والبناء (Developer & Build Guide) — VocalPro v3.0.0

يوضح هذا الدليل بنية الكود المصدري لـ **VocalPro v3.0.0** وكيفية تشغيل بيئة التطوير أو بناء حزم التوزيع على نظام Windows.

---

## 1. هيكلة المشروع (Repository Structure)

```text
vocal-pro-rebuild/
├── src/                    # واجهة React 19 + TypeScript + Tailwind + Zustand
│   ├── screens/            # شاشات Home, Separation, Results, History, Settings
│   ├── components/         # CanvasWaveform, StemMixerStrip, JobQueueBar, Sidebar
│   ├── i18n/               # الترجمات (16 لغة تشمل العربية RTL)
│   └── bindings.ts         # عقود التواصل مع خلفية Rust
├── src-tauri/              # نواة التطبيق المبنية بـ Rust + Tauri v2
│   └── src/
│       ├── audio/          # فك تشفير Symphonia، حساب الموجات، الميكسر، التصدير
│       ├── db/             # قاعدة بيانات SQLite WAL وترحيل الإعدادات القديمة
│       ├── worker/         # إدارة عمليات Python Worker والطابور وبروتوكول JSONL
│       ├── models/         # إدارة النماذج والتحقق من بصمات SHA-256
│       └── system/         # فحص العتاد وCUDA والتكامل مع نظام Windows
├── worker/                 # محرك الذكاء الاصطناعي ومعالجة الصوت بـ Python
│   ├── vocalpro_worker/    # protocol, engine, dsp, analysis, midi, hardware, model_installer
│   └── tests/              # اختبارات الوحدة، التطابق الرياضي (Null Tests)، والتغليف
├── schemas/                # مخطط JSON-Lines للبروتوكول بين Rust وPython
├── benchmarks/             # أدوات توليد المراجع الصوتية وقياس الجودة
├── tests/                  # اختبارات الواجهة (Node .mjs) واختبارات E2E الشاملة
├── scripts/                # سكريبتات إعداد المحرك وبناء المُثبّت وفحص الجاهزية
├── release/                # مشغّل Start-VocalPro.bat وvocalpro.exe للاستخدام المباشر مع ../worker
├── docs/                   # أدلة المستخدم، GUI، الإعدادات، الاختبار، والتراخيص
├── installer.iss           # سكريبت بناء المُثبّت الشامل بـ Inno Setup 6
├── setup.bat / run.bat     # تهيئة وتشغيل المشروع مباشرة على Windows
└── .github/workflows/      # تدفقات البناء والاختبار ci.yml و release.yml
```

---

## 2. متطلبات التطوير المحلي

1. **Node.js 20 أو 22 LTS** (`npm`).
2. **Python 3.10 – 3.12** (غير متوافق مع `3.13+` بسبب اعتماد بعض إضافات Demucs/PyTorch).
3. **Rust Stable Toolchain** (`cargo` و`rustc`) + أدوات **Visual Studio Build Tools (C++ Desktop)** لتجميع `src-tauri`.
4. **Inno Setup 6** (اختياري لبناء ملف التثبيت `.exe` محلياً عبر `installer.iss`).
5. **FFmpeg** في `PATH` أو ضمن الحزمة لتصدير صيغ الصوت المضغوطة والفيديو.

---

## 3. الإعداد والتشغيل في وضع التطوير

### الإعداد السريع على Windows
```bat
setup.bat
```
ثم للتشغيل:
```bat
run.bat
```
*(في حال وجود `release\vocalpro.exe` يعمل التطبيق فوراً بالاعتماد على `worker/`، أو يمكنك تمرير `run.bat --dev` للتشغيل في وضع التطوير).*

### أوامر التطوير اليدوية
```bash
# 1. تثبيت حزم الواجهة وبناؤها
npm install
npm run build

# 2. تشغيل التطبيق الأصلي (Rust + Tauri v2 + React)
npm run tauri:dev

# 3. أو تشغيل واجهة الويب فقط للمعاينة السريعة
npm run dev
```

---

## 4. بناء حزم الإطلاق والمُثبّت (Build & Release Packaging)

### بناء التطبيق محلياً
```bash
npm run build
npm run tauri:build
```
أو عبر سكريبت التجهيز الكامل للمُثبّت على Windows:
```bat
scripts\build_standalone_installer.bat
```

### التجميع الآلي عبر GitHub Actions
يحتوي المستودع على مسارين في `.github/workflows/`:
- **[`ci.yml`](../.github/workflows/ci.yml):** يفحص التجميع والاختبارات عبر `windows-latest` و`ubuntu-latest` و`macos-latest` بالإضافة إلى اختبارات الواجهة وPython Worker، ويرفع ملف `vocalpro.exe` المُجمّع.
- **[`release.yml`](../.github/workflows/release.yml):** يبني تطبيق Tauri، يجهز Python 3.11 Embeddable مع PyTorch وDemucs وFFmpeg ونموذج `htdemucs`، يجمع **`VocalPro-v3.0.0-AllInOne-Setup.exe`** عبر Inno Setup 6 وينشئ **`VocalPro-v3.0.0-Windows.zip`**، ثم ينشرهما مباشرة على صفحة **GitHub Releases**.
