# Bộ chuyển đổi môi trường: Antigravity

> **Chỉ áp dụng khi agent đang chạy trong Antigravity** — dấu hiệu: ngữ cảnh có khối `<user_information>` chứa `appDataDir`. Agent khác **bỏ qua toàn bộ tệp này** và làm theo phần chung trong `SKILL.md`.
>
> Tệp này gom mọi chi tiết phụ thuộc vào cách Antigravity vận hành (đường dẫn nội bộ, tên công cụ, giới hạn công cụ). Các chi tiết này **có thể thay đổi theo phiên bản Antigravity**: khi Antigravity cập nhật, chỉ cần sửa tệp này, không phải sửa `SKILL.md`.

## 1. Ánh xạ thao tác trong `SKILL.md` sang công cụ Antigravity

Tên công cụ dưới đây theo tài liệu Antigravity (trang Hooks) và bản 2.34: agent đọc tệp bằng `view_file`. Một số phiên bản/cấu hình (vd khai báo quyền cho subagent) gọi cùng thao tác là `read_file` / `edit_file` / `write_file` — nếu danh sách công cụ của bạn dùng tên đó thì ánh xạ tương ứng.

| Cách viết trong `SKILL.md` | Công cụ Antigravity |
| :--- | :--- |
| "đọc tệp", "đọc trọn 1 lần", "đọc toàn bộ, không chia đoạn" | `view_file` (hoặc `read_file`) **không** truyền `StartLine`/`EndLine` |
| "đọc theo từng đoạn" (tệp lớn: `manifest.json` vượt ngưỡng, `work\translated.md` dài) | `view_file` với `StartLine`/`EndLine` |
| "mở xem song song trong 1 lượt" các ảnh đã tách | Nhiều lệnh `view_file` gọi **cùng một lượt**, mỗi lệnh một đường dẫn cụ thể (`work\assets\fig_p2_1.png`...), **không** dùng ký tự đại diện `*` |
| "ghi nối dần" vào `work\draft.html` / `work\translated.md` | Lô đầu `write_to_file`; các lô sau `replace_file_content` / `multi_replace_file_content` (hoặc `edit_file`) chèn nội dung mới ngay trước phần đóng tệp |

- **Giới hạn hiện tại của `view_file`:** khoảng 800 dòng / 46 KB mỗi lần gọi; lần đầu mở một tệp, Antigravity luôn trả 800 dòng đầu dù có truyền `StartLine`/`EndLine`. Các tệp SI (`si_academic_html.md`, `si_translation.md`, `si_layout.md`) đều nằm trong giới hạn này nên đọc trọn được trong 1 lần.

## 2. Tải lên tệp (kéo thả vào khung chat hoặc bấm nút thêm tệp `+`)

- **Dấu hiệu:** tin nhắn của người dùng đã có sẵn nội dung OCR/ảnh từng trang PDF và người dùng **không** nêu đường dẫn tệp `.pdf` trên đĩa.
- **Lấy tệp PDF thật:** **không** dùng `read_file` mở `transcript.jsonl`; chạy thẳng lệnh sau ở Bước 1 (thay `<appDataDir>` và `<conversation-id>` bằng giá trị có sẵn trong `<user_information>`), giữ nguyên các tham số còn lại như lệnh Bước 1 trong `SKILL.md`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'tools\extract_pdf_assets.ps1' -TranscriptPath '<appDataDir>\brain\<conversation-id>\.system_generated\logs\transcript.jsonl' -OutDir 'work\assets' -Meta
```

  - `-TranscriptPath` tự đọc ngược transcript, tìm lượt `USER_INPUT` gần nhất có đính kèm `.pdf`, và in `Resolved PDF -> <đường_dẫn_PDF_thực>`. Dùng đúng đường dẫn này cho `-PdfPath` ở các lệnh sau (vd `RenderPages` trong phụ lục fallback).
  - Nếu lệnh báo không tìm thấy transcript hoặc không tìm thấy PDF (Antigravity có thể đã đổi cấu trúc thư mục nội bộ), **không đoán đường dẫn khác**: đề nghị người dùng đặt tệp PDF vào thư mục `input\` của dự án rồi làm lại Bước 1 với `-PdfPath`.
- **Đọc nội dung PDF:** nội dung và ảnh từng trang đã có trong tin nhắn đầu vào — **không** đọc lại tệp PDF lần 2.
- **Tên tệp tạm `media_<id>.pdf`:** Antigravity sao chép tệp tải lên vào thư mục của phiên (`<appDataDir>\brain\<conversation-id>\.user_uploaded\media_<id>.pdf`, chính là đường dẫn in ở dòng `Resolved PDF -> ...`) và đổi sang tên tạm; tên gốc trên máy người dùng không được giữ lại. Khi đặt tên đầu ra ở Bước 4: **không** dùng `media_...`, **không** tìm ngược tên gốc trên máy; đặt theo tiêu đề chính ngắn gọn của tài liệu (ASCII `snake_case`, không dấu) kèm hậu tố của skill (`_vi` hoặc `_layout_vi`), trừ khi người dùng chỉ định tên.
- **Giới hạn tải lên:** khung chat Antigravity nhận tệp tối đa khoảng 10 MB. PDF lớn hơn cần được đặt vào `input\` và xử lý như tệp trên đĩa.
