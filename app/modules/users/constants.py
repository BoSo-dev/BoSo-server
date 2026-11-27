from typing import Literal, get_args

RegionCode = Literal[
    "seoul",
    "busan",
    "daegu",
    "incheon",
    "gwangju",
    "daejeon",
    "ulsan",
    "sejong",
    "gyeonggi",
    "gangwon",
    "chungbuk",
    "chungnam",
    "jeonbuk",
    "jeonnam",
    "gyeongbuk",
    "gyeongnam",
    "jeju",
]
TransportMode = Literal["bus", "subway"]
TransportCard = Literal["k_pass", "climate_card", "other_or_none"]

REGION_CODES = get_args(RegionCode)
TRANSPORT_MODES = get_args(TransportMode)
TRANSPORT_CARDS = get_args(TransportCard)

REGION_LABELS = (
    "서울",
    "부산",
    "대구",
    "인천",
    "광주",
    "대전",
    "울산",
    "세종",
    "경기",
    "강원",
    "충북",
    "충남",
    "전북",
    "전남",
    "경북",
    "경남",
    "제주",
)
MODE_LABELS = ("버스", "지하철")
CARD_LABELS = ("K-패스", "기후동행카드", "기타 / 이용 카드 없음")
