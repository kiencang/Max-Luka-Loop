# Changelog

Tất cả những thay đổi đáng chú ý của dự án **Max Luka Loop** sẽ được ghi lại trong file này.

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
