# VocalPro v3.0.0 — استوديو فصل الصوتيات بالذكاء الاصطناعي

**VocalPro v3.0.0** هو تطبيق سطح مكتب متكامل يعمل بالكامل محلياً (**100% Offline & Private**) لفصل الصوت والموسيقى والمسارات المتعددة (Vocals / Instrumental / 4-Stem / 6-Stem) ومعالجة صوتيات الفيديو وتحويل الغناء إلى MIDI، مبني باستخدام **Tauri v2 (Rust)** و**React 19** ومحرك **PyTorch / Demucs**.

---

## 📥 خيارات التحميل والتشغيل (Download Options)

اختر الطريقة المناسبة لك مباشرة من صفحة الإصدارات الرسمية على GitHub Releases:

### 1️⃣ المُثبّت الشامل للويندوز — **الخيار الموصى به (All-in-One Installer)**
> **ملف واحد شامل لا يحتاج إلى أي إعداد مسبق أو تحميلات إضافية.**

* ⬇️ **[تحميل VocalPro-v3.0.0-AllInOne-Setup.exe (~332 MB)](https://github.com/lam3y35/vocal-pro-rebuild/releases/download/v3.0.0/VocalPro-v3.0.0-AllInOne-Setup.exe)**
* **ماذا يتضمن؟** التطبيق بالكامل + محرك Python 3.11 المعزول + مكتبات PyTorch/Demucs + أداة `ffmpeg.exe` + نموذج الفصل الافتراضي `htdemucs` جاهزاً للعمل **بدون إنترنت** فور انتهاء التثبيت.

### 2️⃣ النسخة المحمولة الخفيفة — **بدون تثبيت (Portable ZIP)**
* ⬇️ **[تحميل VocalPro-v3.0.0-Windows.zip (~5.3 MB)](https://github.com/lam3y35/vocal-pro-rebuild/releases/download/v3.0.0/VocalPro-v3.0.0-Windows.zip)**
* **طريقة التشغيل:** فك ضغط الملف في أي مجلد ثم شغّل **`Start-VocalPro.bat`** لتهيئة بيئة Python AI (يتطلب Python 3.10–3.12 على الجهاز في أول تشغيل فقط)، مع إبقاء مجلد `worker/` بجانب `vocalpro.exe`.

### 3️⃣ الكود المصدري ووضع المطورين (Source Code)
* تصفح جميع الإصدارات: **[صفحة GitHub Releases (`v3.0.0`)](https://github.com/lam3y35/vocal-pro-rebuild/releases/tag/v3.0.0)**
* لتشغيل التطبيق من الكود المصدري على ويندوز:
  ```bat
  git clone https://github.com/lam3y35/vocal-pro-rebuild.git
  cd vocal-pro-rebuild
  setup.bat
  run.bat
  ```

---

## 📚 الأدلة والشروحات (Documentation)

| الدليل | الوصف | الرابط |
|---|---|---|
| **دليل استخدام التطبيق** | التثبيت، التشغيل الأول، فصل الصوتيات والفيديو، الميكسر، التصدير، والعمل بدون إنترنت | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) |
| **دليل الواجهة الرسومية** | شرح شاشات البرنامج وأدوات التحكم مدعوماً بلقطات الشاشة الحقيقية | [docs/GUI_GUIDE.md](docs/GUI_GUIDE.md) |
| **دليل الإعدادات المتقدمة** | مرجع شامل لكل خيار ومعامل وجودة فصل (`Shifts`، `Overlap`، `DSP`، إلخ) | [docs/SETTINGS_GUIDE.md](docs/SETTINGS_GUIDE.md) |
| **العرض التفاعلي للبرنامج** | صفحة HTML تفاعلية تشرح المعمارية وحاسبة المساحة | [docs/why_vocalpro_v3.html](docs/why_vocalpro_v3.html) |
| **دليل الاختبار والفحص** | اختبار النسخة المثبتة، الاختبارات الآلية (`pytest` / `cargo` / Frontend)، والفحص اليدوي على Windows | [docs/TESTING_GUIDE.md](docs/TESTING_GUIDE.md) |
| **دليل التطوير والبناء** | هيكلة المشروع، البناء من المصدر، وتجهيز حزم الإطلاق | [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) |
| **تراخيص المكتبات** | قائمة المكتبات مفتوحة المصدر المستخدمة وتراخيصها | [docs/licenses/THIRD_PARTY.md](docs/licenses/THIRD_PARTY.md) |

---

## ✨ أبرز المميزات (Key Features)

* **خصوصية 100% وتشغيل بدون إنترنت:** جميع عمليات الذكاء الاصطناعي ومعالجة الصوت تتم محلياً على جهازك دون أي خوادم خارجية أو اشتراكات.
* **معمارية Native بدون منافذ مفتوحة:** تواصل مباشر ومؤمّن بين واجهة Tauri/Rust ومحرك Python عبر أنابيب `stdio` JSON-Lines (صفر localhost ports).
* **دعم 8 نماذج AI + وضع Ensemble:** يشمل `htdemucs`، `htdemucs_ft`، `htdemucs_6s` (6 مسارات: Vocals, Drums, Bass, Guitar, Piano, Other)، `hdemucs_mmi`، وعائلة `mdx`، مع 7 أوضاع جودة جاهزة.
* **فصل صوتيات الفيديو (Cinema Video Remux):** دعم `MP4` و`MKV` و`AVI` و`MOV` مع استبدال المسار الصوتي أو مزامنته مباشرة داخل الفيديو.
* **ميكسر استوديو حي بـ 6 قنوات:** تحكم في Solo / Mute / Gain / Pan، والصدى والـ EQ والسرعة ودرجة الصوت، مع عرض موجي سريع (`Symphonia`) وتصدير إلى `WAV` (16/24/32-bit) و`FLAC` و`MP3` و`OGG` بالإضافة إلى تحويل الغناء إلى **MIDI**.
* **إدارة ذكية للدفعات والإلغاء الفوري:** طابور معالجة متوازٍ للملفات وإلغاء تعاوني فوري بين الـ Segments، مع دعم كامل للـ **16 لغة** من ضمنها **العربية (RTL)** والثيم الفاتح والداكن.

---

## 🛠️ اختصار أوامر المطورين والاختبار (Quick Commands)

```bash
# تثبيت حزم الواجهة وبناؤها
npm install
npm run typecheck
npm run build

# تشغيل التطبيق في وضع التطوير (Tauri v2 + React)
npm run tauri:dev

# اختبارات محرك الذكاء الاصطناعي والـ Packaging
python -m pytest worker/tests -v

# اختبارات نواة Rust والتكامل
cargo test --manifest-path src-tauri/Cargo.toml
```

للمزيد من التفاصيل حول إعداد بيئة التطوير وبناء المُثبّت، راجع [دليل المطورين](docs/DEVELOPER_GUIDE.md) و[دليل الاختبار](docs/TESTING_GUIDE.md).
