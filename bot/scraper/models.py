"""Структуры данных для объявлений с сайта 4396200.com."""
from __future__ import annotations

from dataclasses import dataclass, field


# cate_code → корейское название → русское пояснение.
# Первые 6 подкатегорий — это сама техника (экскаваторы), последние 2 —
# навесное оборудование и запчасти. Для большинства запросов «найти
# экскаватор» запчасти и навесное только мешают, поэтому по умолчанию
# мониторим только МАШИНЫ (см. is_machine_subcategory ниже).
EXCAVATOR_SUBCATEGORIES: dict[str, tuple[str, str]] = {
    "100100": ("굴삭기 1.3 ㎥ 이상",    "Экскаваторы 1.3 м³ и выше"),
    "100101": ("굴삭기 1.0 ㎥ 이상",    "Экскаваторы 1.0 м³ и выше"),
    "100102": ("굴삭기 0.4 ~0.9 ㎥",   "Экскаваторы 0.4–0.9 м³"),
    "100103": ("굴삭기 0.3 ㎥ 이하",    "Экскаваторы до 0.3 м³"),
    "100104": ("미니굴삭기",            "Мини-экскаваторы"),
    "100105": ("굴삭기타이어식",        "Колёсные экскаваторы"),
    "100106": ("어태치먼트",            "Навесное оборудование"),
    "100107": ("굴삭기부속",            "Запчасти для экскаваторов"),
}

# Подкатегории, которые НЕ являются экскаватором как машиной.
PARTS_SUBCATEGORIES: frozenset[str] = frozenset({"100106", "100107"})


def is_machine_subcategory(cate_code: str | None) -> bool:
    """True, если код подкатегории — это самостоятельная техника, а не
    запчасть/навесное оборудование."""
    return bool(cate_code) and cate_code not in PARTS_SUBCATEGORIES


def target_subcategories(*, include_parts: bool) -> list[str]:
    """Список cate_code для обхода в зависимости от пользовательских настроек."""
    if include_parts:
        return list(EXCAVATOR_SUBCATEGORIES)
    return [c for c in EXCAVATOR_SUBCATEGORIES if c not in PARTS_SUBCATEGORIES]


# Точные корейские названия «не-машинных» листовых подкатегорий — сверяемся
# с ними. ВАЖНО: проверять надо ТОЛЬКО последний сегмент category_path
# (после '>'), потому что родитель пути в самом каталоге называется
# '굴삭기/어태치부속' — это название группы «Экскаваторы и навесное», и
# слово '어태치' встречается в нём у ВСЕХ восьми подкатегорий, в том числе
# у настоящих экскаваторов.
PARTS_LEAF_NAMES: frozenset[str] = frozenset(
    EXCAVATOR_SUBCATEGORIES[c][0] for c in PARTS_SUBCATEGORIES
)


def looks_like_parts(category_path: str | None) -> bool:
    """True, если category_path указывает на навесное/запчасти.

    Анализирует только последний сегмент пути ('A > B > C' → 'C').
    Родительская группа в названии содержит '어태치부속' у всех подкатегорий,
    поэтому substring-проверка по полному пути выдала бы ложноположительные
    срабатывания на настоящих экскаваторах.
    """
    if not category_path:
        return False
    leaf = category_path.split(">")[-1].strip()
    return leaf in PARTS_LEAF_NAMES


# -----------------------------------------------------------------------
# Грейд состояния (상태): A+급 / A급 / B+급 / B급
# -----------------------------------------------------------------------

GRADE_RANKS: dict[str, int] = {
    "A+": 4, "A": 3, "B+": 2, "B": 1,
}


def grade_rank(grade: str | None) -> int:
    """Числовой ранг грейда: A+ → 4, A → 3, B+ → 2, B → 1; неизвестное → 0.

    На сайте грейд обычно вида 'A+급'. Убираем суффикс '급' и нормализуем.
    """
    if not grade:
        return 0
    s = grade.strip().rstrip("급").strip()
    return GRADE_RANKS.get(s.upper(), 0)


def grade_label(rank: int) -> str:
    for label, r in GRADE_RANKS.items():
        if r == rank:
            return label + "급"
    return "—"


# -----------------------------------------------------------------------
# Регионы (위치): корейские провинции и города
# -----------------------------------------------------------------------

