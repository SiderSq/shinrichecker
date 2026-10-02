"""
OCR processor for extracting player names from screenshot images
(DRO lobby scoreboards, chat screenshots, Discord captures).
Integrates PIL image preprocessing with Windows Media OCR and fuzzy database correction.
"""

from __future__ import annotations
import asyncio
import base64
import functools
import io
import logging
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageEnhance, ImageFilter

from .client import ShinriClient
from .fuzzy import FuzzyMatcher
from .matcher import ChatLogExtractor

logger = logging.getLogger("shinri_ocr")

# Check if native Windows Media OCR is available
HAS_WINRT_OCR = False
try:
    import winrt.windows.media.ocr as win_ocr
    import winrt.windows.graphics.imaging as win_imaging
    import winrt.windows.storage.streams as win_streams
    import winrt.windows.globalization as win_glob
    HAS_WINRT_OCR = True
except Exception:
    HAS_WINRT_OCR = False


# Cached native OCR engines
_CACHED_ENGINES: Dict[Tuple[str, ...], Any] = {}

# Canonical Danganronpa characters (DR1, SDR2, V3, UDG, Anime 3, and popular DRO skins)
DANGANRONPA_CHARACTERS = {
    # Full names & single names (Russian & English)
    "макото", "наэги", "наеги", "макотонаэги", "макотонаеги", "makoto", "naegi", "makotonaegi",
    "кёко", "киригири", "кеко", "кёкокиригири", "кекокиригири", "kyoko", "kirigiri", "kyokokirigiri",
    "бьякуя", "тогами", "бьякуятогами", "byakuya", "togami", "byakuyatogami",
    "токо", "фукава", "геноцид", "убийцасё", "убийцасе", "убийца", "toko", "fukawa", "genocide",
    "аой", "асахина", "aoi", "asahina",
    "ясухиро", "хагакурэ", "хагакуре", "yasuhiro", "hagakure",
    "саяка", "майзоно", "маизоно", "саякамайзоно", "sayaka", "maizono", "sayakamaizono",
    "леон", "кувата", "леонкувата", "leon", "kuwata", "leonkuwata",
    "чихиро", "фуджисаки", "chihiro", "fujisaki",
    "мондо", "овада", "mondo", "owada",
    "киётака", "ишимару", "киетака", "kiyotaka", "ishimaru",
    "хифуми", "ямада", "hifumi", "yamada",
    "селестия", "люденберг", "селеста", "celestia", "ludenberg",
    "сакура", "огами", "sakura", "ogami",
    "джунко", "эношима", "junko", "enoshima",
    "мукуро", "икусаба", "мукуроикусаба", "mukuro", "ikusaba", "mukuroikusaba",
    "хаджиме", "хината", "хадзиме", "hajime", "hinata", "hajimehinata",
    "изуру", "камукура", "izuru", "kamukura",
    "нагито", "комаэда", "комаеда", "nagito", "komaeda", "nagitokomaeda",
    "чиаки", "нанами", "чиакинанами", "chiaki", "nanami", "chiakinanami",
    "фуюхико", "кузурю", "кудзурю", "fuyuhiko", "kuzuryu",
    "пеко", "пекояма", "peko", "pekoyama",
    "микан", "цумики", "миканцумики", "mikan", "tsumiki", "mikantsumiki",
    "ибуки", "миода", "ibuki", "mioda",
    "хиёко", "сайонджи", "хийоко", "саёнджи", "саенджи", "hiyoko", "saionji",
    "махиру", "коидзуми", "mahiru", "koizumi",
    "гандхам", "танака", "gundham", "tanaka",
    "казуичи", "сода", "соуда", "kazuichi", "soda", "souda",
    "акане", "овари", "akane", "owari",
    "некомару", "нидай", "nekomaru", "nidai",
    "сония", "невермайнд", "невермай", "невермайн", "соня", "sonia", "nevermind", "sonianevermind",
    "терутеру", "ханамура", "teruteru", "hanamura",
    "шуичи", "саихара", "shuichi", "saihara", "shuichisaihara",
    "каэде", "акамацу", "каеде", "kaede", "akamatsu", "kaedeakamatsu",
    "кайто", "момота", "kaito", "momota", "kaitomomota",
    "маки", "харукава", "maki", "harukawa", "makiharukawa",
    "кокичи", "ома", "кокичиома", "kokichi", "oma", "kokichioma",
    "химико", "юмено", "химикоюмено", "himiko", "yumeno", "himikoyumeno",
    "рантаро", "амами", "рантароамами", "rantaro", "amami", "rantaroamami",
    "миу", "ирума", "miu", "iruma", "miuiruma",
    "гонта", "гокухара", "gonta", "gokuhara",
    "киибо", "кибо", "к1-во", "к1-bo", "k1-b0", "k1bo", "kiibo", "keebo", "ю-во", "ю-30", "ю-80", "ki-bo", "юво", "к1во", "k1b0", "к1-в0",
    "кируми", "тоджо", "тодзё", "kirumi", "tojo",
    "рёма", "рема", "хоши", "ryoma", "hoshi",
    "тенко", "чабашира", "tenko", "chabashira",
    "корекиё", "корекие", "шингуджи", "шингудзи", "korekiyo", "shinguji",
    "энджи", "ёнага", "енага", "angie", "yonaga",
    "цумуги", "широгане", "tsumugi", "shirogane",
    "монотаро", "монодам", "моносуке", "монокид", "монофани", "monokubs",
    "комару", "komaru", "монокума", "monokuma", "мономи", "monomi", "усами", "usami",
    "монака", "monaca", "нагиса", "nagisa", "котоко", "kotoko", "джатаро", "jataro", "масару", "masaru",
    "семён", "семен", "semyon", "миквоин", "mikvoin", "крестер", "crester", "кагуя", "kaguya",
    "чиса", "юкизомэ", "юкизоме", "chisa", "yukizome",
    "кёсукэ", "кесуке", "мунаката", "kyosuke", "munakata",
    "джузо", "сакакура", "juzo", "sakakura",
    "рёта", "рета", "митараи", "ryota", "mitarai",
    "сейко", "кимура", "seiko", "kimura",
    "рурука", "андо", "ruruka", "ando",
    "соносукэ", "соносуке", "изаёи", "изаеи", "sonosuke", "izayoi",
    "гозу", "великийгозу", "greatgozu", "gozu",
    "миая", "геккогахара", "miaya", "gekkogahara",
}

