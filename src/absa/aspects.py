"""Aspect descriptions used to initialize E4 queries.

Taken from the annotation guideline (Table 3 of the draft), without its repeated
"Các ý kiến đề cập đến" prefix, which would pull all queries toward the same vector.
Locked before error diagnosis: do not edit them based on validation or test errors.
"""

from .data import ASPECTS

ASPECT_DESCRIPTIONS = {
    "ky_nang_giang_day": "Kỹ năng giảng dạy: cách tổ chức dạy học, phương pháp dạy học lý thuyết và thực hành của giảng viên.",
    "hanh_vi": "Hành vi: hành vi, thái độ của giảng viên trong giảng dạy và giao tiếp với người học.",
    "de_xuat": "Đề xuất: đề xuất, mong muốn của sinh viên gửi đến giảng viên và nhà trường.",
    "bai_tap": "Bài tập: bài tập, số lượng bài tập và các loại bài tập của giảng viên.",
    "chuong_trinh_hoc": "Chương trình học: chương trình học và môn học.",
    "kien_thuc": "Kiến thức: mức độ hiểu biết của giảng viên về nội dung giảng dạy và kiến thức đã cung cấp cho sinh viên.",
    "kinh_nghiem": "Kinh nghiệm: kinh nghiệm thực tiễn và việc đưa nội dung thực tiễn lồng ghép vào bài giảng của giảng viên.",
    "cung_cap_tai_lieu": "Cung cấp tài liệu: việc cung cấp tài liệu, giáo trình, giáo án của giảng viên.",
    "thiet_bi_day_hoc": "Thiết bị dạy học: trang thiết bị dạy học như phòng học, máy chiếu, quạt và đèn.",
    "cham_diem": "Chấm điểm: hoạt động chấm điểm của giảng viên.",
    "noi_chung": "Nói chung: vấn đề chung của giảng viên hoặc những nhận xét không thuộc các khía cạnh khác.",
}


def aspect_texts() -> list[str]:
    """Descriptions in the same order as `ASPECTS`."""
    return [ASPECT_DESCRIPTIONS[name] for name in ASPECTS]
