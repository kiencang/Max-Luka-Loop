# Bộ chuyển đổi môi trường: Antigravity

> **Chỉ áp dụng khi agent đang chạy trong Antigravity** — dấu hiệu: ngữ cảnh có khối `<user_information>` chứa `App Data Directory` (tương ứng `<appDataDir>` trong `<artifacts>` / `<conversation_transcript>`, kèm `Conversation ID` và `Artifact Directory Path`). Agent khác **bỏ qua toàn bộ tệp này** và làm theo phần chung trong `SKILL.md`.
>
> Tệp này gom mọi chi tiết phụ thuộc vào cách Antigravity vận hành (đường dẫn nội bộ, tên công cụ, giới hạn công cụ). Các chi tiết này **có thể thay đổi theo phiên bản Antigravity**: khi Antigravity cập nhật, chỉ cần sửa tệp này, không phải sửa `SKILL.md`.

## 1. Ánh xạ thao tác trong `SKILL.md` sang công cụ Antigravity

Antigravity 2.0 dùng bộ công cụ tệp `read_file` / `write_file` / `edit_file` và chạy lệnh bằng `run_command` (shell `pwsh`). Một số phiên bản cũ hơn hoặc Antigravity IDE gọi cùng thao tác tệp là `view_file` / `write_to_file` / `replace_file_content` / `multi_replace_file_content` — nếu danh sách công cụ của bạn dùng tên đó thì ánh xạ tương ứng.

| Cách viết trong `SKILL.md` | Công cụ Antigravity |
| :--- | :--- |
| "đọc tệp", "đọc trọn 1 lần", "đọc toàn bộ, không chia đoạn" | `read_file` (bản cũ: `view_file`) với đường dẫn tuyệt đối, **không** truyền `StartLine`/`EndLine` |
| "đọc theo từng đoạn" (`manifest.json` vượt ngưỡng, `work\translated.md` dài) | `read_file` (bản cũ: `view_file`) với `StartLine`/`EndLine` (và `ByteOffset` nếu chạm giới hạn byte) |
| "mở xem song song trong 1 lượt" các ảnh đã tách | Nhiều lệnh `read_file` (bản cũ: `view_file`) gọi **cùng một lượt**, mỗi lệnh một đường dẫn tuyệt đối cụ thể (`<workspace>\work\assets\fig_p2_1.png`...), **không** dùng ký tự đại diện `*` |
| "ghi nối dần" vào `work\draft.html` / `work\translated.md` | Ưu tiên `write_file`: lô đầu tạo tệp, các lô sau truyền `Append: true` (với `work\draft.html`, để phần đóng `</article></body></html>` hoặc `</body></html>` ở lô cuối). Nếu dùng `edit_file` (bản cũ: `write_to_file` + `replace_file_content` / `multi_replace_file_content`), chèn nội dung mới ngay trước phần đóng tệp |
| Chạy lệnh PowerShell `tools\*.ps1` | `run_command` (shell `pwsh`, mỗi lần gọi là phiên mới). Đặt `WaitMsBeforeAsync` tối đa (`10000` ms); nếu lệnh tách ảnh hoặc xuất PDF chạy lâu hơn và chuyển chạy nền, **dừng lượt chờ hệ thống báo lại**, không tự poll hay dùng lệnh `sleep` |