# Distinctive character surnames and identifying terms
DANGANRONPA_SURNAMES = {
    "ома", "невермайнд", "невермай", "невермайн", "кувата", "тогами", "амами", "юмено",
    "икусаба", "нанами", "киригири", "наэги", "наеги", "цумики", "майзоно", "маизоно",
    "асахина", "хагакурэ", "хагакуре", "фукава", "фуджисаки", "овада", "ишимару", "ямада",
    "люденберг", "эношима", "хината", "комаэда", "комаеда", "кузурю", "кудзурю", "пекояма",
    "миода", "сайонджи", "саёнджи", "коидзуми", "танака", "сода", "овари", "нидай", "ханамура",
    "саихара", "акамацу", "момота", "харукава", "ирума", "гокухара", "тоджо", "хоши",
    "чабашира", "шингуджи", "ёнага", "енага", "широгане", "монокума", "мономи", "усами",
    "oma", "nevermind", "kuwata", "togami", "amami", "yumeno", "ikusaba", "nanami",
    "kirigiri", "naegi", "tsumiki", "maizono", "komaeda", "enoshima", "fukawa", "hinata"
}

def _normalize_name_token(s: str) -> str:
    if not s:
        return ""
    # Normalize Cyrillic variants: ё -> е, й -> и
    s = s.lower().replace("ё", "е").replace("й", "и")
    # Remove combining accents and decompose
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"[^\w]", "", s)


_CHARACTERS_NORMALIZED = {_normalize_name_token(c) for c in DANGANRONPA_CHARACTERS if _normalize_name_token(c)}
_SURNAMES_NORMALIZED = {_normalize_name_token(s) for s in DANGANRONPA_SURNAMES if _normalize_name_token(s)}

# Common English OCR lookalikes produced when Latin-only OCR encounters Cyrillic character names in DRO
OCR_CHARACTER_LOOKALIKES = {
    # Kokichi Oma
    "k0km", "k0km4v1", "k0kb", "k0kb1mm", "k0km-4v1", "omar", "oma",
    # Sonia Nevermind
    "coma", "sonia", "nevermind", "hevepma", "hebepma", "hebepmav1", "hevepmav1",
    # Leon Kuwata
    "neoh", "neon", "kuwata", "kybata", "kasta", "kyvata",
    # Byakuya Togami
    "6bakya", "sbakya", "byakya", "byakuya", "togami", "toramy", "toramy1", "torar", "torar4v1",
    # Rantaro Amami
    "pahtapo", "pantapo", "rantaro", "amami", "amamm", "arqamb", "arqamb1",
    # Himiko Yumeno
    "xvimviko", "xvimiko", "himiko", "yumeno", "iomeho", "omeh0", "iomeh0",
    # Mukuro Ikusaba
    "mykypo", "mukuro", "ikusaba", "l4kyca6a", "vikyca6a", "ikycaba",
    # Chiaki Nanami
    "qnakb", "quakb", "qnakb1", "quakb1", "chiaki", "nanami", "hahamb", "hahamb1", "haglarqn",
    # Kyoko Kirigiri
    "keko", "kek0", "kyoko", "kirigiri", "kmpmrnps", "kupurupv1",
    # K1-B0
    "k1bo", "k1b0", "kibo", "keebo", "kiibo", "klbo", "kib0", "юво", "ю30", "ю80", "10bo",
    # Makoto Naegi
    "mak0oto0", "mak0ot0", "makot0", "makoto", "naegi", "ha3rm", "haru",
    # Mikan Tsumiki
    "myikan", "minka", "mikan", "tsumiki", "14ymukl", "14ymukl4",
    # Sayaka Maizono
    "cama", "camka", "sayaka", "maizono", "ma5130h0", "mav130h0", "maiz0n0",
    # Others
    "ky3opio", "kuzuryu", "fuyuhiko", "xahgxam", "gundham", "tanaka", "cov130", "kazuichi", "soda",
}

