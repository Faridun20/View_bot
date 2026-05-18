"""Структуры данных для объявлений с сайта 4396200.com."""
from __future__ import annotations

from dataclasses import dataclass, field


# cate_code → корейское название → русское пояснение
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
