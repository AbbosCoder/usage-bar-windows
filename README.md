# Usage — Windows versiyasi

**Claude Code** va **agy** (Google Antigravity CLI / Gemini) akkauntlaringizning **5 soatlik** va **haftalik** limitlarini bitta joyda ko'rsatadigan kichik Windows tray dasturi.
Asl macOS dasturi ([usage-bar](https://github.com/thexayotbe/usage-bar)) ning Windows 11 uchun Python porti.

![popover](docs/popover.png)

- **Tray ikonka** (soat yonida): halqa + raqam = 5 soatlik limitning necha foizi ishlatilgan.
  Rang: yashil < 70 · sariq 70–85 · to'q sariq 85–95 · qizil ≥ 95. Kichik to'q sariq nuqta = qaysidir akkauntga kirish kerak yoki ma'lumot eskirgan.
  Claude akkaunt bo'lmasa, ikonka agy akkauntlarining eng yuqori 5 soatlik foizini ko'rsatadi.
- **Chap tugma** → oyna: har bir Claude akkaunt kartasi, har bir agy akkaunt qatori (bosilsa ochiladi: Gemini va Claude & GPT, 5 soat + hafta).
- **O'ng tugma** → menyu (yangilash, akkaunt qo'shish, sozlamalar, chiqish).

## Talablar

- Windows 10/11
- Python 3.10+ ([python.org](https://www.python.org/downloads/), o'rnatishda **"Add python.exe to PATH"** ni belgilang)
- `agy` o'rnatilgan va hech bo'lmasa bitta akkaunt bilan kirilgan (va/yoki Claude Code)

## O'rnatish

1. Papkani istalgan joyga qo'ying, masalan `C:\Users\<siz>\usage-bar-windows`.
2. **`install.bat`** ni ikki marta bosing — `pystray` va `pillow` o'rnatiladi va dastur ishga tushadi.
3. Soat yonida halqa ikonka paydo bo'ladi (ko'rinmasa — `^` strelka ichida; uni sudrab tashqariga chiqaring).
4. Windows bilan birga ochilishi uchun: oynada **`•••` → "Windows bilan birga ishga tushirish"**.

Keyingi safar ishga tushirish: **`start.bat`**. `install.bat` papkani PATH'ga ham qo'shadi, shuning uchun terminalda `agy-acc` buyrug'i ishlaydi.

## Bir nechta Gmail (agy) akkauntni ulash

Windows'da `agy` bitta umumiy loginni ishlatadi (Credential Manager → `gemini:antigravity`). Shuning uchun har bir gmail
loginini saqlab qo'yib, kerak bo'lganda almashtiradigan **`agy-acc`** buyrug'i bor. Qisqasi (yangi terminalda):

```powershell
agy-acc save gmail1     # agy'ga allaqachon kirgan bo'lsangiz (aks holda: agy-acc add gmail1)
agy-acc add gmail2      # agy ochiladi → 2-gmail bilan kiring → /quit
agy-acc add gmail3      # agy ochiladi → 3-gmail bilan kiring → /quit
agy-acc list            # * = hozir faol
agy-acc use gmail2      # terminaldagi agy endi gmail2 limitidan foydalanadi
```

Tray dasturi 3 ala akkauntning limitini ko'rsatadi. **To'liq qo'llanma: [AGY_AKKAUNTLAR.md](AGY_AKKAUNTLAR.md).**

## Sozlamalar

Fayl: `C:\Users\<siz>\.config\usage-bar\config.json` (birinchi ishga tushishda avtomatik yaratiladi). Tahrirlash: **`•••` → Sozlamalarni ochish…**, keyin **Sozlamalarni qayta yuklash**.

| Kalit | Ma'nosi |
|---|---|
| `refreshMinutes` | Har necha daqiqada yangilash (standart 5). Claude API 5 daqiqadan tez so'ralmaydi. |
| `menuBarAccount` | Tray ikonkada ko'rsatiladigan Claude akkaunt nomi (standart: birinchisi). |
| `trayIcon` | `"number"` (halqa + raqam) yoki `"rings"` (ikki halqa: tashqi 5 soat, ichki hafta). |
| `agyPath` | `agy` topilmasa, uning to'liq yo'li, masalan `"C:/Users/siz/AppData/Roaming/npm/agy.cmd"`. |
| `claude[]` | `{ "name", "label"?, "configDir" }` — Claude Code config papkasi (`~/.claude`). `label: "reserve"` kartani xiraroq qiladi. |
| `agy[]` | `{ "name", "enabled" }` — `agy-acc` o'zi qo'shadi. (`"home"` / `"env"` faqat Windows bo'lmagan tizimlar uchun.) |
| `agyCredential` | agy loginining Credential Manager'dagi nomi (standart `gemini:antigravity`). |
| `quotaFile` | Ixtiyoriy: tarmoq o'rniga shu JSON fayldan o'qish (asl README'dagi format). |

**Claude Code** (bo'lsa): Windows'da token `C:\Users\<siz>\.claude\.credentials.json` da turadi — dastur shuni o'qiydi.
Bir nechta Claude akkaunt: `CLAUDE_CONFIG_DIR=C:\Users\siz\.claude-ish` bilan kiring va `claude` ro'yxatiga qo'shing.

## Muammolar

| Belgi | Yechim |
|---|---|
| Ikonka chiqmadi | `check.bat` ni ishga tushiring — har bir akkaunt natijasi yoki xatosi chiqadi. `python usage_bar.py` (w siz) xatoni ko'rsatadi. |
| `agy topilmadi` | `where agy` buyrug'i nima chiqarsa, o'shani `agyPath` ga yozing. |
| agy qatori *kirish kerak* | **Kirish** (yoki `agy-acc login NOM`) → Google bilan kiring → `/quit`. |
| *agy / Antigravity ochiq* | Ochiq turgan agy'ga tegilmasligi uchun boshqa akkauntlar u yopilgach yangilanadi. |
| 3 ala akkaunt bir xil raqam | `agy-acc list` — har biriga turli email yozilganini tekshiring. |
| `agy /quota javob bermadi` | `agy -p "/quota"` ni terminalda qo'lda tekshiring. |
| "Claude login topilmadi" / "token eskirgan" | O'sha akkauntda Claude Code'ni bir marta oching (token yangilanadi). |
| 429 | Anthropic cheklovi: dastur o'zi kutadi va oxirgi raqamlarni ko'rsatadi. |

## Maxfiylik

- Claude: `GET https://api.anthropic.com/api/oauth/usage` — faqat o'zingizning tokeningiz bilan. Token hech qayerga yozilmaydi.
- agy: faqat `agy -p "/quota"` ishga tushiriladi; Google bilan agy'ning o'zi gaplashadi.
- Kesh: `%LOCALAPPDATA%\usage-bar\cache.json` (faqat foizlar va vaqtlar).

## O'chirish

`•••` → "Windows bilan birga…" belgisini olib tashlang → **Chiqish**. Keyin papkani va `C:\Users\<siz>\.config\usage-bar` ni o'chiring.