# Канонические короткие имена. Сайт пишет '강원도', '경기', '서울특별시' и
# подобное — будем нормализовать к этому списку.
REGIONS: list[tuple[str, str]] = [
    ("서울",   "Сеул"),
    ("인천",   "Инчхон"),
    ("경기",   "Кёнгидо"),
    ("강원",   "Канвондо"),
    ("충북",   "Чхунчхон-Пукто"),
    ("충남",   "Чхунчхон-Намдо"),
    ("대전",   "Тэджон"),
    ("전북",   "Чолла-Пукто"),
    ("전남",   "Чолла-Намдо"),
    ("광주",   "Кванджу"),
    ("경북",   "Кёнсан-Пукто"),
    ("경남",   "Кёнсан-Намдо"),
    ("대구",   "Тэгу"),
    ("부산",   "Пусан"),
    ("울산",   "Ульсан"),
    ("제주",   "Чеджу"),
]
REGION_KEYS: list[str] = [k for k, _ in REGIONS]
REGION_LABELS: dict[str, str] = dict(REGIONS)


# Окончания, которые убираем при сравнении: 도/시/특별시/광역시/특별자치도/특별자치시
_REGION_SUFFIXES = (
    "특별자치도", "특별자치시", "광역시", "특별시", "도", "시",
)


def normalize_region(region: str | None) -> str | None:
    """'강원도' → '강원', '서울특별시' → '서울'. Возвращает короткое имя или None."""
    if not region:
        return None
    s = region.strip()
    for suf in _REGION_SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            s = s[: -len(suf)]
            break
    # Иногда в карточке указано «경기 안성» (провинция + город). Берём первое слово.
    s = s.split()[0] if s else s
    # Сверяемся с известными ключами
    if s in REGION_KEYS:
        return s
    # На сайте бывают сокращения — пытаемся найти первое совпадение по началу.
    for key in REGION_KEYS:
        if s.startswith(key) or key.startswith(s):
            return key
    return None


def region_matches(item_region: str | None, allowed: list[str] | set[str] | None) -> bool:
    """True, если регион лота входит в выбранный пользователем набор.

    Пустой `allowed` (None или []) — фильтр выключен, пропускаем всё.
    """
    if not allowed:
        return True
    norm = normalize_region(item_region)
    if norm is None:
        # Регион неизвестен — лучше не отсекать, чтобы пользователь не пропустил
        # объявление с непарсящимся регионом.
        return True
    return norm in set(allowed)


@dataclass
class ListingPreview:
    """Краткая карточка из списка подкатегории (sub8_1_s.html)."""

    pid: int
    model: str | None = None
    price_raw: str | None = None    # «13,800만원»
    grade: str | None = None        # «A+급»
    cate_code: str | None = None    # подкатегория, в которой найден лот


@dataclass
class Listing:
    """Полная карточка одного объявления (sub8_1_vvv.html?pid=…)."""

    pid: int
    url: str

    status: str | None = None            # 구분: 팝니다 / 삽니다
    category_path: str | None = None     # 분류: «굴삭기/어태치부속 > 굴삭기 1.3 ㎥ 이상»
    manufacturer: str | None = None      # 제작사: «볼보»
    model: str | None = None             # 모델명
    year: str | None = None              # 제작년월: «2014.01»
    grade: str | None = None             # 상태: «A+급»
    region: str | None = None            # 위치
    price_raw: str | None = None         # 가격: «6,000만원»
    price_won: int | None = None         # цена в воннах (распарсенная)

    seller: str | None = None            # 상호
    phone: str | None = None             # 연락처

    engine: str | None = None            # 엔진
    transmission: str | None = None      # 밋션
    tonnage: str | None = None           # 톤수
    hours_raw: str | None = None         # 운행 (текст из ячейки)
    hours: int | None = None             # моточасы (распарсенные)
    installment: str | None = None       # 할부여부/원금
    accident: str | None = None          # 사고여부
    undercarriage_type: str | None = None    # 하부타입
    undercarriage_state: str | None = None   # 하부상태

    posted_at: str | None = None         # «2026-05-13 10:21:22»
    description: str | None = None

    photos: list[str] = field(default_factory=list)   # абсолютные URL крупных миниатюр

    def main_photo(self) -> str | None:
        return self.photos[0] if self.photos else None