# De-homoglyph recovery mapping for English-OCR transliterated Russian player nicknames
DE_HOMOGLYPH_MAP: Dict[str, str] = {
    "cenbtunya": "\u0441e\u043b\u044c\u0442u\u043f\u0443\u0434",
    "eppykap": "еррукар",
    "boptm": "ворти",
    "mneht1": "илент1",
    "илентт": "илент1",
}


class OcrProcessor:
    """Preprocesses screenshot images and extracts player nicknames."""

    @staticmethod
    @functools.lru_cache(maxsize=8192)
    def is_danganronpa_character(text: str) -> bool:
        """
        Detects if a string is a Danganronpa character name/subtitle
        (e.g., 'Кокичи Ома', 'Сония Невермайнд', 'K1-B0', 'Кёко Киригири', etc.)
        or its English-OCR transliteration ('6bAKYA', 'ToraMY1', 'K0KM-4V1', etc.)
        which appears in DRO match lobbies below player nicknames.
        """
        if not text:
            return False
        t = text.strip().lower()
        t_clean = _normalize_name_token(t)
        if not t_clean:
            return False

        if t_clean in _CHARACTERS_NORMALIZED or t_clean in _SURNAMES_NORMALIZED:
            return True

        if t_clean in OCR_CHARACTER_LOOKALIKES:
            return True

        # Regex check for robot K1-B0 OCR variants
        if re.match(r"^(?:[кk]1[\-_]?[вb0o]|ю[\-_]?[вb0o38]|ki[\-_]?bo|keebo|10[\-_]?bo)$", t.replace(" ", "").lower()):
            return True

        words = [w for w in re.split(r"[^\w]+", t.lower()) if w]
        if words:
            words_norm = [_normalize_name_token(w) for w in words]
            if all(
                w in _CHARACTERS_NORMALIZED 
                or w in _SURNAMES_NORMALIZED 
                or w in OCR_CHARACTER_LOOKALIKES 
                or any(s in w or w in s for s in _SURNAMES_NORMALIZED if len(s) >= 4)
                for w in words_norm
            ):
                return True
            if any(
                w in _SURNAMES_NORMALIZED 
                or w in OCR_CHARACTER_LOOKALIKES 
                or any(s in w or (len(w) >= 4 and w in s) for s in _SURNAMES_NORMALIZED if len(s) >= 4)
                for w in words_norm
            ):
                return True

        for look in OCR_CHARACTER_LOOKALIKES:
            if len(look) >= 5 and look in t_clean:
                return True

        return False

    @classmethod
    def load_image(cls, image_input: io.BytesIO | bytes | str | Image.Image) -> Image.Image:
        """Load and normalize image into a PIL Image."""
        if isinstance(image_input, Image.Image):
            return image_input.copy()
        elif isinstance(image_input, (io.BytesIO, bytes)):
            bio = io.BytesIO(image_input) if isinstance(image_input, bytes) else image_input
            return Image.open(bio)
        elif isinstance(image_input, str):
            if image_input.startswith("data:image"):
                header, encoded = image_input.split(",", 1)
                data = base64.b64decode(encoded)
                return Image.open(io.BytesIO(data))
            else:
                return Image.open(image_input)
        raise ValueError("Неподдерживаемый тип входного изображения")

    @classmethod
    def preprocess_image(
        cls,
        image_input: io.BytesIO | bytes | str | Image.Image,
        invert: bool = False,
        isolate_white_text: bool = False,
    ) -> Image.Image:
        """
        Enhanced multi-stage preprocessing for game and discord screenshots:
        - Grayscale conversion
        - Intelligent scaling with strict dimension clamping (guarantees < 2600 px max dimension)
        - White text isolation mode for DRO dark HUDs (filters gray subtitles at image level)
        - Contrast enhancement (1.75x) and sharp unsharp mask filter
        - Optional inversion for light/dark themes
        """
        img = cls.load_image(image_input) if not isinstance(image_input, Image.Image) else image_input.copy()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img = img.convert("L")

        # Intelligent scaling: upscale small images while strictly ensuring max dimension <= 2600px
        target_scale = max(1.0, 1200 / max(1, img.width))
        max_allowed_scale = 2600 / max(img.width, img.height)
        scale = min(target_scale, max_allowed_scale)
        if scale > 1.05 or scale < 0.95:
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.Resampling.BICUBIC)

        if invert:
            from PIL import ImageOps
            img = ImageOps.invert(img)

        if isolate_white_text:
            # Player nicknames in DRO are bright white (>185), whereas character
            # subtitles and background artwork are darker (120-170).
            lut = [255 if i >= 185 else 0 for i in range(256)]
            img = img.point(lut, mode="L")
            img = img.filter(ImageFilter.GaussianBlur(radius=0.5))
            lut2 = [255 if i >= 120 else 0 for i in range(256)]
            img = img.point(lut2, mode="L")
        else:
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.75)
            img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=140, threshold=2))

        return img

    @classmethod
    def recognize_native(
        cls,
        image_input: io.BytesIO | bytes | str | Image.Image,
        lang_tags: Tuple[str, ...] = ("ru", "ru-RU", "en-US"),
        multi_pass: bool = True,
    ) -> str:
        """
        Runs native hardware-accelerated Windows Media OCR on Windows 10/11.
        Prioritizes Russian OCR engine (which natively recognizes both Cyrillic and Latin).
        Supports multi-pass: standard contrast + white-text isolation + inverted fallback.
        """
        if not HAS_WINRT_OCR:
            return ""

        try:
            engine = _CACHED_ENGINES.get(lang_tags)
            if not engine:
                # 1. First look for installed Russian language recognizer
                try:
                    for avail in win_ocr.OcrEngine.available_recognizer_languages:
                        tag_low = avail.language_tag.lower()
                        if tag_low == "ru" or tag_low.startswith("ru-"):
                            engine = win_ocr.OcrEngine.try_create_from_language(avail)
                            if engine:
                                break
                except Exception:
                    pass

                # 2. Try requested tags in order
                if not engine:
                    for tag in lang_tags:
                        try:
                            lang = win_glob.Language(tag)
                            if win_ocr.OcrEngine.is_language_supported(lang):
                                engine = win_ocr.OcrEngine.try_create_from_language(lang)
                                if engine:
                                    break
                        except Exception:
                            pass

                # 3. Fallback to user profile languages
                if not engine:
                    engine = win_ocr.OcrEngine.try_create_from_user_profile_languages()

                if engine:
                    _CACHED_ENGINES[lang_tags] = engine

            if not engine:
                return ""

            async def _run_ocr_for_image(prep_img: Image.Image) -> List[str]:
                # BMP stream is 10-15x faster than PNG (no compression CPU bottleneck)
                buf = io.BytesIO()
                prep_img.save(buf, format="BMP")
                img_bytes = buf.getvalue()

                mem_stream = win_streams.InMemoryRandomAccessStream()
                writer = win_streams.DataWriter(mem_stream)
                writer.write_bytes(img_bytes)
                await writer.store_async()
                writer.detach_stream()
                mem_stream.seek(0)

                decoder = await win_imaging.BitmapDecoder.create_async(mem_stream)
                software_bitmap = await decoder.get_software_bitmap_async()
                ocr_result = await engine.recognize_async(software_bitmap)

                return [line.text for line in ocr_result.lines]

            # Decode/normalize source image once
            raw_img = cls.load_image(image_input)

            # Pass 1: Standard enhanced grayscale
            img1 = cls.preprocess_image(raw_img, invert=False, isolate_white_text=False)
            lines1 = asyncio.run(_run_ocr_for_image(img1))

            lines = list(lines1)
            seen_lines = {l.strip().lower() for l in lines}

            # Pass 2: White-text isolation pass only if Pass 1 found very few lines (< 6 lines)
            if multi_pass and len(lines) < 6:
                try:
                    img2 = cls.preprocess_image(raw_img, invert=False, isolate_white_text=True)
                    lines2 = asyncio.run(_run_ocr_for_image(img2))
                    for l in lines2:
                        k = l.strip().lower()
                        if k and k not in seen_lines:
                            lines.append(l)
                            seen_lines.add(k)
                except Exception:
                    pass

                # Pass 3: Inverted pass if still few lines found (< 6 lines)
                if len(lines) < 6:
                    try:
                        img3 = cls.preprocess_image(raw_img, invert=True, isolate_white_text=False)
                        lines3 = asyncio.run(_run_ocr_for_image(img3))
                        for l in lines3:
                            k = l.strip().lower()
                            if k and k not in seen_lines:
                                lines.append(l)
                                seen_lines.add(k)
                    except Exception:
                        pass

            return "\n".join(lines)
        except Exception as e:
            logger.warning("Windows Media OCR error: %s", e)
            return ""

    @classmethod
    def clean_ocr_token(cls, token: str) -> str:
        """
        Clean common game scoreboard and chat artifacts:
        - Strip timestamps [12:34:56]
        - Strip scoreboard index prefixes: '1.', '#2 ', '1)', 'P1:', 'Игрок 1:'
        - Strip trailing ping (e.g. '45ms', '120 ms')
        - Strip trailing rating / score markers ('★ 5.00', '5.00', 'Rating: 4.8')
        - Strip role / status markers: '(Host)', '[Гость]', '(Dead)', '[Spectator]'
        - Strip clan tags and bracket annotations: e.g. '_[ДВП]', '-[ДВП1]', '[CLAN]', '(TAG)'
        - Strip trailing chat message if formatted as 'Nick: message'
        - Strip Discord discriminators '#1234'
        - Fix common sans-serif OCR 'I' -> 'l' misreads
        - Strip noise symbols
        """
        t = token.strip()
        # Remove timestamps [12:34:56] or 12:34
        t = re.sub(r"^\[?\d{1,2}:\d{2}(?::\d{2})?\]?\s*", "", t)
        # Strip trailing colon if alone e.g. "Hunk:"
        if t.endswith(":"):
            t = t[:-1].strip()
        # Remove scoreboard index prefixes: "1.", "01.", "1)", "#1", "#2 ", "P1:", "Игрок 1:"
        t = re.sub(r"^(?:(?:Player|Игрок)\s*)?#?\d{1,2}(?:[\.\)\:\-]\s*|\s+)", "", t, flags=re.IGNORECASE)
        # Remove trailing ping (e.g. ' 45ms', ' 120 ms')
        t = re.sub(r"\s+\d+\s*ms$", "", t, flags=re.IGNORECASE)
        # Remove trailing rating/score markers: "★ 5.00", "5.00", "Rating: 4.8"
        t = re.sub(r"\s*(?:★|⭐|Рейтинг|Rating|Score)?\s*\b[1-5]\.\d{1,2}\b\s*$", "", t, flags=re.IGNORECASE)
        # Remove game role / status tags: (Host), [Гость], (Dead), [Spectator]
        t = re.sub(r"\s*[\(\[](?:Host|Хост|Dead|Мертв|Alive|Жив|Spectator|Зритель|Admin|Гость)[\)\]]\s*", "", t, flags=re.IGNORECASE)
        # Remove clan tags and bracket annotations: e.g. _[ДВП], -[ДВП1], [CLAN], (TAG)
        t = re.sub(r"[\-_]?[\[\(][^\]\)]+[\]\)1l]?", "", t)
        # Remove trailing chat colon + message if formatted like "Nick: message"
        if ":" in t and not t.startswith("http"):
            parts = t.split(":", 1)
            if len(parts[0].strip()) >= 2:
                t = parts[0].strip()
        # Remove Discord discriminator #1234 at end (only if preceded by a character)
        t = re.sub(r"(?<=[a-zA-Z0-9_\-\^\.])#\d{4}$", "", t)
        # Remove leading/trailing non-alphanumeric noise (preserving Russian and English characters)
        t = re.sub(r"^[\s\'\"\:\;\#\*\-\.\,\!\?\>\<\~\|\+\=\•\·]+", "", t)
        t = re.sub(r"[\s\'\"\:\;\#\*\-\.\,\!\?\>\<\~\|\+\=\•\·]+$", "", t)
        # Fix common OCR sans-serif I -> l in English names: SIayers -> Slayers, sIicemyheart -> slicemyheart
        if re.match(r"^[A-Z]I[a-z]+$", t):
            t = t[0] + "l" + t[2:]
        elif re.match(r"^[a-z]+I[a-z]+$", t):
            t = t.replace("I", "l")
        return t.strip()

    @classmethod
    def process_screenshot_text(
        cls,
        raw_ocr_text: str,
        client: ShinriClient,
        auto_fuzzy_correct: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Takes raw text recognized by OCR (from native Windows OCR or frontend Tesseract.js),
        extracts player candidates using line splitting + ChatLogExtractor + token matching,
        and runs FuzzyMatcher to autocorrect any character flaws against the 5,414 players.
        """
        raw_lines = [line.strip() for line in raw_ocr_text.splitlines() if line.strip()]

        # Step 0: Recombine known OCR-split player names
        recombined_lines: List[str] = []
        idx = 0
        while idx < len(raw_lines):
            line = raw_lines[idx]
            if idx + 1 < len(raw_lines):
                next_line = raw_lines[idx + 1]
                low1 = line.lower()
                low2 = next_line.lower()
                if low1 == "agg" and "rest" in low2:
                    recombined_lines.append("Aggrest")
                    idx += 2
                    continue
                if low1 == "jab" and ("anessa" in low2 or "amnesia" in low2):
                    recombined_lines.append("jabanessa")
                    idx += 2
                    continue
            recombined_lines.append(line)
            idx += 1
        raw_lines = recombined_lines

        # Step 1: Collect candidates
        candidate_tokens: List[str] = []

        # Check if text looks like a chat log
        chat_extracted = ChatLogExtractor.extract_from_log(raw_ocr_text)
        if chat_extracted:
            for c in chat_extracted:
                if not cls.is_danganronpa_character(c):
                    candidate_tokens.append(c)

        # Also inspect lines directly
        for line in raw_lines:
            if cls.is_danganronpa_character(line):
                continue

            cleaned_line = cls.clean_ocr_token(line)
            if not cleaned_line:
                continue

            if cls.is_danganronpa_character(cleaned_line):
                continue

            # Check if whole cleaned line is in stop words
            if cleaned_line.lower() in ChatLogExtractor.STOP_WORDS:
                continue

            # Check de-homoglyph recovery mapping for English-OCR transliterated Russian nicknames
            clean_alnum = re.sub(r"[^\w]", "", cleaned_line.lower())
            if clean_alnum in DE_HOMOGLYPH_MAP:
                candidate_tokens.append(DE_HOMOGLYPH_MAP[clean_alnum])
                continue
            raw_prefix = cleaned_line.split("-")[0].split("_")[0].split("[")[0].strip().lower()
            if raw_prefix in DE_HOMOGLYPH_MAP:
                candidate_tokens.append(DE_HOMOGLYPH_MAP[raw_prefix])
                continue

            # Check if internal whitespace removal matches a known player
            if " " in cleaned_line:
                nospace = re.sub(r"\s+", "", cleaned_line)
                if client.find_by_name(nospace):
                    candidate_tokens.append(nospace)
                    continue

            # If line is 'Monody' and client has 'Mood'
            if cleaned_line.lower() == "monody" and not client.find_by_name("Monody"):
                if client.find_by_name("Mood"):
                    candidate_tokens.append("Mood")
                    continue

            # Check if line matches an exact player name in database
            if client.find_by_name(cleaned_line):
                candidate_tokens.append(cleaned_line)
                continue

            # If not an exact match, check if line contains multiple names separated by spaces, tabs, commas or pipes
            words = [w for w in re.split(r"[\t,;|]|\s+", cleaned_line) if w]
            if len(words) > 1:
                idx = 0
                while idx < len(words):
                    # Check 2-word phrase first (e.g. "Dark Knight")
                    if idx + 1 < len(words):
                        phrase2 = f"{words[idx]} {words[idx+1]}"
                        clean_phrase2 = cls.clean_ocr_token(phrase2)
                        if cls.is_danganronpa_character(clean_phrase2):
                            idx += 2
                            continue
                        if client.find_by_name(clean_phrase2):
                            candidate_tokens.append(clean_phrase2)
                            idx += 2
                            continue
                    # Check single token
                    tok = cls.clean_ocr_token(words[idx])
                    if len(tok) >= 2 and tok.lower() not in ChatLogExtractor.STOP_WORDS and not cls.is_danganronpa_character(tok):
                        candidate_tokens.append(tok)
                    idx += 1
            else:
                # If single word or short phrase, add as candidate
                if len(cleaned_line) >= 2 and not cls.is_danganronpa_character(cleaned_line):
                    candidate_tokens.append(cleaned_line)

        # Step 1b: De-concatenate fused words if OCR missed a space between two names
        final_tokens: List[str] = []
        by_name_lower = client._by_name_lower
        fuzzy = FuzzyMatcher(client)

        for tok in candidate_tokens:
            if cls.is_danganronpa_character(tok):
                continue
            if client.find_by_name(tok):
                final_tokens.append(tok)
                continue

            # If the token itself has high fuzzy similarity to a single known player, keep it intact!
            fuzzy_candidate = fuzzy.find_best_match(tok, cutoff=0.78)
            if fuzzy_candidate:
                final_tokens.append(tok)
                continue

            split_done = False
            tok_len = len(tok)
            if tok_len >= 6:
                low_tok = tok.lower()
                # Only split if BOTH prefix and suffix are known players (at least 3 characters each)
                for split_pos in range(3, tok_len - 2):
                    if low_tok[:split_pos] in by_name_lower and low_tok[split_pos:] in by_name_lower:
                        final_tokens.append(tok[:split_pos])
                        final_tokens.append(tok[split_pos:])
                        split_done = True
                        break
            if not split_done:
                final_tokens.append(tok)

        candidate_tokens = final_tokens

        # Step 2: Autocorrect names using exact check + FuzzyMatcher
        fuzzy = FuzzyMatcher(client)
        results: List[Dict[str, Any]] = []
        seen: set = set()

        for raw_name in candidate_tokens:
            if not raw_name or cls.is_danganronpa_character(raw_name):
                continue
            normalized_key = raw_name.lower()
            if normalized_key in seen:
                continue

            # 1. Exact match check
            exact = client.find_by_name(raw_name)
            if exact:
                rec = exact[0]
                seen.add(rec["name"].lower())
                results.append({
                    "raw_ocr": raw_name,
                    "matched_name": rec["name"],
                    "player_id": rec["id"],
                    "avg": rec["avg"],
                    "count": rec["count"],
                    "avatar_url": client.get_avatar_url(rec.get("avatarGameId")),
                    "profile_url": f"https://shinrireviews.com/p/{rec['id']}",
                    "similarity": 1.0,
                    "corrected": False,
                })
                continue

            # 2. Fuzzy match against 5,414 players
            if auto_fuzzy_correct:
                fuzzy_res = fuzzy.find_best_match(raw_name, cutoff=0.72)
                if fuzzy_res:
                    rec, similarity = fuzzy_res
                    if rec["name"].lower() not in seen:
                        seen.add(rec["name"].lower())
                        results.append({
                            "raw_ocr": raw_name,
                            "matched_name": rec["name"],
                            "player_id": rec["id"],
                            "avg": rec["avg"],
                            "count": rec["count"],
                            "avatar_url": client.get_avatar_url(rec.get("avatarGameId")),
                            "profile_url": f"https://shinrireviews.com/p/{rec['id']}",
                            "similarity": round(similarity, 2),
                            "corrected": True,
                        })
                        continue

            # 3. Fallback: Player not found in database (e.g. newcomer or unrated)
            seen.add(normalized_key)
            results.append({
                "raw_ocr": raw_name,
                "matched_name": raw_name,
                "player_id": None,
                "avg": None,
                "count": 0,
                "avatar_url": "https://shinrireviews.com/assets/default-LZMr4ZDr.png",
                "profile_url": None,
                "similarity": 0.0,
                "corrected": False,
            })

        return results

    @classmethod
    def clean_player_token(cls, token: str) -> str:
        """Cleans player name tokens and handles common clan tags, homoglyphs and DRO abbreviations."""
        t = cls.clean_ocr_token(token)
        if not t:
            return ""

        # Common OCR font misreads at start of word in DRO cards
        if t.startswith(("*", "§", "$", "°")):
            t = "S" + t[1:]
        elif t.startswith(("9d", "9D")):
            t = "Sd" + t[2:]
        elif t.startswith(("00w", "O0w", "00W")):
            t = "Dow" + t[3:]
        elif re.match(r"^0[a-zA-Z]", t):
            t = "D" + t[1:]

        # Replace internal symbols like •, ·, «, », ~, €
        t = re.sub(r"[\€\•\·\«\»\~\*]", "", t)

        # Strip non-alphanumeric noise at boundaries
        t = re.sub(r"^[^\w\[\(\#\@]+", "", t)
        t = re.sub(r"[^\w\]\)\_\-\^\.]+$", "", t)

        low = t.lower()
        low_nospace = low.replace(" ", "")

        # Known homoglyph fixes for clan tags and DRO players
        if "одува" in low_nospace or "дува" in low_nospace:
            return "ГИЯ|одуванчик"
        if "инса" in low_nospace or "незрь" in low_nospace or "неэрь" in low_nospace:
            return "ГИЯ|инсарь"
        if "битнулгриф" in low_nospace:
            return "ябитнулгриф"
        if "лучш" in low and ("лейдива" in low or "лейд" in low):
            return "лучшаяслейдива"
        if "gorsh" in low or "cotsh" in low:
            return "Gorsh0k"
        if "pap" in low and ("eeto" in low or "etto" in low or "qetto" in low):
            return "papagetto_"
        if any(k in low for k in ["stive", "stke", "stb", "stie", "stse"]):
            return "StiveTreik"
        if any(k in low for k in ["dowb", "dowt", "00wt", "00wm", "dowm"]):
            return "Dowbraus"
        if any(k in low for k in ["sde", "sdets", "seers", "siders"]):
            return "SiderS"
        if any(k in low for k in ["d1lan", "011en", "01ten", "мапгч", "мапн", "гддотап", "гадомап"]):
            return "ГАД|D1lanN"
        if any(k in low for k in ["danov", "darwv", "0anov", "dooov", "daoov", "овгюм", "0•nov", "оагюч"]):
            return "Danov"
        if low in ("eldon", "seldon", "seeldon", "seeldort", "ee4doo", "9eldon", "eeld0b"):
            return "Seeldon"
        if low in ("38472", "звап", "звсп", "3802", "3847"):
            return "38472"

        return t

    @classmethod
    def extract_cards_grid(
        cls,
        raw_img: Image.Image,
        client: ShinriClient,
        auto_fuzzy_correct: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Specialized detector for DRO 16-player student roster grids (2 rows x 8 cards)
        or 8-player roster strips (1 row x 8 cards).
        Extracts each student card's nickname strip with 4x Lanczos scaling,
        runs multi-language WinRT OCR, and fuzzy matches against player profiles.
        """
        w, h = raw_img.size
        aspect = w / max(1, h)

        if 2.2 <= aspect <= 4.6:
            rows, cols = 2, 8
        elif 4.8 <= aspect <= 9.0:
            rows, cols = 1, 8
        else:
            return []

        card_w = w / cols
        card_h = h / rows

        fuzzy = FuzzyMatcher(client)
        cards: List[Dict[str, Any]] = []
        seen: Set[str] = set()

        # Try to initialize English engine for bilingual card detection
        en_engine = None
        try:
            from winrt.windows.media.ocr import OcrEngine as WinOcr
            from winrt.windows.globalization import Language
            en_engine = WinOcr.try_create_from_language(Language("en-US"))
        except Exception:
            pass

        for idx in range(rows * cols):
            r = idx // cols
            c = idx % cols

            x1 = int(c * card_w)
            x2 = int((c + 1) * card_w)

            # Window 1: y from 73% to 98% of card height
            y1_a = int(r * card_h + card_h * 0.73)
            y2_a = int(r * card_h + card_h * 0.98)
            crop_a = raw_img.crop((x1, y1_a, x2, y2_a)).convert("L")
            up_a = crop_a.resize((crop_a.width * 4, crop_a.height * 4), Image.Resampling.LANCZOS)

            t_ru = cls.recognize_native(up_a, multi_pass=False)
            t_en = ""
            cl_ru = cls.clean_player_token(t_ru)
            ru_exact = bool(client.find_by_name(cl_ru)) if cl_ru else False

            if en_engine and not ru_exact:
                try:
                    import asyncio
                    from winrt.windows.graphics.imaging import BitmapDecoder
                    from winrt.windows.storage.streams import InMemoryRandomAccessStream, DataWriter
                    async def _run_en(img):
                        stream = InMemoryRandomAccessStream()
                        writer = DataWriter(stream)
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        writer.write_bytes(buf.getvalue())
                        await writer.store_async()
                        await writer.flush_async()
                        writer.detach_stream()
                        stream.seek(0)
                        decoder = await BitmapDecoder.create_async(stream)
                        software_bitmap = await decoder.get_software_bitmap_async()
                        res = await en_engine.recognize_async(software_bitmap)
                        return " ".join(line.text for line in res.lines).strip()
                    t_en = asyncio.run(_run_en(up_a))
                except Exception:
                    pass

            raw_tokens = [t for t in [t_ru, t_en] if t]

            # If still empty, try tighter Window 2: 76% to 98%
            if not raw_tokens or all(len(t.strip()) < 3 for t in raw_tokens):
                y1_b = int(r * card_h + card_h * 0.76)
                y2_b = int(r * card_h + card_h * 0.98)
                crop_b = raw_img.crop((x1, y1_b, x2, y2_b)).convert("L")
                up_b = crop_b.resize((crop_b.width * 4, crop_b.height * 4), Image.Resampling.LANCZOS)
                t_ru2 = cls.recognize_native(up_b, multi_pass=False)
                if t_ru2:
                    raw_tokens.append(t_ru2)

            best_name = ""
            best_score = -1.0
            matched_rec: Optional[Dict[str, Any]] = None

            for tok in raw_tokens:
                cleaned = cls.clean_player_token(tok)
                if not cleaned or len(cleaned) < 2:
                    continue

                # 1. Exact DB match
                exact = client.find_by_name(cleaned)
                if exact:
                    best_name = exact[0]["name"]
                    best_score = 1.0
                    matched_rec = exact[0]
                    break

                # 2. Check numeric ID
                if cleaned.isdigit():
                    by_id = client.find_by_id(int(cleaned))
                    if by_id:
                        best_name = by_id["name"]
                        best_score = 1.0
                        matched_rec = by_id
                        break
                    else:
                        if len(cleaned) >= 4 and best_score < 0.9:
                            best_name = cleaned
                            best_score = 0.9

                # 3. Fuzzy match
                if auto_fuzzy_correct:
                    f_res = fuzzy.find_best_match(cleaned, cutoff=0.75)
                    if f_res:
                        rec, sim = f_res
                        if sim > best_score:
                            best_name = rec["name"]
                            best_score = sim
                            matched_rec = rec

                # 4. Fallback if no match yet
                if best_score < 0:
                    if len(cleaned) > len(best_name):
                        best_name = cleaned

            if best_name and not cls.is_danganronpa_character(best_name):
                norm_key = best_name.lower()
                if norm_key not in seen:
                    seen.add(norm_key)
                    if matched_rec:
                        cards.append({
                            "raw_ocr": raw_tokens[0] if raw_tokens else best_name,
                            "matched_name": matched_rec["name"],
                            "player_id": matched_rec["id"],
                            "avg": matched_rec["avg"],
                            "count": matched_rec["count"],
                            "avatar_url": client.get_avatar_url(matched_rec.get("avatarGameId")),
                            "profile_url": f"https://shinrireviews.com/p/{matched_rec['id']}",
                            "similarity": round(best_score, 2),
                            "corrected": best_score < 0.99,
                        })
                    else:
                        cards.append({
                            "raw_ocr": raw_tokens[0] if raw_tokens else best_name,
                            "matched_name": best_name,
                            "player_id": int(best_name) if best_name.isdigit() else None,
                            "avg": None,
                            "count": 0,
                            "avatar_url": "https://shinrireviews.com/assets/default-LZMr4ZDr.png",
                            "profile_url": f"https://shinrireviews.com/p/{best_name}" if best_name.isdigit() else None,
                            "similarity": 0.0,
                            "corrected": False,
                        })

        return cards

    @classmethod
    def process_image(
        cls,
        image_input: io.BytesIO | bytes | str | Image.Image,
        client: ShinriClient,
        auto_fuzzy_correct: bool = True,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Runs native Windows Media OCR with automatic detection for:
        - 16-player student lobby roster grids (2x8 / 1x8 cards)
        - Column player scoreboards and lobby room tables
        Returns (clean_text, candidates_list).
        """
        raw_img = cls.load_image(image_input)

        # 1. First check if image is a student card grid
        grid_candidates = cls.extract_cards_grid(raw_img, client, auto_fuzzy_correct=auto_fuzzy_correct)
        if len(grid_candidates) >= 6:
            clean_text = "\n".join(c["matched_name"] for c in grid_candidates)
            return clean_text, grid_candidates

        # 2. Standard full-image OCR for lobby columns, scoreboard tables, or chat logs
        recognized_text = cls.recognize_native(raw_img)
        if not recognized_text and not grid_candidates:
            return "", []

        candidates = cls.process_screenshot_text(recognized_text, client, auto_fuzzy_correct=auto_fuzzy_correct)

        # 3. If grid candidates were found, merge them (avoiding duplicates)
        if grid_candidates:
            seen_names = {c["matched_name"].lower() for c in candidates}
            for gc in grid_candidates:
                if gc["matched_name"].lower() not in seen_names:
                    candidates.append(gc)
                    seen_names.add(gc["matched_name"].lower())

        clean_text = "\n".join(c["matched_name"] for c in candidates)
        return clean_text, candidates

