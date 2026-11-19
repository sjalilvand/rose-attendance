"""۳۱ کلینیک مرکزی «رز دکتر» در مراکز استان‌ها — جدول کارفرما (۱۴۰۵/۰۸/۰۹).

منبع داده: فهرست شعب کلینیک در استان‌ها که کارفرما برای افزودن به سامانه فرستاد
(نام، استان/شهر، نشانی، مختصات). شعاع مجاز تردد = ۳۰۰ متر طبق پیش‌فرض کلینیک
مصوب ۲٫۱ (GEOFENCE_RADIUS_DEFAULT_CLINIC). وضعیت «منتشرشده» یعنی شعبه فعال.

ماژول مستقل از مدل‌ها است تا هم migration تاریخی و هم دستور مدیریتی بتوانند
مدل خودشان را بدهند؛ seed ایده‌مپوتنت است: با کد موجود یا نام تکراری دوباره
نمی‌سازد و فقط گزارش می‌دهد.
"""

CLINIC_RADIUS_M = 300  # مصوب ۲٫۱ — شعاع پیش‌فرض کلینیک (شهری ۱۵۰ / کلینیک ۳۰۰)

CLINICS: list[dict] = [
    {
        "code": "RD-ARAK",
        "region_code": "PRV-ARAK",
        "province": "مرکزی",
        "city": "اراک",
        "name": "کلینیک مرکزی رز دکتر — اراک",
        "address": "انتهای خیابان قائم مقام ،میدان امام حسین (ع) ابتدای شهرک الغدیر بعد از بازارچه ،کلینیک رز جنب پارک ولایت ساختمان کانون فرهنگی",
        "geo_latitude": 34.0917,
        "geo_longitude": 49.6892,
    },
    {
        "code": "RD-ARDABIL",
        "region_code": "PRV-ARDABIL",
        "province": "اردبیل",
        "city": "اردبیل",
        "name": "کلینیک مرکزی رز دکتر — اردبیل",
        "address": "خیابان شهید مطهری- کمیته امداد امام خمینی (ره) اداره ۲",
        "geo_latitude": 38.2498,
        "geo_longitude": 48.2933,
    },
    {
        "code": "RD-URMIA",
        "region_code": "PRV-URMIA",
        "province": "آذربایجان غربی",
        "city": "ارومیه",
        "name": "کلینیک مرکزی رز دکتر — ارومیه",
        "address": "ارومیه، خیابان عمار، پشت بیمارستان امام خمینی، کوچه 9",
        "geo_latitude": 37.5527,
        "geo_longitude": 45.0760,
    },
    {
        "code": "RD-ISFAHAN",
        "region_code": "PRV-ISFAHAN",
        "province": "اصفهان",
        "city": "اصفهان",
        "name": "کلینیک مرکزی رز دکتر — اصفهان",
        "address": "بخش مرکزی شهر اصفهان محله عسگریه کوچه شهید فرهاد امام جمعه۴۹ کوچه هوشمند۴۱ پلاک ۹ طبقه دوم",
        "geo_latitude": 32.6546,
        "geo_longitude": 51.6680,
    },
    {
        "code": "RD-AHVAZ",
        "region_code": "PRV-AHVAZ",
        "province": "خوزستان",
        "city": "اهواز",
        "name": "کلینیک مرکزی رز دکتر — اهواز",
        "address": "اهواز خیابان سلمان فارسی (نادری) .مجتمع اداری تجاری کارون طبقه سوم",
        "geo_latitude": 31.3183,
        "geo_longitude": 48.6706,
    },
    {
        "code": "RD-ILAM",
        "region_code": "PRV-ILAM",
        "province": "ایلام",
        "city": "ایلام",
        "name": "کلینیک مرکزی رز دکتر — ایلام",
        "address": "ایلام میدان دفاع مقدس . جنب باشگاه نشاط ، مجتمع کانون ولایت",
        "geo_latitude": 33.6374,
        "geo_longitude": 46.4227,
    },
    {
        "code": "RD-BOJNURD",
        "region_code": "PRV-BOJNURD",
        "province": "خراسان شمالی",
        "city": "بجنورد",
        "name": "کلینیک مرکزی رز دکتر — بجنورد",
        "address": "بجنورد خیابان نواب صفوی ، نواب صفوی ۸ ( محجوب ) جنب سالن ورزشی الغدیر پلاک ۲۲",
        "geo_latitude": 37.4747,
        "geo_longitude": 57.3290,
    },
    {
        "code": "RD-BANDARABBAS",
        "region_code": "PRV-BANDARABBAS",
        "province": "هرمزگان",
        "city": "بندرعباس",
        "name": "کلینیک مرکزی رز دکتر — بندرعباس",
        "address": "شهرک نبوت خیابان هجرت زعد از کوچه هجرت ۴مجتمع فرهنگی ورزشی فاطمیه",
        "geo_latitude": 27.1832,
        "geo_longitude": 56.2666,
    },
    {
        "code": "RD-BUSHEHR",
        "region_code": "PRV-BUSHEHR",
        "province": "بوشهر",
        "city": "بوشهر",
        "name": "کلینیک مرکزی رز دکتر — بوشهر",
        "address": "بوشهر-خیابان قدس خیابان رئیسعلی دلواری -اداره کل کمیته امداد استان بوشهر",
        "geo_latitude": 28.9234,
        "geo_longitude": 50.8203,
    },
    {
        "code": "RD-BIRJAND",
        "region_code": "PRV-BIRJAND",
        "province": "خراسان جنوبی",
        "city": "بیرجند",
        "name": "کلینیک مرکزی رز دکتر — بیرجند",
        "address": "شهرستان بیرجند_ کلینیک راه زندگی خیایان شهید رجایی، بین رجایی ۱۱ و ۱۳ کتابخانه ولایت",
        "geo_latitude": 32.8663,
        "geo_longitude": 59.2211,
    },
    {
        "code": "RD-TABRIZ",
        "region_code": "PRV-TABRIZ",
        "province": "آذربایجان شرقی",
        "city": "تبریز",
        "name": "کلینیک مرکزی رز دکتر — تبریز",
        "address": "تبریز خیابان فلسطین (ملل متحد)، پایین تر از درمانگاه دکتر قریب",
        "geo_latitude": 38.0754,
        "geo_longitude": 46.2919,
    },
    {
        "code": "RD-TEHRAN",
        "region_code": "PRV-TEHRAN",
        "province": "تهران",
        "city": "تهران",
        "name": "کلینیک مرکزی رز دکتر — تهران",
        "address": "منطقه ۱۷، میدان بهاران، خیابان سجاد جنوبی، کوجه علی درودیان، نبش کوچه خدایار حسنی پلاک ۷۸، واحد ۵",
        "geo_latitude": 35.6892,
        "geo_longitude": 51.3890,
    },
    {
        "code": "RD-KHORRAMABAD",
        "region_code": "PRV-KHORRAMABAD",
        "province": "لرستان",
        "city": "خرم‌آباد",
        "name": "کلینیک مرکزی رز دکتر — خرم‌آباد",
        "address": "خرم آباد ، انتهای خیرآباد ، کوچه تعاون ۷ ، روبروی پارک شاپوری",
        "geo_latitude": 33.4878,
        "geo_longitude": 48.3558,
    },
    {
        "code": "RD-RASHT",
        "region_code": "PRV-RASHT",
        "province": "گیلان",
        "city": "رشت",
        "name": "کلینیک مرکزی رز دکتر — رشت",
        "address": "رشت، سبزه میدان، ابتدای پیرسرا، جنب پلیس امنیت اقتصادی، بن‌بست نیکو",
        "geo_latitude": 37.2808,
        "geo_longitude": 49.5832,
    },
    {
        "code": "RD-ZAHEDAN",
        "region_code": "PRV-ZAHEDAN",
        "province": "سیستان و بلوچستان",
        "city": "زاهدان",
        "name": "کلینیک مرکزی رز دکتر — زاهدان",
        "address": "دانشگاه 49(قلنبر یک)،داخل میلان سمت راست اولین کوچه کنار ساختمان فنی و حرفه آیی ، جنب کانون فرهنگی امام علی کمیته امداد امام خمینی ره مرکز مشاوره راه زندگی",
        "geo_latitude": 29.4963,
        "geo_longitude": 60.8629,
    },
    {
        "code": "RD-ZANJAN",
        "region_code": "PRV-ZANJAN",
        "province": "زنجان",
        "city": "زنجان",
        "name": "کلینیک مرکزی رز دکتر — زنجان",
        "address": "زنجان-اعتماديه-معبر ماقبل آخر؛خیابان دکترامیر اعلم غضنفريان،معبرآخر؛خیابان شهید سید کمال میرصدری(۱۱وسط)،پلاک ۴۲",
        "geo_latitude": 36.6736,
        "geo_longitude": 48.4787,
    },
    {
        "code": "RD-SARI",
        "region_code": "PRV-SARI",
        "province": "مازندران",
        "city": "ساری",
        "name": "کلینیک مرکزی رز دکتر — ساری",
        "address": "سارى خيابان معلم ،انتهاى معلم كوچه مديريت ،سمت راست درب دوم",
        "geo_latitude": 36.5633,
        "geo_longitude": 53.0601,
    },
    {
        "code": "RD-SEMNAAN",
        "region_code": "PRV-SEMNAAN",
        "province": "سمنان",
        "city": "سمنان",
        "name": "کلینیک مرکزی رز دکتر — سمنان",
        "address": "میدان دریادار همتی بلوار ۱۷ شهریور جنب بانک ملت زیر زمین کمیته امداد",
        "geo_latitude": 35.5729,
        "geo_longitude": 53.3970,
    },
    {
        "code": "RD-SANANDAJ",
        "region_code": "PRV-SANANDAJ",
        "province": "کردستان",
        "city": "سنندج",
        "name": "کلینیک مرکزی رز دکتر — سنندج",
        "address": "سنندج بلوار کردستان بالاتر از پل مردوخت جنب پست بانک کمیته امداد منطقه دو طبقه ۳",
        "geo_latitude": 35.3219,
        "geo_longitude": 46.9862,
    },
    {
        "code": "RD-SHAHREKORD",
        "region_code": "PRV-SHAHREKORD",
        "province": "چهارمحال و بختیاری",
        "city": "شهرکرد",
        "name": "کلینیک مرکزی رز دکتر — شهرکرد",
        "address": "خیابان مولوی روبروی دبیرستان سید جمال الدین",
        "geo_latitude": 32.3256,
        "geo_longitude": 50.8644,
    },
    {
        "code": "RD-SHIRAZ",
        "region_code": "PRV-SHIRAZ",
        "province": "فارس",
        "city": "شیراز",
        "name": "کلینیک مرکزی رز دکتر — شیراز",
        "address": "شیراز بلوار رازی روبروی کوچه ۷ طبقه فوقانی مدرسه دخترانه گل واژه",
        "geo_latitude": 29.5918,
        "geo_longitude": 52.5837,
    },
    {
        "code": "RD-QAZVIN",
        "region_code": "PRV-QAZVIN",
        "province": "قزوین",
        "city": "قزوین",
        "name": "کلینیک مرکزی رز دکتر — قزوین",
        "address": "چهارراه راهنمایی رانندگی قدیم کمی جلوتر از صبحانه سرای نمونه به سمت نظام وفا، روبه روی تیپاکس",
        "geo_latitude": 36.2797,
        "geo_longitude": 50.0049,
    },
    {
        "code": "RD-QOM",
        "region_code": "PRV-QOM",
        "province": "قم",
        "city": "قم",
        "name": "کلینیک مرکزی رز دکتر — قم",
        "address": "قم،بلوار ۱۵ خرداد،بین کوچه ۲۵ و ۲۷،طبقه همکف کانون فرهنگی امداد ولایت،کلینیک راه زندگی",
        "geo_latitude": 34.6396,
        "geo_longitude": 50.8759,
    },
    {
        "code": "RD-MASHHAD",
        "region_code": "PRV-MASHHAD",
        "province": "خراسان رضوی",
        "city": "مشهد",
        "name": "کلینیک مرکزی رز دکتر — مشهد",
        "address": "چهارراه بیسیم جهاد سازندگی ۵",
        "geo_latitude": 36.2605,
        "geo_longitude": 59.6168,
    },
    {
        "code": "RD-HAMADAN",
        "region_code": "PRV-HAMADAN",
        "province": "همدان",
        "city": "همدان",
        "name": "کلینیک مرکزی رز دکتر — همدان",
        "address": "میدان امام ابتدای خیابان باباطاهر روبروی پاساژ استقلال طبقه اول نبش درمانگاه امام خمینی بعضی روزها صبح بعضی اوقات عصر",
        "geo_latitude": 34.7992,
        "geo_longitude": 48.5146,
    },
    {
        "code": "RD-KARAJ",
        "region_code": "PRV-KARAJ",
        "province": "البرز",
        "city": "کرج",
        "name": "کلینیک مرکزی رز دکتر — کرج",
        "address": "کرج،۴۵ متری گلشهر،خیابان شهید قلندری،جنب پارک بهار،مرکز خدمات مشاوره و روانشناختی راه زندگی",
        "geo_latitude": 35.8400,
        "geo_longitude": 50.9391,
    },
    {
        "code": "RD-KERMAN",
        "region_code": "PRV-KERMAN",
        "province": "کرمان",
        "city": "کرمان",
        "name": "کلینیک مرکزی رز دکتر — کرمان",
        "address": "کرمان میدان عاشورا بلوار سردار سلیمانی روبروی خیابان ورزش کمیته امداد منطقه یک",
        "geo_latitude": 30.2839,
        "geo_longitude": 57.0834,
    },
    {
        "code": "RD-KERMANSHAH",
        "region_code": "PRV-KERMANSHAH",
        "province": "کرمانشاه",
        "city": "کرمانشاه",
        "name": "کلینیک مرکزی رز دکتر — کرمانشاه",
        "address": "کلینیک مرکزی: کرمانشاه ، شهرک دانش خیابان مهر ، خیابان شهید تورج بزرگیان ، جنب کمیته امداد منطقه ۴",
        "geo_latitude": 34.3277,
        "geo_longitude": 47.0778,
    },
    {
        "code": "RD-GORGAN",
        "region_code": "PRV-GORGAN",
        "province": "گلستان",
        "city": "گرگان",
        "name": "کلینیک مرکزی رز دکتر — گرگان",
        "address": "گرگان، خیابان ولیعصر، عدالت ۸، جنب کمیته امداد امام خمینی (ره)",
        "geo_latitude": 36.8456,
        "geo_longitude": 54.4393,
    },
    {
        "code": "RD-YASUJ",
        "region_code": "PRV-YASUJ",
        "province": "کهگیلویه و بویراحمد",
        "city": "یاسوج",
        "name": "کلینیک مرکزی رز دکتر — یاسوج",
        "address": "یاسوج شصت متری -کوچه جنب اداره مالیات-خیابان مالیات پلاک ۱۲ کلینیک راه زندگی",
        "geo_latitude": 30.6682,
        "geo_longitude": 51.5878,
    },
    {
        "code": "RD-YAZD",
        "region_code": "PRV-YAZD",
        "province": "یزد",
        "city": "یزد",
        "name": "کلینیک مرکزی رز دکتر — یزد",
        "address": "کلینیک مرکزی: خیابان کاشانی خیابان چمران کوچه اویسی ۲۶ چمران نبش کوچه ۲۴ سلمان فارسی",
        "geo_latitude": 31.8974,
        "geo_longitude": 54.3569,
    },
]

