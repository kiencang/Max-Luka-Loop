# Hướng dẫn phát triển Max Luka Loop

Tệp này dành cho người và AI agent khi **phát triển, sửa lỗi hoặc kiểm thử chính công cụ**. Khi dịch tài liệu, làm theo `AGENTS.md` và `SKILL.md`, không làm theo tệp này. Ở chế độ phát triển được phép đọc mã nguồn `tools\` và dùng Python hệ thống để build/test.

## Môi trường

- Windows 10/11 x64, Windows PowerShell 5.1 (có sẵn) và nên có PowerShell 7 (`pwsh`) để chạy test trên cả hai phiên bản như CI.
- Python **3.12.7** (khớp CI) và các gói ghim phiên bản: `python -m pip install -r tools\src\requirements-build.txt` (PyMuPDF, PyInstaller).
- Microsoft Edge hoặc Google Chrome để chạy các test xuất PDF thật.

## Cấu trúc mã

- `tools\src\` — mã nguồn Python của `extract_assets.exe`:
  - `extract_assets.py`: điểm vào CLI, phân luồng theo `--mode` (`extract`, `render-pages`, `crop-json`, `embed-images`, `html-to-pdf`).
  - `figure_detector\` (package): tách hình/sơ đồ theo bố cục (pipeline 6 pha, ngưỡng gom trong `DetectorConfig`). Phân tầng — mỗi module chỉ import từ module đứng trước: `model` (proxy `pymupdf` nạp trễ, `DetectorConfig`, regex chú thích, dataclass) → `geometry` → `text` (Pha 1) → `caption_match` (khớp chú thích, dùng chung cho Pha 2–6) → `raster` (Pha 2) → `vector` (Pha 3) → `captions` (Pha 4) → `merge` (Pha 5) → `pipeline` (chạy Pha 1–5 cho một trang) → `docling_layout` (port hậu xử lý bố cục, thứ tự đọc, ghép chú thích của Docling) → `egret` (thay Pha 2–5 bằng mô hình ONNX, xem mục **Bộ tìm hình Egret**) → `extract` (Pha 6, `extract_images`, tham số `detector`). `__init__.py` giữ nguyên các tên công khai cũ.
    - **Quy tắc phân loại cụm vector (Pha 3, `vector.py`):** `_evaluate_vector_cluster` áp lần lượt các quy tắc trong `_VECTOR_CLUSTER_RULES`; quy tắc đầu tiên trả về `FilterDecision` thắng, không quy tắc nào loại thì giữ cụm. Mỗi quy tắc là một hàm `_reject_<lý_do>(f)` nhận `_ClusterFeatures` (các đặc trưng tính lười bằng `cached_property`, nên phần nặng như `get_text`/`find_tables` chỉ chạy khi có quy tắc cần) và tự nêu đủ điều kiện của mình (kể cả "không có raster", "không có chú thích hình"). Thêm quy tắc mới: viết hàm `_reject_...`, chèn vào đúng vị trí trong `_VECTOR_CLUSTER_RULES` (thứ tự quyết định lý do thắng), cập nhật `test_rule_order_is_unchanged` và thêm ca thử trong `tests\test_vector_rules.py`; nếu kết quả tách hình đổi có chủ đích, sinh lại golden và xem kỹ diff.
  - `image_ops.py`: render trang, cắt ảnh theo JSON, tối ưu ảnh, cùng các trần an toàn (`MAX_PDF_PAGES = 300`, `MAX_EXTRACTED_FIGURES = 1000`; gọi từ Python có thể truyền `max_pages=0, max_figures=0` vào `extract_images` / `render_pages` để bỏ giới hạn khi thử tài liệu dày).
  - Bước 4 (đóng gói), tách theo trách nhiệm — `packager.py` → `reader_shell.py`, `html_qa.py`, `pdf_export.py`, `output_paths.py` (không có vòng phụ thuộc):
    - `packager.py`: điểm vào `embed-images` — nhúng ảnh Base64 rồi điều phối các module dưới.
    - `reader_shell.py`: gắn `tools\reader_shell.html` (CSS, thanh công cụ, script), lấy script tin cậy, tiêm CSP.
    - `html_qa.py`: Auto-QA — bộ quét DOM & bảo mật một lượt (`_QADOMScanner`, `run_html_qa_check`).
    - `mathjax_guard.py`: script cấu hình MathJax cố định (bước `renderActions`) gỡ mọi liên kết không phải `http(s):`/`mailto:`/`#` sau khi dựng công thức; `packager.py` chèn ngay trước thẻ MathJax, `html_qa.py` cho phép đúng nội dung này.
    - `pdf_export.py`: điểm vào `html-to-pdf` — xuất PDF bằng Edge/Chrome headless cô lập.
    - `output_paths.py`: làm sạch tên tệp đầu ra, đánh số `_2`/`_3`, dọn `work\` sau khi đã có đầu ra.
  - `transcript.py`: tìm PDF đính kèm mới nhất trong `transcript.jsonl` (Antigravity `-TranscriptPath`).
  - `manifest.py`: in bản rút gọn `manifest.json` ra stdout (chỉ dùng thư viện chuẩn, không import module nào khác của dự án — bộ tách hình không phụ thuộc bộ đóng gói).
  - `path_guards.py`: kiểm tra an toàn đường dẫn (UNC, NTFS ADS, symlink/junction, tên thiết bị Windows), dọn `work\` an toàn.
- `tools\*.ps1` — wrapper PowerShell mỏng chuyển tiếp tham số vào exe; `tools\_path_guards.ps1` là tiện ích dùng chung.
- `tools\extract_assets\` — kết quả build (không đưa vào git; gói phát hành do CI build).
- Chỉ dẫn cho agent: `AGENTS.md`, `CLAUDE.md`, `.agents\skills\` (quy trình + SI dịch), `.agents\adapters\` (chi tiết riêng từng môi trường agent), `.claude\` (lối vào và quyền cho Claude Code).

## Build và test

```powershell
.\tools\build_extractor.ps1                 # build lại tools\extract_assets\extract_assets.exe
.\tests\run_tests.ps1 -IncludePython        # test PowerShell 5.1 + toàn bộ test Python
pwsh -NoProfile -File .\tests\run_tests.ps1 # test PowerShell 7
```

- **Build lại exe sau mọi thay đổi trong `tools\src\`** trước khi chạy test PowerShell: các wrapper và test PowerShell gọi exe, không gọi mã Python.
- Chạy nhanh riêng test Python: `$env:PYTHONUTF8='1'; python -m unittest discover -s tests -p "test_*.py"`.
- Các tệp test chỉ cần thư viện chuẩn (không cần PyMuPDF/Edge): `test_skill_contracts.py`, `test_pdf_export_resilience.py`, `test_clean_dir_scope.py`, `test_cli.py`, `test_eval_doclaynet.py`, `test_ab_judge.py`.
- Test chỉ ghi vào thư mục tạm của hệ thống, không ghi vào `work\` hay `output\` của dự án.
- CI (`.github\workflows\ci.yml`) chạy khi đổi `tools/**`, `.agents/**`, `AGENTS.md` hoặc chính `ci.yml`. Chỉ sửa test (`tests/**`) hay công cụ phát triển (`dev/**`) thì không kích hoạt CI: hãy chạy test ở máy, hoặc bấm **Run workflow** trong tab Actions. Quy trình phát hành (`release.yml`) chạy khi đẩy tag `v*` và luôn chạy lại toàn bộ test trước khi đóng gói.

## Bộ tìm hình Egret (ONNX, mặc định)

CLI và `extract_pdf_assets.ps1` **chỉ dùng Egret**: không có tham số chọn bộ tìm hình, không có đường lùi. Mô hình thiếu, onnxruntime hỏng hay lỗi khi chạy đều dừng bước tách ảnh với `ERROR: …` trước khi ghi bất kỳ tệp nào, để người dùng biết ngay. `extract_images(detector=...)` mặc định `"egret"`; giá trị `"heuristic"` (bộ quy tắc cũ) chỉ dùng trong Python: test hồi quy (`test_extract_assets.py`, golden) và `eval_doclaynet.py` ghi rõ nó, còn `test_powershell.ps1` chạy wrapper nên kiểm tra kết quả của Egret.

Egret thay khâu tìm khung hình (Pha 2–5) bằng mô hình bố cục **docling-layout-egret-medium** (D-FINE, 19,5M tham số, Apache-2.0) chạy qua onnxruntime trong `tools\src\figure_detector\egret.py`. Mọi thông tin về hình trong manifest (`caption`, `placement`, `context`) cũng lấy theo Docling (`docling_layout.py`), không dùng các quy tắc của bộ heuristic (`analyze_page`, `link_captions`, `find_tables`). PyMuPDF chỉ còn render trang, cấp dòng chữ của PDF, đếm ảnh/nét vẽ cho `source` và cắt PNG (Pha 6).

- **Xuất mô hình** (cần venv riêng có `torch` bản CPU, `transformers`, `onnx`, `onnxscript`, `onnxruntime`, `PyMuPDF`, `numpy`, `Pillow`; đặt venv ở đường dẫn ngắn như `%TEMP%\egv` vì gói torch có tên tệp rất dài, vượt giới hạn 260 ký tự nếu Windows chưa bật Long Path):

  ```powershell
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File dev\egret\fetch_model.ps1   # lấy mô hình đã phát hành (không cần torch)
  python -X utf8 dev\egret\export_onnx.py --out tools\models\egret_medium.onnx --check tests\layout_samples   # hoặc tự xuất lại
  python -X utf8 dev\egret\verify_onnx_weights.py   # chỉ cần numpy + onnx: tệp ONNX chứa đúng trọng số gốc đã ghim
  python -X utf8 dev\egret\compare_detectors.py    # so sánh với bộ tìm hình heuristic, mở gallery.html để xem
  python -X utf8 dev\egret\verify_docling_port.py dump --doclaynet-test --out %TEMP%\ro_inputs.jsonl   # venv có Egret
  python -X utf8 dev\egret\verify_docling_port.py compare %TEMP%\ro_inputs.jsonl   # venv có docling-slim: port phải trùng Docling
  .\tools\build_extractor.ps1 -PythonExe <python của venv>
  ```

  `--check` đối chiếu đầu ra ONNX với PyTorch và bước hậu xử lý numpy với `RTDetrImageProcessor` (phải trùng khớp), đồng thời đo thời gian. `tools\models\` là kết quả build, không đưa vào git (78 MB).
- **Chỉ float32:** transformers tính position embedding sin/cos của encoder bằng float64. Một số bản onnxruntime (vd 1.26) không có `Sin`/`Cos` cho double và từ chối nạp mô hình. Vì đầu vào cố định 640×640, script ghi lại embedding sau một lần chạy rồi xuất nó thành hằng float32, và báo lỗi nếu đồ thị còn nút float64. `tests\test_egret_detector.py` nên được chạy trên cả hai phiên bản onnxruntime.
- **Đầu vào:** render trang với cạnh dài 1280 px rồi để MuPDF thu về 640×640. Cách này cho khung `Picture` trùng đường tham chiếu (render rồi resize bằng processor của HF) trên 20/20 trang mẫu; render thẳng ra 640×640 chỉ trùng 16/20. Đã thử lượng tử hóa int8 động: chậm hơn ~9 lần trên CPU và lệch kết quả, nên giữ fp32.
- **Hậu xử lý = Docling, không tự chế** (`docling_layout.postprocess_layout`): bản port `LayoutPostprocessor` trong `docling/utils/layout_postprocessor.py` (docling-slim 2.151.1, MIT). Mọi hằng số ở đầu `docling_layout.py` lấy nguyên từ đó và phải giữ đồng bộ với upstream, không chỉnh theo ý mình: lọc thô 0,3; ngưỡng theo nhãn (`Picture`/`Table`/`Caption` 0,5, so sánh `>=`); bỏ hình phủ > 90% trang; gom khung chồng nhau (IoU > 0,8 hoặc nằm > 80% trong nhau) và giữ một khung mỗi nhóm (khung lớn hơn thắng trừ khi điểm thấp hơn > 0,3); hình trùng bảng (IoU > 0,8) thua trừ khi điểm cao hơn ≥ 0,1; sắp thứ tự trên-xuống, trái-sang-phải. Khung **không** được nới, cắt hay gộp thêm. Ảnh PNG cũng được **cắt sát đúng khung, không thêm lề** như Docling (`standard_pdf_pipeline.py`: `page.image.crop(bbox)`); lề 4 pt cũ chỉ còn cho bộ heuristic (`CROP_PAD_PT` trong `extract.py`), để ảnh mẫu golden của nó không đổi. Khác Docling có chủ ý: ảnh cắt ở 180 DPI (`-Dpi`, Docling mặc định 72) để chữ trong hình đủ nét khi dịch. Hệ quả đã biết (giống Docling): hình nhiều panel mà khung bao trọn < 0,5 sẽ ra từng panel riêng; ảnh trong ô bảng bị mất nếu mô hình gắn cả bảng là `Picture`.
- **Kết quả trên DocLayNet test** (943 trang khoa học, 359 hình; Egret không huấn luyện trên tập này, còn bộ heuristic từng được tinh chỉnh trên nó): trang có lỗi nặng 14 (heuristic 44), hình sót 15 (6), hình cắt thiếu nặng 4 (29), ảnh lẹm chữ 5 (24), F1 0,956 (0,921). Công cụ chấm theo đúng lề của từng bộ (`RENDER_PAD` = `CROP_PAD_PT`). Khi còn lề 4 pt, Egret có 11 trang lỗi nặng; 3 trang chênh lệch đã được xem tận mắt: ảnh cắt sát vẫn chứa trọn hình và nhãn trục, chỉ có khung gán nhãn DocLayNet rộng hơn ở phần lề trắng nên tỷ lệ phủ diện tích tụt dưới 90%. Số ô chữ bị cắt không đổi (2), số ô chữ lẹm vào ảnh giảm (78 xuống 72). Hai phiên bản hậu xử lý tự chế trước đó (ngưỡng 0,45, nới khung lấy nhãn trục, cắt chú thích, lọc tiêu đề trang) cho 22 rồi 14 trang lỗi nặng. Lỗi sót còn lại chủ yếu là giản đồ Feynman nằm trong công thức (mô hình gắn nhãn `Formula`).
- **Tốc độ:** ~0,8 s/trang trên CPU laptop 4 nhân (i7-8550U), vượt giới hạn trung bình 0,5 s/trang ở mục dưới. Bộ heuristic ~0,13 s/trang. Bài báo của nhóm Docling báo 0,33 s/ảnh trên AMD EPYC 7763 (4 luồng).
- **Chú thích, `placement`, `context` = Docling** (`docling_layout.py`, port từ docling-slim 2.151.1 và docling-core 2.108.0, MIT): mọi vùng Egret (không riêng `Picture`) đi qua `LayoutPostprocessor` đầy đủ — gán dòng chữ PDF vào vùng, dòng chữ không thuộc vùng nào thành vùng `Text` riêng, co khung theo chữ — rồi qua thứ tự đọc theo luật (`ReadingOrderPredictor`, không dùng đường kẻ trang như mặc định của Docling). Một vùng `Caption` chỉ với tới dãy hình/bảng/code liền kề nó trong thứ tự đọc và chỉ thuộc về **một** hình (ghép theo đường tăng, giống Docling); chữ chú thích nối dòng như `PageAssembleModel.sanitize_text`. `placement = "table_cell"` khi ảnh không có chú thích/footnote và nằm ≥ 80% trong vùng `Table` (cổng đầu của `_match_table_pictures`; Docling còn tìm ô bằng TableFormer, ở đây không có), lúc đó `context` là chữ cùng hàng trong bảng; ảnh không chú thích khác lấy `context` từ đoạn chữ liền trước/sau trong thứ tự đọc. Khác Docling: chữ lấy từ dòng PyMuPDF (Docling dùng docling-parse) và không có OCR, nên trang scan không có chú thích. `verify_docling_port.py` chạy chính Docling trên cùng đầu vào: 943/943 trang DocLayNet test và 20/20 trang mẫu trùng hoàn toàn (vùng, thứ tự đọc, liên kết, chữ); port tốn ~9 ms/trang.
- **Kết quả chú thích/placement trên DocLayNet test** (352 hình, so với regex `Figure N` + `find_tables` cũ trên cùng khung): 329 hình cùng chú thích; mới bắt thêm 4 chú thích kiểu `FIG. 3:` mà quy tắc cũ bỏ sót; mất 6 (2 hình nhiều panel — chỉ một panel nhận chú thích; 2 nhãn trục như `r`, `ex` thò ra ngoài khung hình thành vùng `Text` chen giữa hình và chú thích; 1 chú thích xoay dọc; 1 do thứ tự đọc); gán sai 2 (thứ tự đọc đẩy chú thích sang hình bên dưới; Egret gắn nhãn `Caption` cho một dòng công thức). `placement` đúng 352/352 (cách cũ gán nhầm 4 hình là `table_cell`: 2 do `find_tables` nhận đồ thị là bảng, 2 do quy tắc thẳng hàng bắt nhầm ma trận); ảnh trong ô bảng ở `tests\layout_samples` vẫn giữ `table_cell`. Các lỗi còn lại là hành vi của Docling, không vá cục bộ.
- **Nguồn trọng số được ghim:** `export_onnx.py` chỉ xuất từ commit `MODEL_REVISION` (`77ede7cc…`) của repo Hugging Face và từ chối nếu `model.safetensors` khác `MODEL_SAFETENSORS_SHA256` (`e7fc5b9a…`); hai hằng này khai báo một lần trong `verify_onnx_weights.py`. `verify_onnx_weights.py` tải đúng tệp đó (hoặc nhận `--safetensors`) và tìm từng tensor trong tệp ONNX: giống từng byte (hoặc chuyển vị), hoặc tính lại phép gộp Conv + BatchNorm và hằng `scale`/`shift` của BatchNorm cố định ở backbone (sai lệch ≤ 1e-5, thực tế 1,6e-7); chỉ bỏ qua các tensor chỉ dùng khi huấn luyện. Tệp ONNX hiện tại: 314 tensor trùng byte, 67 chuyển vị, 73 cặp Conv + BatchNorm gộp, 60 BatchNorm cố định, 19 tensor huấn luyện, 4 vô hướng gộp vào hằng khác. Đổi sang trọng số mới: sửa hai hằng, xuất lại, chạy `verify_onnx_weights.py`, rồi phát hành như mục dưới.
- **Mô hình trong CI và bản phát hành:** `tools\models\` không có trong git. Tệp ONNX được đưa lên **một lần** thành tệp đính kèm của GitHub release `model-egret-medium-v1`; `dev\egret\fetch_model.ps1` tải về `tools\models\` và từ chối nếu SHA-256 khác giá trị ghim trong script. `ci.yml` và `release.yml` chạy script này rồi `build_extractor.ps1 -RequireEgretModel` (thiếu mô hình là dừng). Đổi mô hình: xuất bằng `export_onnx.py`, tạo release `model-…` mới chứa tệp, rồi sửa `$Url`/`$Sha256` trong `fetch_model.ps1` trong cùng commit. Gói zip không chứa `tools\models\` (mô hình đã nằm trong `tools\extract_assets\_internal\models\`).
- **Lưu ý khi đánh giá trên DocLayNet:** Egret được huấn luyện trên DocLayNet, mà tập `tune`/`holdout` của `eval_doclaynet.py` đều lấy từ tập train của DocLayNet, nên kết quả trên hai tập này thiên vị cho Egret. Hãy đo trên PDF ngoài DocLayNet và chấm mù A/B.

## Đánh giá bộ tách hình trên DocLayNet

`dev\eval_doclaynet.py` chạy chính mã `figure_detector` (giống trong exe) trên PDF gốc nhúng trong **DocLayNet v1.2** (bản parquet trên Hugging Face, có cột `pdf`) và so với hộp `Picture` do người gán nhãn — chỉ lấy `doc_category = scientific_articles`. Cần Python hệ thống có thêm `pyarrow`; bộ dữ liệu (~37 GB) để ngoài repo, truyền đường dẫn qua `--data`.

```powershell
python -X utf8 dev\eval_doclaynet.py --data D:\PdfSamples --subset tune                       # đo trên tập hiệu chỉnh
python -X utf8 dev\eval_doclaynet.py --data D:\PdfSamples --subset tune --gallery 8              # + trang minh họa lỗi nặng
python -X utf8 dev\eval_doclaynet.py --data D:\PdfSamples --subset tune --limit 500 --overlays 20  # mẫu nhỏ + ảnh chồng trang lỗi
python -X utf8 dev\eval_doclaynet.py --data D:\PdfSamples --subset tune --disable-rule _reject_too_small  # đo đóng góp một quy tắc
```

- **Các tập:** `tune` = train trừ hold-out (xem lỗi, chỉnh quy tắc ở đây); `holdout` = ~20% **tài liệu** của train, chọn bằng hash cố định trong script — chỉ để đo, công cụ cấm `--overlays` trên tập này; `val`/`test` = bộ mà bộ phát hiện từng được hiệu chỉnh trước đây (không còn là thước đo khách quan).
- **Tọa độ:** hộp DocLayNet là `[x, y, w, h]` trên ảnh 1025×1025 bị kéo giãn → quy đổi riêng từng trục về kích thước trang thật.
- **Chỉ số chính — mức độ nghiêm trọng với bản dịch** (`severity`, không phụ thuộc cách gộp/tách panel; ảnh được xét đúng như khi xuất, tức với lề `RENDER_PAD` của bộ đang đo: 4 pt cho heuristic, 0 cho Egret):
  - *Hình bị cắt thiếu* (`clipped`): chữ thuộc hình (nhãn trục, số chia, chú giải — lấy từ `pdf_cells` của hộp `Picture`) nằm ngoài mọi ảnh đã tách **và có mực thật ở đó** (render kiểm tra, vì `pdf_cells` đôi khi nằm trên chữ ẩn), hoặc > 10% diện tích hình bị cắt. Chia mức: `major` (≥ 3 ô chữ hoặc cắt diện tích) và `minor` (1–2 ô chữ, thường là nhãn panel); `minor` không tính là lỗi nặng. *Bỏ sót* (`missed`): phủ < 50%.
  - *Ảnh lấn chữ* (`intrusion`): ô chữ của nội dung được gán nhãn ngoài hình (Caption, Text, Formula, Table, Page-header…) lọt vào ảnh; *gộp lệch* (`bad_merge`): một ảnh bao nhiều hình **và** lấn chữ. Ảnh bao nhiều hình mà không lấn chữ là `merge_ok` — chấp nhận được.
- **Chỉ số phụ — khớp theo quy ước DocLayNet** (`matching`): khớp một-một; `strict` = IoU ≥ 0,5; `lenient` thêm trường hợp hộp phủ ≥ 90% hộp nhãn và không lớn quá 2 lần. Hộp không khớp được phân loại `missed`/`partial`/`split`/`merged`, `merge`/`fragment`/`fp_<lớp>`/`fp_unlabeled`. DocLayNet vẽ một `Picture` cho mỗi chú thích ở ~99% trường hợp, nên split/merge chủ yếu phản ánh cách gom panel — ít ảnh hưởng tới bản dịch.
- **Nhiễu nhãn:** DocLayNet có trang thiếu hoặc lệch nhãn; xem ảnh minh họa trước khi coi một nhóm lỗi là thật.
- **Đầu ra:** mặc định trong `%TEMP%\max_luka_doclaynet_eval\` — kết quả bộ phát hiện từng trang lưu đệm theo dấu vân tay mã nguồn (`pages\<fingerprint>.jsonl`, đổi mã là tự chạy lại); nhãn lưu đệm riêng (`ground_truth_v1.jsonl`) và việc chấm điểm luôn tính lại, nên đổi cách chấm không phải chạy lại bộ phát hiện. Mỗi lần chạy có `runs\<tên>\summary.json`, `worst_pages.json`, `overlays\` (`--overlays N`) và `gallery.html` (`--gallery N`: N ví dụ mỗi loại lỗi nặng, ảnh cắt sát vùng hình; chấm cam = chữ lọt vào ảnh, chấm xanh dương = chữ của hình bị cắt; kèm **ảnh xuất ra thực tế** để đối chiếu — ảnh chồng dễ gây hiểu lầm vì chữ bị cắt thường nằm sát ngay ngoài đường viền).
- **Quy trình cải tiến:** chọn một nhóm lỗi nặng trên `tune` → sửa/thêm quy tắc → đo lại `tune` → kiểm tra `holdout` không tụt → chạy test, sinh lại golden nếu kết quả mẫu đổi có chủ đích và xem kỹ diff → **chấm mù trái/phải** (mục dưới) trước khi commit.
- **Giới hạn tốc độ:** ưu tiên chất lượng hơn tốc độ. Một thay đổi được chậm hơn nếu cho kết quả tốt hơn, miễn là bộ tách hình (đo bằng cột `seconds` của `pages\<fp>.jsonl`) vẫn nằm trong ba giới hạn:
  - trung bình ≤ 0,5 s/trang;
  - 99% số trang dưới 10 s;
  - không trang nào được phép chạy quá 30 s: quá ngưỡng thì bỏ các bước phân tích nặng và giữ kết quả đơn giản đã có.

  Mốc đo trên Luka-Loop gốc v1.1.14: trung bình 0,43 s, 99% dưới 5,4 s, trang chậm nhất 178 s. Riêng giới hạn 30 s/trang hiện **chưa được thực thi**.

### Chấm mù trái/phải (A/B)

Chỉ số DocLayNet có thể đánh lừa: chẳng hạn `pdf_cells` nằm trên chữ ẩn, hay ảnh chồng che mất chữ bị cắt. Vì vậy mỗi thay đổi bộ tách hình còn được chấm bằng mắt. `dev\ab_judge.py` lấy các hình mà hai bản cho ảnh xuất ra khác nhau, xuất ảnh với lề `RENDER_PAD` (mặc định 4 pt, đúng với bộ heuristic) và xáo ngẫu nhiên bên trái/phải. Kết quả là một trang HTML cục bộ. Người chấm chọn Trái/Phải/Như nhau/Cả hai tệ, rồi dán lại mã dạng `AB5:LREX…`.

```powershell
python -X utf8 dev\eval_doclaynet.py --data D:\PdfSamples --subset tune      # chạy cho cả bản cũ lẫn bản mới để có pages\<fp>.jsonl
python -X utf8 dev\ab_judge.py build --old <fp_cũ> --new <fp_mới> --n 50 --seed 5 --code AB5
python -X utf8 dev\ab_judge.py score AB5:LREX...
```

- Trang và khóa nằm ở `%TEMP%\max_luka_doclaynet_eval\ab\`. Chỉ lấy trang `tune`, **không bao giờ** lấy `holdout`. Trang chứa ảnh cắt từ bài báo của bên thứ ba, nên không đăng công khai.
- `score` giải mã bằng khóa, in số thắng/thua kèm sign test và khoảng tin cậy Wilson, liệt kê các hình "cũ tốt hơn"/"cả hai tệ" để xem lại. Lệnh cũng lưu đợt chấm (không kèm ảnh) vào `dev\ab_history\`. Đợt sau tự bỏ qua các tài liệu đã chấm (`--allow-repeat-docs` để tắt).
- Xem từng ca thua trước khi kết luận. Mỗi lần chỉ đổi một quy tắc: nhiều quy tắc cùng lúc dễ che lỗi của nhau (xem `dev\experiments\`).

## Quy ước

- **Xuống dòng & mã hóa:** LF và UTF-8 cho mọi tệp văn bản (`.gitattributes`, `.editorconfig`); riêng `.cmd`/`.bat` dùng CRLF. Khi sửa tệp, giữ nguyên kiểu xuống dòng của tệp.
- **Chỉ dẫn cho agent:**
  - `AGENTS.md` và `SKILL.md` viết trung lập theo hành động ("đọc trọn 1 lần", "mở xem song song", "ghi nối dần"), không ghi tên công cụ của một agent cụ thể.
  - Chi tiết riêng của Antigravity chỉ đặt trong `.agents\adapters\antigravity.md`; riêng Claude Code trong `.agents\adapters\claude-code.md`.
  - `.claude\skills\` chỉ là lối vào: phần frontmatter (`name`, `description`) phải giống hệt skill gốc trong `.agents\skills\`.
  - Lệnh mẫu trong tài liệu bắt đầu đúng dạng `powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'tools\<script>.ps1'` để khớp quy tắc cho phép trong `.claude\settings.json`.
  - Sau mọi thay đổi ở các tệp này, chạy `test_skill_contracts.py`: test đối chiếu tham số, giá trị mặc định, dòng stdout, liên kết và kích thước tệp SI với mã thật.
- **Đổi dòng stdout của exe:** nếu `SKILL.md` dựa vào dòng đó, cập nhật `SKILL.md` cùng lúc (test đối chiếu sẽ báo nếu quên).
- **CHANGELOG:** ghi thay đổi vào mục `[Unreleased]`. Khi phát hành, đổi `[Unreleased]` thành số phiên bản, commit, rồi đẩy tag `vX.Y.Z` để CI build và đóng gói.
- **Commit:** tách theo chủ đề, tiêu đề tiếng Anh dạng `fix: …`, `feat: …`, `test: …`, `refactor: …`, `chore: …`, `docs: …`. Không commit `output\`, `work\`, `tools\extract_assets\`.
