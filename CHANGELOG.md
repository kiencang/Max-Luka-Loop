# Changelog

Tất cả những thay đổi đáng chú ý của dự án **Max Luka Loop** sẽ được ghi lại trong file này.

## [1.1.5] - 2026-11-28
### Changed
- `AGENTS.md`: dấu hiệu nhận diện Antigravity thêm nhãn `Artifact Directory Path` (`appDataDir` ghi rõ là của bản cũ).
- Hai `SKILL.md`: cập nhật kích thước các tệp SI cần đọc trọn 1 lần cho khớp tệp thật (`si_academic_html.md` ~269 dòng / ~33 KB, `si_translation.md` ~131 dòng / ~20 KB, `si_layout.md` ~249 dòng / ~23 KB).

Port từ Luka-Loop v1.1.34 và v1.1.47 (chỉ tài liệu skill, không đổi mã).
- **Chế độ giữ thiết kế không bắt chước font của bản gốc** (`si_layout.md` Mục 2.1): kể cả khi PDF gốc dùng font có chân, chữ thư pháp hay font trang trí, mọi văn bản trong `work\draft.html` vẫn dùng `--font-sans` (Inter); không khai báo `font-family` nào khác ngoài `--font-sans` và `--font-mono`.
- **Hai skill dịch thống nhất cách dịch nhãn chữ trên ảnh giữ dạng PNG (Nhóm B):** trước đây chỉ sơ đồ dựng lại bằng HTML/CSS (Nhóm A) được dặn dịch nhãn, nên với ảnh PNG agent lúc bỏ qua nhãn, lúc dịch, lúc đặt chữ dịch đè lên ảnh (xô lệch). Nay cả hai skill:
  - cấm đặt chữ dịch chồng lên ảnh, ảnh giữ nguyên;
  - ghi các cặp nhãn **gốc → dịch** in nghiêng trong `<span class="fig-labels">` ở cuối `<figcaption>`, ngay sau chú thích; hình không có chú thích thì `<figcaption>` chỉ chứa dòng nhãn, ngay dưới ảnh;
  - không dịch số, đơn vị, ký hiệu, chữ đánh dấu hình con, tên riêng, chữ đã là tiếng Việt; không còn nhãn cần dịch thì không thêm dòng;
  - `pdf-to-html-vi`: `si_academic_html.md` Mục 4.3 ý 5, CSS `.fig-labels`, mục tự kiểm 2;
  - `pdf-to-html-vi-layout`: tag mới `[FIG-LABELS]` trong `work\translated.md` (`si_translation.md`), quy tắc dựng và CSS trong `si_layout.md`, danh sách tag trong `SKILL.md`.

## [1.1.4] - 2026-11-27
### Security
Port từ Luka-Loop v1.1.43 (mã đóng gói/QA của Max trước đó giống hệt Luka v1.1.42).
- Khóa cứng đuôi tệp đầu ra (`tools/src/output_paths.py`: `prepare_sanitized_output_path`, `assert_expected_output_extension`): `-OutHtmlPath` (và `-HtmlPath` khi ghi tại chỗ) bắt buộc có đuôi `.html`, `-OutPdfPath` bắt buộc có đuôi `.pdf` (không phân biệt hoa/thường; từ chối tên chỉ có đuôi, dấu chấm cuối hay ký tự lạ trong đuôi trước khi làm sạch tên). Chặn việc lợi dụng lệnh đóng gói đã được cấp quyền sẵn để ghi tệp thực thi (`.bat`, `.cmd`, `.ps1`, `.hta`, `.exe`...).
- Trần an toàn cho PDF quá lớn: `extract_images` (`tools/src/figure_detector/extract.py`, cả Egret lẫn heuristic) và `render_pages` (`tools/src/image_ops.py`) từ chối PDF quá `MAX_PDF_PAGES = 300` trang ngay khi mở tài liệu (trước khi chạy mô hình trên trang nào hay tạo thư mục), và dừng khi vượt `MAX_EXTRACTED_FIGURES = 1000` hình (dọn sạch ảnh PNG dở dang). Gọi từ Python có thể truyền `max_pages=0` / `max_figures=0` để bỏ giới hạn. Kết quả tách hình không đổi. Hai `SKILL.md` và `README.md` ghi rõ giới hạn và dặn agent dừng, hướng dẫn người dùng tách PDF.
- Gia cố kiểm tra LaTeX trong `tools/src/html_qa.py`:
  - đọc đối số `\href`, `\url`, `\style` theo ngoặc nhọn cân bằng `{...}`, coi `%` trong đối số là ký tự thường như MathJax (URL mã hóa phần trăm `a%20b` hợp lệ), và bắt buộc có đối số `{...}` ngay sau lệnh;
  - **cấm mọi định nghĩa macro LaTeX** (`\def`, `\edef`, `\gdef`, `\xdef`, `\newcommand`, `\renewcommand`, `\providecommand`, `\DeclareRobustCommand`, `\newenvironment`, `\renewenvironment`, `\let`, `\futurelet`, `\DeclarePairedDelimiter`/`X`/`XPP`) cùng các lệnh riêng của MathJax `\mmlToken`, `\bbox` (đóng khung dùng `\boxed{...}`) và `\require`, vì macro cho phép giấu đích liên kết khỏi bộ kiểm tra; bản dịch từ PDF không cần macro (thêm dòng dặn vào `si_academic_html.md` và `si_layout.md`);
  - coi `U+FEFF` là khoảng trắng như MathJax, và quét lại toàn bộ chữ của trang nối liền để bắt lệnh bị tách qua `<wbr>`, comment HTML hay thẻ lạc (`\hr<wbr>ef{...}`);
  - nhắc tên lệnh LaTeX trong câu văn (vd `\url`) phải đặt trong `<code>`.
