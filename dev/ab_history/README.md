# Lịch sử chấm mù trái/phải (A/B)

Mỗi tệp `ab_key_<mã>.json` là một đợt chấm do `dev/ab_judge.py` tạo. Tệp gồm:

- dấu vân tay của bản cũ (`old_fp`) và bản mới (`new_fp`);
- với từng hình: tài liệu, trang, bên nào là bản mới, các hộp ảnh xuất ra;
- mã người chấm dán lại (`answers`) và kết quả đã giải mã (`result`).

Không có ảnh trong các tệp này: trang chấm chứa ảnh cắt từ bài báo của bên thứ ba nên chỉ để cục bộ.

Các đợt sau tự bỏ qua những tài liệu đã có ở đây, để mỗi tài liệu chỉ được chấm một lần.

| Đợt | Cũ → mới | Hình | Mới tốt hơn | Cũ tốt hơn | Như nhau | Cả hai tệ | Kết luận |
|---|---|---|---|---|---|---|---|
| AB1 | `98b5395668dac5a6` → `37db5525b514bdce` | 30 | 9 | 1 | 18 | 2 | |
| AB2 | như trên | 50 | 14 | 2 | 30 | 4 | |
| AB3 | như trên | 70 | 28 | 1 | 35 | 6 | Gộp 150 hình: 51:4, p = 2e-11 → commit `198d9c8` (v1.1.14) |
| AB4 | `37db5525b514bdce` → `403db2febc3b7420` | 35 | 7 | 11 | 11 | 6 | Loại; xem `dev/experiments/fix3_rejected_by_AB4.patch` |

Dấu vân tay là băm mã nguồn `tools/src/figure_detector/*.py` và `image_ops.py`, do `eval_doclaynet.detector_fingerprint` tính. `37db5525b514bdce` chính là mã đang có trong `main`.
