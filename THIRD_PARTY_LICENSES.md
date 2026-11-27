# Third-Party Licenses & Notices

Mã nguồn gốc của dự án **Max Luka Loop** (bao gồm `AGENTS.md`, thư mục `.agents/skills/`, các script PowerShell trong `tools/`, `tools/reader_shell.html` và bộ mã nguồn tham chiếu trong `tools/src/`) được phát hành theo [MIT License](./LICENSE).

Tuy nhiên, gói công cụ thực thi dựng sẵn dành cho Windows (`tools/extract_assets/`, được biên dịch tự động trên GitHub Actions và phân phối kèm trong gói phát hành Release `max-luka-loop-win-x64.zip`) chứa các thư viện và tệp nhị phân của bên thứ ba dưới các giấy phép riêng biệt sau đây:

## Tổng hợp thành phần bên thứ ba trong `tools/extract_assets/`

| Thành phần | Tệp tiêu biểu trong repo | Chủ sở hữu / Nguồn | Giấy phép | Toàn văn giấy phép |
| :--- | :--- | :--- | :--- | :--- |
| **PyMuPDF / MuPDF** | `_internal/pymupdf/mupdfcpp64.dll`, `_mupdf.pyd`, `_extra.pyd` | Artifex Software, Inc. | **AGPL-3.0** | [licenses/AGPL-3.0.txt](./licenses/AGPL-3.0.txt) |
| **Python 3.12.7** | `_internal/python312.dll`, `python3.dll`, `base_library.zip`, `*.pyd` | Python Software Foundation | **PSF-2.0** | [licenses/PSF-2.0.txt](./licenses/PSF-2.0.txt) |
| **OpenSSL 3.0.15** | `_internal/libcrypto-3.dll` | The OpenSSL Authors | **Apache-2.0** | [licenses/Apache-2.0.txt](./licenses/Apache-2.0.txt) |
| **PyInstaller** | Bootloader của `extract_assets.exe` & runtime hooks | PyInstaller Development Team | **GPL-2.0-or-later** (kèm Bootloader Exception) & **Apache-2.0** | [licenses/PyInstaller-COPYING.txt](./licenses/PyInstaller-COPYING.txt) |
| **Microsoft Visual C++ Runtime & UCRT** | `MSVCP140.dll`, `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`, `ucrtbase.dll`, `api-ms-win-*.dll` | Microsoft Corporation | Microsoft Runtime Redistribution Terms | Xem thông báo bên dưới |
| **ONNX Runtime 1.32.0** | `_internal/onnxruntime/capi/onnxruntime.dll`, `onnxruntime_pybind11_state.pyd` | Microsoft Corporation | **MIT** (kèm thông báo bên thứ ba) | [licenses/onnxruntime-LICENSE.txt](./licenses/onnxruntime-LICENSE.txt), [licenses/onnxruntime-ThirdPartyNotices.txt](./licenses/onnxruntime-ThirdPartyNotices.txt) |
| **NumPy 2.5.5** (kèm OpenBLAS, thư viện GCC runtime) | `_internal/numpy/`, `_internal/numpy.libs/libscipy_openblas*.dll` | NumPy Developers; The OpenBLAS Project | **BSD-3-Clause** (OpenBLAS: BSD-3-Clause; GCC runtime: GPL-3.0 kèm GCC Runtime Library Exception) | [licenses/numpy-LICENSE.txt](./licenses/numpy-LICENSE.txt) |
| **Mô hình docling-layout-egret-medium** (bản chuyển sang ONNX) | `_internal/models/egret_medium.onnx` | Docling Project ([Hugging Face](https://huggingface.co/docling-project/docling-layout-egret-medium)) | **Apache-2.0** | [licenses/Apache-2.0.txt](./licenses/Apache-2.0.txt) |
| **Docling — hậu xử lý bố cục, thứ tự đọc, ghép chú thích** (mã port lại, nằm trong `extract_assets.exe` và [`tools/src/figure_detector/docling_layout.py`](./tools/src/figure_detector/docling_layout.py)) | `extract_assets.exe` (mã Python đã đóng gói) | The Docling Contributors | **MIT** | [licenses/docling-MIT.txt](./licenses/docling-MIT.txt) |
| **docling-core — các phép so khung (`BoundingBox`)** (mã port lại, cùng tệp trên) | `extract_assets.exe` (mã Python đã đóng gói) | International Business Machines | **MIT** | [licenses/docling-core-MIT.txt](./licenses/docling-core-MIT.txt) |

---

## Thông báo chi tiết theo từng thành phần

### 1. PyMuPDF / MuPDF (GNU Affero General Public License v3.0 — AGPL-3.0)
- Gói thực thi `tools/extract_assets/extract_assets.exe` (tự động build từ [`tools/build_extractor.ps1`](./tools/build_extractor.ps1)) được biên dịch liên kết trực tiếp với thư viện **PyMuPDF / MuPDF**, do đó bản phân phối nhị phân kết hợp tuân theo các điều khoản của **AGPL-3.0**.
- Toàn bộ mã nguồn phía ứng dụng dùng để tạo `extract_assets.exe` được công khai đầy đủ tại [`tools/src/`](./tools/src/) ([`extract_assets.py`](./tools/src/extract_assets.py), [`figure_detector/`](./tools/src/figure_detector/), [`image_ops.py`](./tools/src/image_ops.py), [`packager.py`](./tools/src/packager.py), [`reader_shell.py`](./tools/src/reader_shell.py), [`html_qa.py`](./tools/src/html_qa.py), [`pdf_export.py`](./tools/src/pdf_export.py), [`output_paths.py`](./tools/src/output_paths.py), [`transcript.py`](./tools/src/transcript.py), [`manifest.py`](./tools/src/manifest.py), [`path_guards.py`](./tools/src/path_guards.py)). Mã nguồn thượng nguồn của PyMuPDF và MuPDF được cung cấp công khai bởi Artifex Software tại <https://github.com/pymupdf/PyMuPDF> và <https://mupdf.com/>.
- Toàn văn giấy phép xem tại [`licenses/AGPL-3.0.txt`](./licenses/AGPL-3.0.txt).

### 2. Python 3.12.7 (Python Software Foundation License Version 2)
```text
This distribution incorporates Python 3.12.7.
Python is Copyright (c) 2001-2024 Python Software Foundation; All Rights Reserved.
Licensed under the Python Software Foundation License Version 2 (PSF-2.0).
```
- Toàn văn giấy phép xem tại [`licenses/PSF-2.0.txt`](./licenses/PSF-2.0.txt).

### 3. OpenSSL 3.0.15 (Apache License 2.0)
```text
This product includes cryptographic software written by the OpenSSL Project
for use in the OpenSSL Toolkit (https://www.openssl.org/).
Copyright 1998-2024 The OpenSSL Authors. All rights reserved.
OpenSSL 3.0.15 (libcrypto-3.dll) is licensed under the Apache License, Version 2.0.
```
- Toàn văn giấy phép xem tại [`licenses/Apache-2.0.txt`](./licenses/Apache-2.0.txt).

### 4. PyInstaller (GPL-2.0-or-later với Bootloader Exception & Apache-2.0)
- `extract_assets.exe` sử dụng bootloader của **PyInstaller**, được phân phối kèm ngoại lệ *Bootloader Exception* (cho phép kết hợp với mã nguồn khác) và các runtime hook theo Apache-2.0.
- Toàn văn điều khoản xem tại [`licenses/PyInstaller-COPYING.txt`](./licenses/PyInstaller-COPYING.txt).

### 5. Microsoft Visual C++ Runtime & Universal CRT
- Các tệp `MSVCP140.dll`, `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`, `ucrtbase.dll` và bộ `api-ms-win-crt-*.dll` / `api-ms-win-core-*.dll` mang bản quyền `© Microsoft Corporation. All rights reserved.` và chỉ được đóng gói lại như thành phần runtime phụ trợ đi kèm bản dựng Python portable trên Windows.

### 6. ONNX Runtime 1.32.0 (MIT License)
- Dùng để chạy mô hình Egret trên CPU. `Copyright (c) Microsoft Corporation`. Toàn văn giấy phép và thông báo các thành phần ONNX Runtime đóng gói lại: [`licenses/onnxruntime-LICENSE.txt`](./licenses/onnxruntime-LICENSE.txt), [`licenses/onnxruntime-ThirdPartyNotices.txt`](./licenses/onnxruntime-ThirdPartyNotices.txt).

### 7. NumPy 2.5.5 (BSD-3-Clause)
- Thư viện mảng onnxruntime cần. Bản Windows kèm OpenBLAS và thư viện GCC runtime; điều khoản của từng thành phần nằm trong [`licenses/numpy-LICENSE.txt`](./licenses/numpy-LICENSE.txt).

### 8. Mô hình bố cục docling-layout-egret-medium (Apache License 2.0)
- Trọng số gốc do Docling Project phát hành tại <https://huggingface.co/docling-project/docling-layout-egret-medium> theo **Apache-2.0**.
- **Nguồn chính xác:** commit `77ede7cc7bed96d853c58f319734803d6ea2ea5c` của repo trên, tệp `model.safetensors` có SHA-256 `e7fc5b9a353826c123c5d03efc230909ac02b93e26293ec7cb4db8978fe9e3af` (trọng số này giống hệt ở mọi commit có trọng số của repo). Tệp ONNX phát hành có SHA-256 `06da7202c1fcfc9eb984830857c51c1e3993e8ba36a21f76c74d4c0756d1fbcc`; [`dev/egret/verify_onnx_weights.py`](./dev/egret/verify_onnx_weights.py) kiểm lại rằng tệp ONNX chứa đúng các trọng số đó. Với đúng các phiên bản công cụ trong [`dev/egret/requirements-export.txt`](./dev/egret/requirements-export.txt), chạy lại `export_onnx.py` từ trọng số trên tạo ra tệp ONNX giống hệt từng byte (cùng SHA-256), nên ai cũng tự tái tạo và đối chiếu được.
- **Thay đổi so với bản gốc** (theo điều 4(b) của Apache-2.0): trọng số được chuyển từ safetensors (PyTorch) sang ONNX bằng [`dev/egret/export_onnx.py`](./dev/egret/export_onnx.py), đầu vào cố định 1×3×640×640, position embedding của encoder được tính sẵn thành hằng float32. Khi xuất, BatchNorm được gộp vào lớp Conv đứng trước (hoặc tính sẵn thành hằng nhân/cộng ở backbone), một phép biến đổi tương đương về toán học; các phần chỉ dùng khi huấn luyện (đầu dự đoán của lớp decoder trung gian, nhánh denoising) không có trong đồ thị. Trọng số không bị huấn luyện lại.
- Toàn văn giấy phép xem tại [`licenses/Apache-2.0.txt`](./licenses/Apache-2.0.txt).

### 9. Docling — hậu xử lý bố cục, thứ tự đọc, ghép chú thích (MIT License)
```text
Copyright The Docling Contributors
Licensed under the MIT License.
```
- Sau khi mô hình Egret chạy, mọi bước tiếp theo được port từ dự án [Docling](https://github.com/docling-project/docling) (gói `docling-slim` 2.151.1) vào [`tools/src/figure_detector/docling_layout.py`](./tools/src/figure_detector/docling_layout.py):
  - `docling/utils/layout_postprocessor.py` (`LayoutPostprocessor`): ngưỡng tin cậy theo nhãn, gán dòng chữ vào vùng, tạo vùng cho chữ lẻ, gom khung chồng nhau, loại hình phủ trên 90% trang, ưu tiên bảng khi trùng khung với hình;
  - `docling/models/postprocessing/reading_order_rb.py` (`ReadingOrderPredictor`): thứ tự đọc theo luật, ghép chú thích và chú thích cuối (footnote) với hình/bảng liền kề;
  - `docling/models/stages/reading_order/readingorder_model.py` và `page_assemble/page_assemble_model.py`: sắp xếp phần tử trong vùng Form/Key-Value, ngưỡng 80% để coi ảnh nằm trong bảng, cách nối dòng chữ (`sanitize_text`);
  - `docling/utils/text_normalization.py`: chuẩn hóa ký tự (dấu nháy, chữ ghép).
- Toàn văn giấy phép xem tại [`licenses/docling-MIT.txt`](./licenses/docling-MIT.txt).

### 10. docling-core — phép so khung `BoundingBox` (MIT License)
```text
Copyright (c) 2024 International Business Machines
Licensed under the MIT License.
```
- Các phép so khung dùng trong thứ tự đọc (`overlaps_horizontally`, `is_strictly_above`, `overlaps_vertically_with_iou`…) được port từ `docling_core/types/doc/base.py` (gói `docling-core` 2.108.0) vào lớp `_Node` của [`tools/src/figure_detector/docling_layout.py`](./tools/src/figure_detector/docling_layout.py).
- Toàn văn giấy phép xem tại [`licenses/docling-core-MIT.txt`](./licenses/docling-core-MIT.txt).

---

## Tài nguyên tải qua CDN khi xem HTML (tùy chọn phía trình duyệt)
Các tệp HTML đầu ra có thể tham chiếu tới tài nguyên công cộng qua Internet (không đóng gói nhị phân trong repo):
- **MathJax 3** (tải từ `cdn.jsdelivr.net` khi tài liệu có công thức toán học): **Apache License 2.0**.
- **Google Fonts — Inter** (tải từ `fonts.googleapis.com`): **SIL Open Font License 1.1**.