- **Giới hạn đọc tệp mỗi lần gọi:** khoảng 800 dòng / 45 KB (`46.080` bytes). Các tệp SI (`si_academic_html.md`, `si_translation.md`, `si_layout.md`) đều nhỏ hơn ngưỡng này nên đọc trọn được trong 1 lần. *(Lưu ý tương thích ngược: `read_file` ở Antigravity 2.0 tôn trọng `StartLine`/`EndLine` ngay lần mở đầu; riêng một số bản cũ dùng `view_file` có thể luôn trả 800 dòng đầu ở lần mở đầu tiên.)*
- **Không tạo Artifact / tệp `scratch/` khi dịch:** Dù Antigravity có thư mục Artifact (`<appDataDir>\brain\<conversation-id>`), khi dịch tài liệu **chỉ** ghi tệp tạm vào `work\` và tệp kết quả vào `output\` trong workspace, không tạo thêm Artifact markdown hay tệp trong `scratch\`.

## 2. Lấy tệp PDF (tải lên khung chat vs. tệp trên đĩa)

- **Trường hợp 1 — Tải lên khung chat** *(kéo thả vào khung chat hoặc bấm nút thêm tệp `+`; tin nhắn đã có sẵn khối ảnh chụp/OCR từng trang PDF và người dùng không nêu đường dẫn `.pdf` trên đĩa)*:
  - **Lấy tệp PDF thật:** **không** dùng `read_file` mở `transcript.jsonl`; chạy thẳng lệnh sau ở Bước 1 (thay `<appDataDir>` và `<conversation-id>` bằng `App Data Directory` và `Conversation ID` trong `<user_information>` — phần `<appDataDir>\brain\<conversation-id>` cũng chính là `Artifact Directory Path`), giữ nguyên các tham số còn lại như lệnh Bước 1 trong `SKILL.md`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'tools\extract_pdf_assets.ps1' -TranscriptPath '<appDataDir>\brain\<conversation-id>\.system_generated\logs\transcript.jsonl' -OutDir 'work\assets' -Meta
```

  - `-TranscriptPath` tự đọc ngược transcript, tìm lượt `USER_INPUT` gần nhất có đính kèm `.pdf`, và in `Resolved PDF -> <đường_dẫn_PDF_thực>`. Dùng đúng đường dẫn này cho `-PdfPath` ở các lệnh sau (vd `RenderPages` trong phụ lục fallback).
  - Nếu lệnh báo không tìm thấy transcript/PDF hoặc bị từ chối quyền truy cập ngoài workspace (do bật Terminal Sandbox, cài Non-Workspace File Access là `deny`, hoặc Antigravity đổi cấu trúc thư mục nội bộ), **không đoán đường dẫn khác**: đề nghị người dùng đặt tệp PDF vào thư mục `input\` của dự án rồi làm lại Bước 1 với `-PdfPath`.
  - **Tên tệp tạm `media_<id>.pdf`:** Antigravity sao chép tệp tải lên vào thư mục của phiên (`<appDataDir>\brain\<conversation-id>\.user_uploaded\media_<id>.pdf`, chính là đường dẫn in ở dòng `Resolved PDF -> ...`) và đổi sang tên tạm; tên gốc trên máy người dùng không được giữ lại. Khi đặt tên đầu ra ở Bước 4: **không** dùng `media_...`, **không** tìm ngược tên gốc trên máy; đặt theo tiêu đề chính ngắn gọn của tài liệu (ASCII `snake_case`, không dấu) kèm hậu tố của skill (`_vi` hoặc `_layout_vi`), trừ khi người dùng chỉ định tên.
  - **Giới hạn tải lên:** khung chat Antigravity nhận tệp tối đa khoảng 10 MB. PDF lớn hơn cần được đặt vào `input\` và xử lý như Trường hợp 2.

- **Trường hợp 2 — Tệp PDF nằm sẵn trên đĩa** *(người dùng nêu đường dẫn hoặc gắn `@` tới tệp `.pdf` trong workspace, vd đặt trong `input\`)*:
  - Dùng thẳng `-PdfPath` ở Bước 1 (không dùng `-TranscriptPath`).

## 3. Đọc nội dung PDF

- **PDF đã tải lên khung chat (Trường hợp 1):** nội dung OCR và ảnh từng trang đã có sẵn trong tin nhắn đầu vào — **không** gọi `read_file` đọc lại tệp PDF lần 2.
- **PDF nằm sẵn trên đĩa (Trường hợp 2):** `read_file` của Antigravity đọc trực tiếp được tệp `.pdf` cục bộ (trả về ảnh từng trang và lớp chữ OCR). Với tài liệu ngắn/vừa, đọc trực tiếp bằng `read_file`; nếu tệp quá lớn, quá dài hoặc `read_file` báo lỗi/vượt giới hạn, chuyển sang mục **"Agent không đọc trực tiếp được PDF"** trong `SKILL.md` (render từng cụm `5–8` trang bằng `RenderPages` rồi mở xem song song các ảnh `work\pages\page_<p>.png`).
