# Terminalda bir nechta Gmail akkauntni agy'ga ulash (Windows)

## Avval buni bilib oling

Windows'da `agy` (va Antigravity ilovasi) Google loginini **Windows Credential Manager**'da,
`gemini:antigravity` nomli **bitta** yozuvda saqlaydi. Ya'ni bir vaqtda faqat **bitta** gmail faol bo'ladi.

`agy-acc` buyrug'i shu muammoni hal qiladi:
1. Har bir gmail loginini alohida joyga saqlaydi: `usage-bar/agy/<nom>` (u ham Credential Manager'da, Windows himoyasi ostida).
2. Akkaunt almashtirilganda kerakli loginni `gemini:antigravity` yozuviga qo'yadi.
3. Tray dasturi har bir akkaunt kvotasini navbat bilan tekshiradi, keyin sizning faol akkauntingizni joyiga qaytaradi.

> ⚠️ **Saqlangan akkaunt uchun `agy` ichida `/logout` qilmang!** Bu Google tokenini bekor qilishi mumkin.
> Yangi akkaunt qo'shish uchun `agy-acc add` ishlating: u faqat kompyuterdagi loginni tozalaydi, tokenlar o'chmaydi.

---

## 0. Tayyorgarlik (bir marta)

1. `install.bat` ni ishga tushiring. U papkani PATH'ga qo'shadi va `agy-acc` buyrug'i paydo bo'ladi.
2. **Yangi** terminal oching (PowerShell, cmd yoki Windows Terminal) va tekshiring:

```powershell
agy-acc
```

Yordam matni chiqsa, hammasi joyida.
(Chiqmasa, `install.bat` dan keyin terminal qayta ochilmagan bo'ladi. Yoki to'liq yo'l bilan yozing: `C:\...\usage-bar-windows\agy-acc.bat`.)

## 1. Birinchi gmail

**Agar `agy` ga allaqachon kirgan bo'lsangiz**, hozirgi loginni nom berib saqlang:

```powershell
agy-acc save gmail1
```

**Agar hali kirmagan bo'lsangiz:**

```powershell
agy-acc add gmail1
```

`agy` ochiladi, keyin:
1. Brauzerda **1-gmail** bilan kiring.
2. `agy` ga qaytib `/quit` yozing.

Shundan keyin `Saqlandi: gmail1 (siz@gmail.com) — hozir faol` chiqadi.

## 2. Ikkinchi va uchinchi gmail

```powershell
agy-acc add gmail2
```

`agy` ochiladi: brauzerda **2-gmail** bilan kiring (avvalgi gmail emas!), keyin `/quit`.

```powershell
agy-acc add gmail3
```

Xuddi shunday, **3-gmail** bilan kiring va `/quit`.

> Brauzer avtomatik ravishda eski gmail bilan kirib yuborsa, Google sahifasida **"Use another account"** (boshqa akkaunt) ni tanlang.
> Yoki havolani inkognito oynada oching.
> Bir gmail ikki marta qo'shilsa, dastur buni aniqlaydi va saqlamaydi.

## 3. Tekshirish

```powershell
agy-acc list
```

```
   gmail1       ali@gmail.com
   gmail2       ali.work@gmail.com
 * gmail3       ali.ext@gmail.com
```

`*` belgisi `agy` hozir qaysi akkauntdan foydalanayotganini bildiradi.

## 4. Kundalik ishlatish: akkaunt almashtirish

Avval ochiq `agy` ni yoping (`/quit`). Antigravity ilovasi ochiq bo'lsa, uni ham yoping. Keyin:

```powershell
agy-acc use gmail2
agy
```

Endi `agy` **gmail2** limitidan foydalanadi. Bir akkauntning limiti tugasa, `/quit` → `agy-acc use gmail3` → `agy`.

Qaysi akkauntda limit ko'proq qolganini tray ikonkasidagi oynadan ko'rasiz: unda 3 ala akkaunt kvotasi bor.

## 5. Boshqa buyruqlar

| Buyruq | Nima qiladi |
|---|---|
| `agy1` (akkaunt nomi) yoki `agy-acc open agy1` | Shu akkauntga o'tib, `agy` ni ochadi |
| `agy-acc quota` | Har bir akkaunt limiti (% ishlatilgan) |
| `agy-acc run "vazifa"` | Vazifani agy'ga beradi: limiti ko'p qolgan gmail o'zi tanlanadi, limit tugasa keyingisiga o'tadi. agy joriy papkada fayllarni o'zgartira oladi; `--read-only` — faqat javob |
| `agy-acc current` | Hozirgi faol akkaunt nomi |
| `agy-acc login gmail2` | gmail2 ga qayta kirish (token eskirgan / "kirish kerak" chiqqan bo'lsa) |
| `agy-acc rename agy gmail1` | Akkaunt nomini o'zgartirish (masalan tray o'zi `agy` deb saqlagan bo'lsa) |
| `agy-acc email gmail2 siz@gmail.com` | Ro'yxatda/oynada gmail ko'rinmasa, uni qo'lda yozib qo'yish |
| `agy-acc doctor` | Muammo bo'lsa: loginlar tuzilishi (tokenlarsiz) |
| `agy-acc remove gmail3` | gmail3 ni ro'yxatdan o'chirish |
| `agy-acc use gmail1 --force` | `agy` ochiq bo'lsa ham almashtirish (tavsiya etilmaydi) |

Shularni tray dasturi ichidan ham qilsa bo'ladi: **`•••` → agy akkauntlar**. U yerda Kirish, yangi akkaunt qo'shish va terminal uchun akkaunt tanlash bor.

## Nimaga e'tibor berish kerak

- **`agy` ochiq paytda almashtirmang.** Ishlab turgan `agy` taxminan har soatda tokenini yangilaydi va o'z akkauntini qayta yozib qo'yadi, natijada almashtirish bekor bo'ladi. `agy-acc use` buni o'zi tekshiradi.
- **Antigravity ilovasi ham shu loginni ishlatadi.** `agy-acc use gmail2` dan keyin ilova ham gmail2 da bo'ladi.
- **Tray dasturi va ochiq `agy`.** `agy` ochiq paytda tray dasturi faqat faol akkauntni yangilaydi. Qolganlari `agy` yopilgach yangilanadi.
- **Qo'lda boshqa gmail bilan kirsangiz,** `agy-acc` uni hech qaysi saqlangan akkaunt ustiga yozmaydi. `list` buyrug'i "saqlanmagan akkaunt bor" deydi; uni `agy-acc save gmail4` bilan saqlang.
- **Saqlangan loginlarni ko'rish:** *Boshqaruv paneli → Credential Manager → Windows Credentials* → `usage-bar/agy/...`. U yerdan o'chirsa ham bo'ladi.
- **Kelajakda `agy` boshqa joyda saqlay boshlasa** (masalan, yangi versiyada): `config.json` ga `"agyCredential": "<yangi nom>"` yozing.

## Claude Code'dan agy'ni ishlatish (skill)

`install.bat` (yoki `python usage_bar.py --install-skill`) Claude Code uchun **`agy`** skill'ini o'rnatadi:
`C:\Users\<siz>\.claude\skills\agy\SKILL.md`. Claude Code'ni qayta ochgach, unga shunday deyish mumkin:

- "login sahifasini qil, oddiy qismlarini agy'ga ber — Claude limitini tejaylik"
- "agy bilan shu funksiyaga testlar yozdir"
- "agy bilan shu funksiyani review qildir"
- "agy akkauntlarimda qancha limit qoldi?"
- yoki shunchaki `/agy ...`

agy Claude'ning **subagenti** bo'lib ishlaydi: qaysi qismni agy qilishini Claude o'zi hal qiladi va uni `agy-acc run` orqali
limiti eng ko'p qolgan gmail'ga beradi. agy loyiha papkasida fayllarni o'zi yaratadi, tahrirlaydi va o'chiradi
(`--dangerously-skip-permissions` bilan ishga tushadi). Keyin Claude `git diff` ni o'qiydi, kerak bo'lsa tuzatadi, testlarni ishga tushiradi
va qaysi qismni agy qilganini sizga aytadi. Faqat javob kerak bo'lsa (review, savol), Claude agy'ga fayllarga tegmaslikni aytadi yoki `--read-only` ishlatadi.

> agy'ga hamma ruxsat berilgani uchun, muhim loyihalarda ishni boshlashdan oldin o'zgarishlaringizni commit qilib qo'ying —
> shunda agy nima qilgani `git diff` da aniq ko'rinadi va kerak bo'lsa osongina qaytariladi.
Kirish (`add`, `login`) kabi brauzer kerak bo'lgan ishlarni Claude o'zi qilmaydi — ularni siz terminalda bajarasiz.
