# Max Luka Loop
Công cụ AI Agent tự động dịch tài liệu PDF từ tiếng Anh sang tiếng Việt. Không yêu cầu cài thêm bất cứ phần mềm hỗ trợ nào. Chỉ cần mở thư mục trên [Antigravity](https://antigravity.google/), Claude Code là bắt đầu dùng được ngay.

- Định dạng đầu vào: PDF, nên dưới 50 trang. Hình ảnh, biểu đồ được tìm bằng mô hình bố cục Egret (chạy ngay trên CPU của máy), nên **cả PDF scan cũng được tự động cắt hình**; riêng phần chữ của bản scan vẫn tốn thời gian hơn vì AI phải đọc từ ảnh trang.
- Định dạng đầu ra mặc định: Bản dịch tiếng Việt trả về ở cả 2 định dạng đồng thời là HTML và PDF. Định dạng HTML thường có kết quả hiển thị tốt hơn.

PS: Nếu file PDF bạn hay dùng để dịch là file tiêu chuẩn (không phải dạng scan), bạn có thể sử dụng phiên bản nhỏ gọn hơn của Max-Luka-Loop ở đây: https://github.com/kiencang/Luka-Loop

## Cách dùng
Rất đơn giản, bạn tải trực tiếp gói dựng sẵn mới nhất tại đây:

- **Tải bản mới nhất:** [max-luka-loop-win-x64.zip](https://github.com/kiencang/Max-Luka-Loop/releases/latest/download/max-luka-loop-win-x64.zip)
- *(Nếu mở trang [GitHub Releases](https://github.com/kiencang/Max-Luka-Loop/releases), hãy chọn tệp **`max-luka-loop-win-x64.zip`** trong mục **Assets** — không tải `Source code (zip)` vì gói mã nguồn thô từ Git không kèm sẵn `extract_assets.exe`).*

Sau đó giải nén file zip đó ở bất kỳ thư mục làm việc nào mà bạn muốn. Khi giải nén, nhớ chọn tùy chọn `Extract Here`, mở thư mục `max-luka-loop` vừa giải nén thấy ngay file có tên `AGENTS.md` nghĩa là bạn đã giải nén thành công (nếu thích, bạn có thể đổi tên thư mục `max-luka-loop` sang tên khác cũng không vấn đề gì).

Phần khó nhất đã xong! Giờ để dùng công cụ dịch, bạn chỉ việc vào Antigravity, chọn `Workspace > Create Project > Add Folder`, rồi bạn thêm thư mục vừa giải nén xong là OK.

Giờ thì bạn chỉ việc tải file PDF vào khung chat rồi gõ câu lệnh kiểu như `Dịch tài liệu sang tiếng Việt.` là agent Gemini sẽ tiến hành dịch, và gửi kết quả về ở cả 2 định dạng HTML và PDF. 

Nếu muốn bản dịch **giữ sát bố cục/thiết kế gốc** của từng trang của PDF (sách, tạp chí, tài liệu nhiều cột...), hãy nêu rõ trong yêu cầu (ví dụ: `Dịch tài liệu sang tiếng Việt và bảo toàn thiết kế/layout.`).

Dung lượng file: Nếu bạn tải file lên từ khung chat, giới hạn của Antigravity là 10MB, trường hợp bạn có file lớn hơn, bạn nên đặt vào thư mục `input` của chương trình này.

**Lưu ý**:
- Khi làm việc với Antigravity, bạn có thể chọn chế độ **Turbo** (thay vì mặc định Request Review) để tránh phải xác nhận lặp lại các lệnh đóng gói; tuy nhiên **chỉ nên dùng Turbo với tài liệu PDF từ nguồn tin cậy** *(với PDF lạ, nên giữ Request Review để kiểm soát lệnh thực thi)*.
- Nếu đặt thư mục `max-luka-loop` bên trong vùng đồng bộ đám mây (OneDrive, Google Drive, Dropbox...), hãy bật tùy chọn giữ tệp ngoại tuyến trên máy (*Always keep on this device* / *Mirror files* / *Available offline*) để `extract_assets.exe` nạp đủ các thư viện và mô hình đi kèm, và tránh lồng đường dẫn quá sâu vượt giới hạn ký tự trên Windows. Nếu mô hình không nạp được, bước tách ảnh sẽ dừng và báo lỗi thay vì cho ra kết quả kém.

## Dùng với Claude Code
Ngoài Antigravity, bạn có thể dùng công cụ với **Claude Code** (tab Code trong ứng dụng Claude desktop) trên Windows:

- Mở thư mục `max-luka-loop` trong Claude Code. Lần đầu mở, hãy chấp nhận hộp thoại tin cậy thư mục (workspace trust) để các quyền chạy sẵn trong [`.claude/settings.json`](./.claude/settings.json) có hiệu lực.
- Gõ yêu cầu kèm đường dẫn tệp PDF, ví dụ `Dịch input/bao-cao.pdf sang tiếng Việt.` (hoặc thêm `và bảo toàn thiết kế/layout.`).
- Với PDF trên 10 trang, agent dựng ảnh từng cụm trang bằng `extract_assets.exe` có sẵn (PyMuPDF) để đọc, nên không cần cài thêm chương trình `pdftoppm` (poppler) mà công cụ đọc PDF của Claude Code đòi hỏi khi đọc theo cụm trang.
- [`.claude/settings.json`](./.claude/settings.json) cho phép Claude Code chạy 3 script công cụ trong `tools\` mà không hỏi lại mỗi lần. Nếu muốn được hỏi trước mỗi lệnh, xóa các dòng trong `permissions.allow`.

## Yêu cầu hệ thống
- **Hệ điều hành:** Windows 10 hoặc Windows 11 **64-bit (x64)** *(bộ công cụ `extract_assets.exe` hiện biên dịch ở kiến trúc x64, chưa hỗ trợ Windows 32-bit), hầu hết các máy tính hiện nay trên thị trường đều là bản 64-bit*.
- **PowerShell:** Hỗ trợ cả **Windows PowerShell 5.1** (có sẵn mặc định trên Windows 10/11) lẫn **PowerShell 7+** (`pwsh.exe`), không yêu cầu cấu hình thêm.
- **Dung lượng & tốc độ:** Thư mục sau giải nén khoảng 220 MB (gồm Python portable, PyMuPDF, ONNX Runtime và mô hình Egret ~75 MB). Tách ảnh mất khoảng 1 giây/trang trên CPU laptop phổ thông; không cần GPU.
- **Trình duyệt (tùy chọn để tự động xuất PDF):** Công cụ dùng Microsoft Edge (ưu tiên) hoặc Google Chrome để xuất tệp PDF. Nếu không có, quy trình vẫn xuất hoàn chỉnh tệp `*_vi.html`.

## Lý do tồn tại
Tôi đã có sản phẩm https://github.com/kiencang/PDF-silaTranslator có chức năng tương đương, nhưng hiện tại chỉ API Key trả phí mới sử dụng được. 

**Max Luka Loop và [Luka-Loop](https://github.com/kiencang/Luka-Loop):** Max Luka Loop được tách ra từ Luka-Loop (v1.1.17) để phát triển riêng. Khác biệt chính nằm ở khâu tách ảnh: Luka-Loop tìm hình bằng các quy tắc hình học, còn Max Luka Loop dùng mô hình bố cục **Egret Medium** của dự án [Docling](https://github.com/docling-project/docling) (IBM Research), nên cắt hình chính xác hơn và xử lý được cả PDF scan. Đổi lại, gói tải về nặng hơn (khoảng 220 MB so với khoảng 60 MB) và tách ảnh chậm hơn. Trên bộ kiểm thử DocLayNet (943 trang bài báo khoa học), số trang có lỗi tách hình nghiêm trọng giảm từ 44 xuống 14.

## Cấu trúc dự án
- [`AGENTS.md`](./AGENTS.md) — Quy tắc điều phối dành cho AI Agent trong workspace.
- [`.agents/skills/pdf-to-html-vi/`](./.agents/skills/pdf-to-html-vi/) — Skill mặc định `pdf-to-html-vi` (giao diện 1 cột) gồm quy trình 4 bước ([`SKILL.md`](./.agents/skills/pdf-to-html-vi/SKILL.md)) và bộ dịch thuật học thuật / dàn trang ([`si_academic_html.md`](./.agents/skills/pdf-to-html-vi/si_academic_html.md)).
- [`.agents/skills/pdf-to-html-vi-layout/`](./.agents/skills/pdf-to-html-vi-layout/) — Skill tùy chọn `pdf-to-html-vi-layout` (kích hoạt khi yêu cầu bảo toàn thiết kế/layout) gồm quy trình tách pha tiết kiệm token ([`SKILL.md`](./.agents/skills/pdf-to-html-vi-layout/SKILL.md)), bộ quy chuẩn chuyên dịch ([`si_translation.md`](./.agents/skills/pdf-to-html-vi-layout/si_translation.md)) và bộ quy chuẩn thiết kế từng trang ([`si_layout.md`](./.agents/skills/pdf-to-html-vi-layout/si_layout.md)).
- [`CLAUDE.md`](./CLAUDE.md), [`.claude/`](./.claude/) và [`.agents/adapters/claude-code.md`](./.agents/adapters/claude-code.md) — Hỗ trợ Claude Code: `CLAUDE.md` nạp `AGENTS.md` cùng bộ chuyển đổi riêng; `.claude/skills/` chỉ là lối vào trỏ tới skill gốc trong `.agents/skills/` (không sao chép quy trình); `.claude/settings.json` cho phép sẵn đúng 3 lệnh công cụ.
- [`.agents/adapters/antigravity.md`](./.agents/adapters/antigravity.md) — Bộ chuyển đổi riêng cho Antigravity: gom mọi chi tiết phụ thuộc vào Antigravity (lấy PDF kéo-thả vào khung chat, tên tệp tạm, ánh xạ sang công cụ `read_file`...). `AGENTS.md` và các `SKILL.md` viết trung lập để có thể dùng với agent khác (Codex, Cursor...); khi Antigravity thay đổi cách vận hành, chỉ cần sửa tệp này.
- [`tools/`](./tools/) — Bộ công cụ thực thi portable (`extract_assets.exe`) cùng các script PowerShell bọc CLI mỏng:
  - [`extract_pdf_assets.ps1`](./tools/extract_pdf_assets.ps1) gọi `tools/extract_assets/extract_assets.exe` để phân giải tệp PDF (qua `-PdfPath` hoặc `-TranscriptPath`), tách ảnh/sơ đồ, xuất `manifest.json` và thu gọn tóm tắt trên stdout. Khung hình được tìm bằng mô hình bố cục Egret Medium (ONNX, chạy trên CPU, cắt được cả hình trên trang scan) đóng gói sẵn trong `extract_assets`; nếu mô hình không chạy được, bước tách ảnh dừng ngay và báo lỗi.
  - [`pdf_fallback_tools.ps1`](./tools/pdf_fallback_tools.ps1) gọi `tools/extract_assets/extract_assets.exe` (PyMuPDF) để render trang PDF thành ảnh và cắt khung ảnh theo JSON kèm auto-trim và kiểm tra giới hạn thư mục — chỉ dùng khi AI thấy một hình bị tách sót hoặc cắt sai, hoặc khi agent không đọc trực tiếp được PDF.
  - [`html_packager.ps1`](./tools/html_packager.ps1) chuyển tiếp sang `tools/extract_assets/extract_assets.exe` để tối ưu & nhúng ảnh Base64 trong bộ nhớ (không tạo ảnh tạm trên đĩa), bơm lớp vỏ đọc [`reader_shell.html`](./tools/reader_shell.html) (hoặc bỏ qua khi bật `-PreserveLayout`), kiểm định Auto-QA, tự động đánh số chống ghi đè (`_2`, `_3`...), xuất PDF và dọn sạch `work/`.
  - [`_path_guards.ps1`](./tools/_path_guards.ps1) — Tiện ích PowerShell kiểm tra an toàn đường dẫn và gọi `extract_assets.exe` (kèm phát hiện tệp đám mây offline).
  - [`src/`](./tools/src/) ([`extract_assets.py`](./tools/src/extract_assets.py), [`figure_detector/`](./tools/src/figure_detector/), [`image_ops.py`](./tools/src/image_ops.py), [`packager.py`](./tools/src/packager.py), [`reader_shell.py`](./tools/src/reader_shell.py), [`html_qa.py`](./tools/src/html_qa.py), [`pdf_export.py`](./tools/src/pdf_export.py), [`output_paths.py`](./tools/src/output_paths.py), [`transcript.py`](./tools/src/transcript.py), [`manifest.py`](./tools/src/manifest.py), [`path_guards.py`](./tools/src/path_guards.py)) & [`src/requirements-build.txt`](./tools/src/requirements-build.txt) — Mã nguồn Python gốc và danh sách gói ghim phiên bản dùng trên GitHub Actions (hoặc chạy [`build_extractor.ps1`](./tools/build_extractor.ps1) khi phát triển ở máy cá nhân) để đóng gói ra `extract_assets.exe` *(khi chạy dịch thuật, ứng dụng này tuyệt đối không gọi Python hệ thống)*. Bộ tìm hình bằng mô hình Egret nằm ở [`figure_detector/egret.py`](./tools/src/figure_detector/egret.py) (hậu xử lý theo Docling); tệp mô hình ONNX không có trong mã nguồn mà được tải từ bản phát hành [`model-egret-medium-v1`](https://github.com/kiencang/Max-Luka-Loop/releases/tag/model-egret-medium-v1) và đóng gói sẵn trong `tools/extract_assets/`.
- `input/` — Thư mục chứa tệp tin đầu vào, quan trọng khi file PDF hơn 10MB thì cần đặt vào đó, nếu không đến giới hạn ấy, người dùng có thể tải lên ngay từ khung chat mà không cần đặt vào thư mục input;
- `output/` — Thư mục chứa tệp đầu ra (`*_vi.html`/`*_vi.pdf` cho bản đọc mượt mặc định; `*_layout_vi.html`/`*_layout_vi.pdf` cho bản bảo toàn thiết kế; tự động thêm `_2`, `_3`... nếu dịch lại nhiều lần cùng một file), tự động được tạo khi đóng gói và được bỏ qua bởi [`.gitignore`](./.gitignore).
- [`dev/`](./dev/), [`tests/`](./tests/), [`.github/workflows/`](./.github/workflows/) — Chỉ dành cho phát triển, không có trong gói phát hành: hướng dẫn phát triển ([`dev/DEVELOPMENT.md`](./dev/DEVELOPMENT.md)), công cụ xuất/đánh giá mô hình Egret ([`dev/egret/`](./dev/egret/)) và đánh giá trên DocLayNet ([`dev/eval_doclaynet.py`](./dev/eval_doclaynet.py)), bộ kiểm thử Python/PowerShell, và hai workflow GitHub Actions (`ci.yml` chạy kiểm thử, `release.yml` đóng gói `max-luka-loop-win-x64.zip` khi đẩy tag `v*`).

## Tuyên bố từ chối trách nhiệm
Công cụ này có thể được sử dụng cho mục đích nghiên cứu và học tập cá nhân.

`Max Luka Loop` cũng như người phát triển nó không đưa ra bất kỳ bảo đảm rõ ràng hay ngụ ý nào, cũng như không tuyên bố rằng công cụ sẽ vận hành hoàn hảo, chính xác hoặc cập nhật. Người phát triển sẽ không chịu trách nhiệm cho bất kỳ tổn thất hay thiệt hại nào phát sinh trực tiếp hoặc gián tiếp liên quan đến hoặc phát sinh từ việc sử dụng công cụ này.

## Giấy phép & Thành phần Bên thứ ba (License & Third-Party Notices)

- **Mã nguồn gốc của `Max Luka Loop`:** Phần kịch bản điều phối Agent, Skill, script PowerShell, lớp vỏ [`tools/reader_shell.html`](./tools/reader_shell.html) và bộ mã nguồn tự viết trong [`tools/src/`](./tools/src/) ([`extract_assets.py`](./tools/src/extract_assets.py), [`figure_detector/`](./tools/src/figure_detector/), [`image_ops.py`](./tools/src/image_ops.py), [`packager.py`](./tools/src/packager.py), [`reader_shell.py`](./tools/src/reader_shell.py), [`html_qa.py`](./tools/src/html_qa.py), [`pdf_export.py`](./tools/src/pdf_export.py), [`output_paths.py`](./tools/src/output_paths.py), [`transcript.py`](./tools/src/transcript.py), [`manifest.py`](./tools/src/manifest.py), [`path_guards.py`](./tools/src/path_guards.py)) được cấp phép theo **MIT License** — xem chi tiết tại [`LICENSE`](./LICENSE).
- **Bộ công cụ thực thi dựng sẵn (`tools/extract_assets/`):** Bản đóng gói portable phân phối kèm trong gói phát hành Release (`max-luka-loop-win-x64.zip`, biên dịch tự động qua GitHub Actions từ [`tools/build_extractor.ps1`](./tools/build_extractor.ps1)) có tích hợp các thành phần phần mềm bên thứ ba và chịu sự điều chỉnh của giấy phép tương ứng từng thành phần:
  - **PyMuPDF / MuPDF:** Cấp phép theo **AGPL-3.0**; toàn bộ mã nguồn tương ứng của công cụ thực thi được công khai đầy đủ tại [`tools/src/`](./tools/src/).
  - **Python 3.12.7:** Cấp phép theo **PSF License v2**.
  - **OpenSSL 3.0.15 (`libcrypto-3.dll`):** Cấp phép theo **Apache License 2.0**.
  - **PyInstaller:** Bootloader theo **GPL-2.0-or-later** (kèm *Bootloader Exception*) và runtime hooks theo **Apache License 2.0**.
  - **Microsoft Visual C++ Runtime / Universal CRT:** Thuộc bản quyền của Microsoft Corporation.
  - **ONNX Runtime:** Cấp phép theo **MIT**. **NumPy** (kèm OpenBLAS): **BSD-3-Clause**.
  - **Mô hình bố cục docling-layout-egret-medium** (Docling Project, bản chuyển sang ONNX): Cấp phép theo **Apache-2.0**.
  - **Thuật toán hậu xử lý bố cục của Docling** (port lại trong [`tools/src/figure_detector/egret.py`](./tools/src/figure_detector/egret.py)): Cấp phép theo **MIT**, © The Docling Contributors.

Vui lòng xem đầy đủ thông báo bản quyền và toàn văn các giấy phép bên thứ ba tại [`THIRD_PARTY_LICENSES.md`](./THIRD_PARTY_LICENSES.md) và thư mục [`licenses/`](./licenses/).
