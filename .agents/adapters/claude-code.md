# Bộ chuyển đổi môi trường: Claude Code

> **Chỉ áp dụng cho Claude Code** (tab Code trong ứng dụng desktop Claude hoặc Claude Code dòng lệnh) chạy trên Windows. Tệp này được nạp tự động qua `CLAUDE.md`; agent khác bỏ qua.
>
> Tệp gom các chi tiết phụ thuộc vào cách Claude Code vận hành. Khi Claude Code thay đổi, chỉ cần sửa tệp này, không phải sửa `SKILL.md`.

## 1. Chạy lệnh công cụ

- Chạy **nguyên văn** các lệnh `tools\*.ps1` trong `SKILL.md` (chỉ thay giá trị trong `<...>`) bằng công cụ **PowerShell** của Claude Code.
- Nếu phiên Claude Code chỉ có công cụ **Bash**, vẫn chạy nguyên văn lệnh đó trong Bash: lệnh tự mở chương trình PowerShell có sẵn trên Windows. Riêng tệp có dấu `'` trong tên (vd `O'Brien 2024.pdf`), Bash làm hỏng đường dẫn; khi đó hãy đề nghị người dùng đổi tên tệp.
- `.claude/settings.json` của dự án cho phép sẵn đúng dạng lệnh này (qua cả công cụ PowerShell lẫn Bash) với 3 script `tools\extract_pdf_assets.ps1`, `tools\pdf_fallback_tools.ps1`, `tools\html_packager.ps1`. Viết khác đi (vd `& .\tools\html_packager.ps1 ...`, đổi thứ tự tham số đầu) sẽ khiến Claude Code phải hỏi lại người dùng.
- **Mỗi lệnh chạy riêng một lần gọi**, không nối nhiều lệnh bằng `;`, `&&` hay `|`.

## 2. Lấy tệp PDF

Người dùng đưa tệp PDF theo một trong hai cách; cả hai đều dùng lệnh `-PdfPath` của Bước 1 (Trường hợp 2):

- **Tải lên tệp** (kéo thả vào khung chat hoặc bấm nút thêm tệp `+`): ứng dụng chèn vào tin nhắn đường dẫn gốc của tệp dạng `@"<đường dẫn>"` và tự đọc nội dung PDF. Dùng đúng đường dẫn đó cho `-PdfPath`, không đọc lại tệp PDF.
- **Nêu đường dẫn bằng lời:** nếu người dùng nhắc tệp bằng `@` hoặc ghi đủ đường dẫn, dùng ngay đường dẫn đó. Nếu chỉ mô tả vị trí (vd "file PDF trong thư mục input"), tìm tệp `.pdf` trong đúng thư mục đó **một lần**; có nhiều tệp thì hỏi người dùng chọn tệp nào, không tự đoán.
- Nếu không lấy được đường dẫn tệp trên đĩa (vd người dùng chỉ dán ảnh hoặc chữ), đề nghị họ đặt tệp PDF vào thư mục `input\` của dự án.

## 3. Đọc nội dung PDF

- **PDF tới 10 trang** (theo `total_pages` ở Bước 1): đọc cả tệp bằng **một lệnh `Read` chỉ có `file_path`, tuyệt đối không kèm tham số `pages`** (kể cả `pages: "1-5"` cho đủ số trang). Đọc cả tệp như vậy, Claude nhận được cả lớp chữ của PDF lẫn hình ảnh từng trang, nên chữ, số liệu và ký hiệu chính xác hơn đọc từ ảnh render, và không cần `pdftoppm`. Chính tham số `pages` mới đòi `pdftoppm`.
- **PDF trên 10 trang:** **không** dùng `Read` với tham số `pages`. Cách đọc theo cụm trang đó cần chương trình `pdftoppm` (poppler), hầu như không có sẵn trên Windows, và chỉ gây thêm một lời gọi lỗi cùng thông báo `pdftoppm is not installed` làm người dùng hoang mang. Đi thẳng mục **"Agent không đọc trực tiếp được PDF"** trong `SKILL.md`: render từng cụm trang bằng `RenderPages` (PyMuPDF có sẵn trong `extract_assets.exe`) rồi mở xem các ảnh trang.
- Nếu vì lý do nào đó vẫn gặp thông báo `pdftoppm is not installed`, **không tự cài phần mềm** và không hướng dẫn người dùng cài; chuyển sang `RenderPages` như trên.

## 4. Ánh xạ thao tác trong `SKILL.md` sang công cụ Claude Code

| Cách viết trong `SKILL.md` | Công cụ Claude Code |
| :--- | :--- |
| "đọc tệp", "đọc trọn 1 lần" (các tệp SI) | `Read` cả tệp — các tệp SI đều nhỏ hơn giới hạn một lần đọc của `Read` |
| "đọc theo từng đoạn" (`manifest.json` lớn, `work\translated.md` dài) | `Read` với `offset`/`limit` |
| "mở xem song song trong 1 lượt" các ảnh đã tách | Nhiều lệnh `Read` trong **cùng một lượt trả lời**, mỗi lệnh một đường dẫn ảnh cụ thể, không dùng ký tự đại diện `*` |
| "ghi nối dần" vào `work\draft.html` / `work\translated.md` | Lô đầu: `Write` tạo tệp và đặt dòng đánh dấu `<!-- MAX-LUKA-CONTINUE -->` ngay trước phần đóng (`</article></body></html>` hoặc cuối tệp Markdown). Mỗi lô sau: `Edit` thay dòng đánh dấu bằng nội dung lô mới **kèm lại** dòng đánh dấu. Lô cuối: xóa dòng đánh dấu |
