# VocalPro v3.0.0 — Windows Release

هذا المجلد يحتوي على النسخة المترجمة الجاهزة للتشغيل للمستخدم النهائي مباشرة (**Production Release**).

---

## ⚡ خيارات التحميل المباشر (Direct Downloads):

### 1️⃣ الخيار الموصى به للمستخدم النهائي: مثبت ويندوز المتكامل (Windows Setup Installer)
* استخدم مثبت `VocalPro-v3.0.0-Windows-Setup.exe` من صفحة [GitHub Releases](https://github.com/lam3y35/vocal-pro-rebuild/releases) لتثبيت التطبيق مع بيئة Python والـ Worker والنماذج المسبقة التحميل بشكل كامل.

### 2️⃣ الحزمة المحمولة الكاملة مضغوطة (Portable ZIP)
👈 **[اضغط هنا لتحميل VocalPro-v3.0.0-Windows.zip مباشرة](https://github.com/lam3y35/vocal-pro-rebuild/raw/main/release/VocalPro-v3.0.0-Windows.zip)**  
* عند التشغيل لأول مرة على جهاز لا يحتوي على التثبيت الكامل، فك الضغط ثم شغّل **`Start-VocalPro.bat`** أولاً لتهيئة بيئة Python AI وتمرير أي ملفات صوت/فيديو مسحوبة إلى `vocalpro.exe` (ومع بقاء مجلد `worker/` بجانبهما).
* تأكد من توفر `ffmpeg` في PATH أو تحديد مساره داخل **Settings -> FFmpeg Path** للتصدير بصيغ MP3/FLAC والفيديو.

---

## 📂 محتويات هذا المجلد:
* **`VocalPro-v3.0.0-Windows.zip`**: الحزمة المجمعة الكاملة (تحتوي على `vocalpro.exe` و `Start-VocalPro.bat` و `worker/`).
* **`vocalpro.exe`**: ملف التشغيل المترجم بلغة Rust و Tauri v2 (يعمل مع مجلد `worker/` المجاور).
* **`Start-VocalPro.bat`**: مشغل مساعد للمستخدم يقوم بالفحص والتشغيل.
* **`worker/`**: محرك معالجة وعزل المسارات الصوتية بالذكاء الاصطناعي.