- Lớp chặn lúc hiển thị cho liên kết trong công thức (`tools/src/mathjax_guard.py`): khi trang có MathJax, `embed_images_and_package` tự chèn ngay trước thẻ MathJax (cả chế độ thường lẫn `-PreserveLayout`) một script cấu hình cố định dùng `renderActions` của MathJax để gỡ mọi `href` không phải `http(s):`/`mailto:`/`#` sau khi công thức được dựng, ở cả trang HTML lẫn bản PDF. Auto-QA cho phép đúng script này (CSP tự thêm mã băm SHA-256) và khi đóng gói bắt buộc nó đứng trước thẻ MathJax. Không dùng `ui/safe` của MathJax vì nó để lọt `search-ms:`/`ms-settings:` (có dấu gạch ngang) và mặc định cho phép `file:`.

## [1.1.3] - 2026-11-25
### Changed
- Bộ chuyển đổi Antigravity (`.agents\adapters\antigravity.md`): cập nhật bộ công cụ chính sang `read_file` / `write_file` (ưu tiên `Append: true` khi ghi nối dần) / `edit_file` / `run_command` (giữ chú thích tương thích ngược `view_file` / `write_to_file` / `replace_file_content`), khớp giới hạn đọc `800` dòng / `45 KB` (`46.080` bytes), chỉnh lại ghi chú về `StartLine`/`EndLine` ở lần mở đầu, bổ sung mục đọc PDF trực tiếp từ đĩa (Trường hợp 2), gợi ý `Artifact Directory Path`, xử lý lỗi sandbox/quyền truy cập ngoài workspace và quy tắc không tạo Artifact / `scratch\` khi dịch.
- `AGENTS.md` và hai `SKILL.md`: bổ sung nhãn `App Data Directory` cùng `appDataDir` trong dấu hiệu nhận diện Antigravity và nhắc đọc `antigravity.md` cùng lượt mở `SKILL.md` (trước khi chạy lệnh Bước 1).

## [1.1.2] - 2026-11-22
### Changed
- Auto-QA (`html_qa.py`): tách hàm kiểm tra thẻ mở `_process_start_tag` (212 dòng, 108 nhánh) thành các hàm nhỏ theo việc: cấu trúc, `<script>`, `<img>`, `<table>`, thuộc tính, và từng nhóm đường dẫn (`<a>`, `<link>`, `<img>`, `<script>`, còn lại). Mã lấy từ Luka-Loop (bản 1.1.22), nơi `html_qa.py` trước khi tách giống hệt bản ở đây. Không đổi quy tắc nào: bản cũ và bản mới cho trạng thái và kết luận giống hệt nhau trên HTML trong repo và 30.000 tài liệu sinh ngẫu nhiên.

## [1.1.1] - 2026-11-22
### Fixed
- Chọn chế độ giữ thiết kế: `AGENTS.md` và hai `SKILL.md` nhận diện theo quy tắc ("giữ/giữ nguyên/bảo toàn" + "định dạng/format/bố cục/layout/thiết kế/trình bày") kèm ví dụ, thay cho danh sách 5 cụm từ cố định. Trước đây câu "Giữ định dạng" bị chuyển sang skill mặc định (bản một cột). Thêm ví dụ các yêu cầu về nội dung ("dịch sát nghĩa", "giữ hình ảnh/bảng biểu") không được nhầm thành chế độ giữ thiết kế.

## [1.1.0] - 2026-11-22
### Changed
- `caption`, `placement` và `context` trong `manifest.json` giờ lấy theo cách của Docling, không còn dùng quy tắc cũ (regex `Figure N`, `find_tables` của PyMuPDF, quy tắc thẳng hàng). Mọi vùng Egret tìm thấy đi qua hậu xử lý bố cục và thứ tự đọc của Docling (port trong `tools\src\figure_detector\docling_layout.py`). Chú thích là vùng `Caption` liền kề hình trong thứ tự đọc. Ảnh là `table_cell` khi không có chú thích và nằm ≥ 80% trong vùng bảng. Kiểm chứng bằng chính Docling: kết quả trùng hoàn toàn trên 943 trang DocLayNet test.
- Trên DocLayNet test: `placement` hết 4 lỗi gán nhầm `table_cell`; nhận thêm chú thích kiểu `FIG. 3:` mà cách cũ bỏ sót. Đổi lại, như Docling, mỗi chú thích chỉ thuộc về **một** ảnh: hình nhiều panel tách thành nhiều ảnh thì chỉ một ảnh mang `caption`, các ảnh còn lại `caption: null`. Hai `SKILL.md` hướng dẫn agent nhìn ảnh để đặt các panel chung một `<figure>`. Tổng cộng trên 352 hình, số chú thích đúng là 333 (cách cũ 337). Có 2 chú thích bị gán sai do thứ tự đọc và do Egret nhận nhầm một dòng công thức là chú thích; đây là hành vi của Docling, không vá riêng.
- `context` của ảnh trong ô bảng tách các ô cùng hàng bằng ` | `.

### Added
- `dev\egret\verify_docling_port.py`: chạy Docling gốc (`docling-slim`) và bản port trên cùng đầu ra của Egret, báo trang nào khác nhau.
- `licenses\docling-core-MIT.txt` và mục 10 trong `THIRD_PARTY_LICENSES.md` cho phần port từ `docling-core`.

## [1.0.4] - 2026-11-22
### Changed
- Skill giữ bố cục: quy tắc thứ tự hình viết tổng quát hơn. Agent xếp hình đúng thứ tự như bản gốc (không chỉ theo cột), xác định vị trí bằng `page` + `box` trong `manifest.json` và quan sát trang gốc, đối chiếu nhãn/số in trên hình nếu có; chỉ cần biết số `Y` trong tên tệp `fig_pX_Y` không phải căn cứ thứ tự (`X` là số trang vật lý trong tệp PDF).

## [1.0.3] - 2026-11-22
### Fixed
- Skill giữ bố cục (`si_layout.md`, `si_translation.md`): agent phải giữ đúng thứ tự trên–dưới của hình trong từng cột theo `y0` và đối chiếu nhãn/số in trên hình (①, ②…), không suy thứ tự từ tên tệp `fig_pX_Y` (số chạy so le giữa các cột). Trước đây hai hình bước 6 và 7 ở cột phải có thể bị đảo chỗ.

## [1.0.2] - 2026-11-22
### Changed
- Ảnh hình được cắt sát đúng khung mà mô hình Egret tìm ra, không còn thêm lề 4 pt mỗi cạnh, đúng như cách Docling cắt ảnh. Trên DocLayNet test, ảnh lẹm ít chữ thân bài hơn mà không làm mất nội dung hình nào.
- Claude Code: PDF tới 10 trang được đọc bằng một lệnh `Read` không kèm tham số `pages`. Trước đây agent đôi khi tự thêm `pages: "1-5"`, gặp lỗi `pdftoppm is not installed` rồi phải render trang thành ảnh, mất lớp chữ chính xác của PDF.
- Hai `SKILL.md` mô tả đúng cách tách ảnh hiện tại: cắt sát khung, và hình nhiều panel có thể ra thành nhiều ảnh cùng một `caption`, cần đặt chung một chú thích (thay cho mô tả cũ "nới lề 4 pt", "gộp cụm hình theo chú thích" của bộ tách ảnh trước).

## [1.0.1] - 2026-11-22
### Fixed
- Lệnh ngay cho Claude dùng `RenderPages` để đọc các file PDF trên 10 trang (tránh việc tự tìm cách cài đặt các công cụ khác để xử lý);

## [1.0.0] - 2026-11-22
Bản phát hành đầu tiên của **Max Luka Loop** (`max-luka-loop`), dựng lại từ mã nguồn [Luka-Loop](https://github.com/kiencang/Luka-Loop) v1.1.17 (cùng tác giả). Lịch sử thay đổi trước đó xem tại dự án gốc.

### Added
- Tách ảnh bằng mô hình bố cục **Egret Medium** (docling-layout-egret-medium, Apache-2.0) chạy qua ONNX trên CPU. Mô hình chỉ thay khâu tìm khung hình (Pha 2–5); khung được hậu xử lý đúng như `LayoutPostprocessor` của Docling (ngưỡng theo nhãn, bỏ hình phủ > 90% trang, gom khung chồng nhau, bảng thắng hình trùng khung). PyMuPDF vẫn render trang, đọc chữ để ghép chú thích và cắt PNG, nên `manifest.json` giữ nguyên định dạng (thêm trường `"detector": "egret"`). Trên DocLayNet test (943 trang khoa học): 11 trang có lỗi nặng, so với 44 của bộ quy tắc cũ. Điểm mạnh chính: cắt được hình trên trang scan, nơi bộ tìm hình cũ chỉ báo `scanned_pages` để agent cắt tay; trang đã cắt được hình không còn nằm trong `scanned_pages`.
- Mô hình ONNX chỉ dùng float32 (position embedding của encoder được xuất thành hằng), nên chạy được trên cả các bản onnxruntime thiếu `Sin`/`Cos` cho float64 (vd 1.26).
- `dev\egret\export_onnx.py` (xuất ONNX và đối chiếu với PyTorch), `dev\egret\compare_detectors.py` (so sánh với bộ quy tắc cũ, kèm trang ảnh cắt cạnh nhau), `tests\test_egret_detector.py`.

### Changed
- `extract_pdf_assets.ps1` / `extract_assets.exe --mode extract` **chỉ dùng Egret**, không có tham số chọn bộ tìm hình và không có đường lùi: thiếu mô hình, onnxruntime hỏng hoặc mô hình lỗi khi chạy thì dừng ngay với `ERROR: …` (exit code 1) và không ghi ảnh hay manifest nào. Bộ quy tắc hình học cũ chỉ còn gọi được từ mã Python (`extract_images(detector="heuristic")`) cho test hồi quy và công cụ đánh giá trong `dev\`.
- Hai `SKILL.md`: `scanned_pages` nay chỉ là thông tin (trang scan không tìm thấy hình, thường chỉ có chữ), không còn là tín hiệu chạy fallback. Agent chỉ dùng `RenderPages` + `CropFromJson` khi tự thấy, lúc đối chiếu trang PDF với ảnh đã tách, một hình Nhóm B bị tách sót hoặc cắt sai. Khi bước tách ảnh báo `ERROR`, agent báo lỗi cho người dùng thay vì tự cắt hình thay thế.
- Đổi thương hiệu sang **Max Luka Loop**: gói phát hành `max-luka-loop-win-x64.zip`, thư mục `max-luka-loop`; thuộc tính CSP `data-max-luka-csp`, dấu ghi nối `<!-- MAX-LUKA-CONTINUE -->`, khóa `localStorage` `max-luka-loop-theme` / `max-luka-loop-max-width` (thiết lập giao diện đọc đã lưu của bản cũ không được mang sang), tiền tố thư mục tạm `max_luka_*`, biến môi trường `MAX_LUKA_UPDATE_GOLDEN`.
- `build_extractor.ps1` đóng gói thêm onnxruntime, numpy và `tools\models\egret_medium.onnx` (vào `_internal\models\`), có `-RequireEgretModel` để CI/phát hành dừng khi thiếu mô hình; gói `extract_assets` tăng từ ~61 MB lên ~217 MB. `requirements-build.txt` ghim thêm `onnxruntime==1.32.0`, `numpy==2.5.5` và ghim cả các gói phụ thuộc gián tiếp (`pyinstaller-hooks-contrib`, `altgraph`, `pefile`, `pywin32-ctypes`, `packaging`, `setuptools`, `flatbuffers`, `protobuf`) để cùng một mã nguồn luôn build ra cùng một gói.
- CI và phát hành: mô hình ONNX lấy từ release `model-egret-medium-v1` qua `dev\egret\fetch_model.ps1` (kiểm tra SHA-256); gói phát hành đổi tên thành `max-luka-loop-win-x64.zip` và được kiểm tra có chứa mô hình.
- `THIRD_PARTY_LICENSES.md` và `licenses\` bổ sung giấy phép ONNX Runtime (MIT), NumPy/OpenBLAS (BSD-3-Clause), mô hình Egret (Apache-2.0, kèm mô tả thay đổi khi chuyển sang ONNX) và thuật toán hậu xử lý bố cục port từ Docling (MIT, `licenses\docling-MIT.txt`).
