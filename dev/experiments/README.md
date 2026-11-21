# Thử nghiệm bộ tách hình chưa được nhận

## `fix3_rejected_by_AB4.patch`

Bản vá nối tiếp `198d9c8`, sửa `tools/src/figure_detector/pipeline.py` và `tests/test_detector_fixes.py`. Phần sửa `CHANGELOG.md` trong bản vá đã cũ, đừng áp dụng phần đó.

Áp dụng phần mã:

```
git apply --include=tools/* --include=tests/* dev/experiments/fix3_rejected_by_AB4.patch
```

Bản vá gộp ba quy tắc vào bước gom nhãn theo dòng:

1. Khi nới sang trái/phải, bỏ qua dòng nằm gần một đồ họa khác hơn là gần hình đang xét. Đường trục được nới 0,5 pt để có diện tích.
2. Loại mảnh phương trình (dòng bắt đầu bằng `=`, `+`, `−`…, ngoặc lớn TeX) và các dòng cùng hàng.
3. Loại dòng chữ đầu tiên/cuối cùng của trang (rộng ≥ 30 pt), bất kể lề trang.

Kết quả chấm mù AB4: thua 7:11. Chỉ số DocLayNet cho thấy ảnh lấn chữ giảm, đổi lại hình bị cắt thiếu tăng nhẹ.

Nguyên nhân thua:

- Quy tắc 1 làm mất số chia trục Y và tiêu đề trục của chính hình, vì đường trục giờ được tính là "đồ họa khác".
- Quy tắc 3 làm mất tiêu đề biểu đồ nằm sát mép trên trang.

Hướng làm tiếp: đưa lại từng quy tắc một và chấm mù riêng mỗi quy tắc. Thứ tự đề xuất:

1. quy tắc 2;
2. quy tắc 3, nhưng thu hẹp tín hiệu, ví dụ chỉ khi dòng lặp lại ở trang khác hoặc khớp mẫu tiêu đề chạy;
3. quy tắc 1, chỉ khi đồ họa bên cạnh rõ ràng là một hình khác (có chú thích riêng hoặc là ứng viên khác), không tính trục của chính hình.