CLINIC_BRANCH_CODES = sorted(c["code"] for c in CLINICS)
CLINIC_REGION_CODES = sorted({c["region_code"] for c in CLINICS})


def seed_clinic_branches(region_model, branch_model, dry_run: bool = False) -> dict:
    """ثبت ایده‌مپوتنت کلینیک‌ها؛ مدل‌ها را صاحب صدا می‌دهد (تاریخی یا واقعی).

    برمی‌گرداند: regions_created / branches_created / skipped (کد + دلیل).
    """
    created_regions: list[str] = []
    created_branches: list[str] = []
    skipped: list[tuple[str, str]] = []
    region_cache: dict[str, object] = {}
    existing_names = set(branch_model.objects.values_list("name", flat=True))

    for c in CLINICS:
        if branch_model.objects.filter(code=c["code"]).exists():
            skipped.append((c["code"], "کد شعبه از قبل موجود است"))
            continue
        if c["name"] in existing_names:
            skipped.append((c["code"], "شعبه‌ای با همین نام موجود است"))
            continue
        region = region_cache.get(c["province"])
        if region is None:
            # نام منطقه ممکن است با مناطق دستی کارفرما یکی باشد — همان استفاده می‌شود
            region = region_model.objects.filter(name=c["province"]).first()
            if region is None:
                region = region_model.objects.create(
                    code=c["region_code"],
                    name=c["province"],
                    is_active=True,
                )
                created_regions.append(region.code)
            region_cache[c["province"]] = region
        if dry_run:
            created_branches.append(c["code"])
            continue
        branch = branch_model.objects.create(
            code=c["code"],
            name=c["name"],
            region=region,
            province=c["province"],
            city=c["city"],
            address=c["address"],
            geo_latitude=c["geo_latitude"],
            geo_longitude=c["geo_longitude"],
            geo_radius_m=CLINIC_RADIUS_M,
            is_active=True,
        )
        created_branches.append(branch.code)
        existing_names.add(c["name"])

    return {
        "dry_run": dry_run,
        "regions_created": created_regions,
        "branches_created": created_branches,
        "skipped": skipped,
    }
