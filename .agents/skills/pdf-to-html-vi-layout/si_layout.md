# Bộ Quy tắc Tái Tạo Thiết Kế & Dàn Trang HTML/CSS (`pdf-to-html-vi-layout` — Pha Thiết Kế)

> Tài liệu chuyên trách **Nghệ thuật chữ & Bảo toàn Thiết kế Từng Trang** cho Bước 3 & Bước 4 của skill [`pdf-to-html-vi-layout`](./SKILL.md). Đọc file này ngay khi bắt đầu Bước 3 để dựng `work\draft.html` từ `work\translated.md`, PDF gốc, `manifest.json` và ảnh tách ra từ file PDF.

---

## 1. Vai trò & Thứ tự Ưu tiên Thiết kế

Bạn là **Kỹ sư Dàn trang & Typographer Cao cấp**. Với bản dịch đã hoàn chỉnh ở `work\translated.md`, nhiệm vụ của bạn ở pha này là tái tạo giao diện HTML/CSS **trung thực tối đa với cấu trúc thị giác từng trang của PDF gốc**, đồng thời giữ khả năng đọc sắc nét trên màn hình máy tính và xuất bản đẹp sang PDF.

**Thứ tự ưu tiên (khi có xung đột ở Pha 3):**
1. **KHÔNG MẤT NỘI DUNG / KHÔNG CẮT CHỮ:** Tiếng Việt dài hơn tiếng Anh `~15–25%` → không bao giờ ép `height` cứng + `overflow: hidden` làm mất chữ; mọi trang `.pdf-page` phải co giãn chiều cao tự nhiên (`height: auto`).
2. **BẢO TOÀN CẤU TRÚC THỊ GIÁC GỐC:** Giữ đúng số cột, phân vùng trái/phải, bảng biểu phức tạp, hộp callout, màu sắc/nhấn mạnh, đường kẻ và vị trí hình ảnh của từng trang PDF.
3. **KHẢ NĂNG ĐỌC TỐI ƯU & KHÔNG TRÀN NGANG:** Thân bài mặc định `18px` bằng họ font không chân `Inter` (kèm fallback hệ thống), chống tràn ngang container.

---

## 2. Quy chuẩn Font chữ & Global CSS (Đặt trong `<head>` của `work\draft.html`)

### 2.1 Quy tắc Font chữ Không chân Thống nhất
- **Font chính (`--font-sans`):** Bắt buộc ưu tiên **`'Inter'`** (hỗ trợ dấu tiếng Việt sắc nét, gọn bề ngang giúp văn bản tiếng Việt dễ nằm gọn trong các cột/hộp hẹp của thiết kế gốc, đủ trọng số `400–800` và `tabular-nums` căn thẳng số liệu; nạp qua `@import` duy nhất ở Mục 2.4) kèm fallback hệ thống Windows/offline **`'Segoe UI', Roboto, 'Noto Sans', Arial, sans-serif`**.
- **Font monospace (cho code/mã số):** `'JetBrains Mono', Consolas, 'Courier New', monospace`.
- **Cỡ chữ thân bài mặc định:** **`18px`**, `line-height: 1.6`.
  - *Linh hoạt cục bộ theo thiết kế gốc:* Cho phép hạ nhẹ cỡ chữ có kiểm soát (`14px–16.5px`) tại các ô bảng nhiều cột, thẻ thông số hẹp, `running-header`, `figcaption` hoặc `footnotes` để giữ nguyên tỷ lệ khung trang PDF gốc mà không bị tràn vỡ.

### 2.2 Khung Giấy Từng Trang (class `.pdf-page`) & Chiều rộng Linh hoạt (`740px–1000px`)
- Toàn bộ tài liệu đặt trên nền ngoài trung tính nhẹ (vd `#eef2f6`), mỗi trang PDF gốc được dựng thành **một khung giấy riêng biệt**:
  `<section id="pdf-page-N" class="pdf-page" data-page="N">...</section>` *(với `N = 1, 2, ...`)*.
- **Độ rộng linh hoạt `--page-width`:** AI chọn 1 giá trị tối ưu trong khoảng **`740px` đến `1000px`** ở Global CSS `:root` dựa theo mật độ và số cột của PDF gốc:
  - Tài liệu 1 cột thanh thoát: `--page-width: 780px;` *(hoặc `740px–840px`)*.
  - Tài liệu 2–3 cột, bảng rộng, slide ngang 16:9, brochure: `--page-width: 920px;` đến `1000px;` *(tối đa `1000px`)*.
- **Chiều cao linh hoạt (`height: auto`):** Dùng `min-height` nhẹ hoặc để `height: auto` tự giãn theo chữ tiếng Việt; **TUYỆT ĐỐI KHÔNG** đặt `height` cố định kèm `overflow: hidden`.

### 2.3 Chiến lược CSS 2 Tầng (Chống Lặp CSS — Tiết Kiệm Token & Cô Lập Trang)
1. **Tầng 1 — Global CSS (`<style>` đầu `<head>`):** Phân tích tổng quan PDF để định nghĩa **một lần duy nhất** bảng biến màu gốc (`--doc-paper`, `--doc-ink`, `--doc-muted`, `--doc-primary`, `--doc-accent`, `--doc-surface`, `--doc-border`), cỡ chữ, tỷ lệ tiêu đề (`h1`, `h2`, `h3` khớp tỷ lệ tài liệu gốc), `.pdf-page`, `.multi-column-flow`, `.academic-table` / `.grid-table`, `.callout`, `.running-header`, `.footnotes`, `<hr>`, `.cjk` và `@media print`.
2. **Tầng 2 — Scoped CSS từng trang (`#pdf-page-N ...` hoặc `style="..."` nội tuyến):** Trong từng trang `<section id="pdf-page-N">`, tái sử dụng tối đa class Global CSS ở trên, **chỉ dùng bộ chọn `#pdf-page-N ...` hoặc `style="..."` nội tuyến** cho bố cục/màu sắc đặc thù riêng của trang đó (như trang bìa, banner màu, lưới bất đối xứng `grid-template-columns`, vị trí ảnh/hộp đặc biệt) — đảm bảo trang này hoàn toàn không ghi đè làm hỏng trang khác.

### 2.4 Bộ CSS Nền Khởi tạo (Tùy biến biến màu & `--page-width` theo PDF gốc)
```css
@import url('https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,400..800;1,14..32,400..700&display=swap');

:root {
    --font-sans: 'Inter', 'Segoe UI', Roboto, 'Noto Sans', Arial, sans-serif;
    --font-mono: 'JetBrains Mono', Consolas, 'Courier New', monospace;
    --page-width: 900px;       /* Điều chỉnh từ 740px đến 1000px tùy bố cục PDF gốc */
    --doc-canvas: #eef2f6;
    --doc-paper: #ffffff;
    --doc-surface: #f8fafc;
    --doc-ink: #1e293b;
    --doc-heading: #0f172a;
    --doc-muted: #475569;
    --doc-primary: #1d4ed8;    /* Chỉnh theo màu chủ đạo của PDF gốc */
    --doc-accent: #0369a1;
    --doc-border: #cbd5e1;
}

*, *::before, *::after { box-sizing: border-box; }

body {
    margin: 0;
    padding: 28px 16px;
    background-color: var(--doc-canvas);
    color: var(--doc-ink);
    font-family: var(--font-sans);
    font-size: 18px;
    line-height: 1.6;
    overflow-wrap: break-word;
}

/* Khung tờ giấy từng trang — chiều cao linh hoạt */
.pdf-page {
    width: 100%;
    max-width: var(--page-width);
    height: auto;
    margin: 0 auto 28px;
    padding: 40px 44px;
    background-color: var(--doc-paper);
    border: 1px solid #dbe2ea;
    border-radius: 6px;
    box-shadow: 0 4px 18px rgba(15, 23, 42, 0.08);
}

h1, h2, h3, h4, h5, h6 {
    color: var(--doc-heading);
    line-height: 1.28;
    margin-top: 1.2em;
    margin-bottom: 0.5em;
    break-after: avoid;
    page-break-after: avoid;
}

.pdf-page > :first-child { margin-top: 0; }
p { margin: 0 0 0.85em; }

/* Tiêu đề lặp & số trang in gọn nhẹ từng trang */
.running-header {
    font-size: 0.78rem;
    color: #64748b;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 6px;
    margin-bottom: 20px;
    display: flex;
    justify-content: space-between;
    gap: 12px;
    font-style: italic;
}

/* Luồng chữ đa cột chảy liên tục */
.multi-column-flow { column-gap: 28px; column-fill: balance; orphans: 2; widows: 2; }
.cols-2 { columns: 2; }
.cols-3 { columns: 3; }
.col-rule { column-rule: 1px solid var(--doc-border); }
.span-all { column-span: all; }

/* Hình ảnh & Chú thích */
img, svg { max-width: 100%; height: auto; object-fit: contain; display: block; margin: 0 auto; border-radius: 4px; }
figure { margin: 1.1rem 0; break-inside: avoid; page-break-inside: avoid; }
figcaption { font-size: 0.88rem; color: var(--doc-muted); line-height: 1.45; margin-top: 0.45rem; }
td img, th img { margin: 0.2rem auto; }

/* Bảng biểu học thuật & bảng lưới */
.table-wrapper { width: 100%; overflow-x: auto; margin: 1rem 0; -webkit-overflow-scrolling: touch; }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; margin: 1rem 0; font-variant-numeric: tabular-nums; }
.table-wrapper > table { margin: 0; }
tr { break-inside: avoid; page-break-inside: avoid; }
th, td { border: 1px solid var(--doc-border); padding: 7px 10px; text-align: left; vertical-align: top; }
th { background-color: #f1f5f9; font-weight: 600; color: var(--doc-heading); }
table.academic-table th, table.academic-table td { border-left: none; border-right: none; }
table.academic-table thead th { background: transparent; border-top: 2px solid var(--doc-heading); border-bottom: 1.5px solid var(--doc-heading); }
table.academic-table tbody tr:last-child td { border-bottom: 2px solid var(--doc-heading); }
tr.summary-row td { font-weight: 700; background-color: var(--doc-surface); border-top: 1.5px solid var(--doc-heading); }
.ws-nowrap { white-space: nowrap; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.table-note { font-size: 0.85rem; color: var(--doc-muted); margin-top: 0.35rem; break-before: avoid; page-break-before: avoid; }

/* Hộp Callout / Định lý */
.callout {
    border: 1px solid #e2e8f0;
    border-left: 4px solid var(--doc-primary);
    background-color: var(--doc-surface);
    border-radius: 6px;
    padding: 12px 16px;
    margin: 1rem 0;
    break-inside: avoid;
    page-break-inside: avoid;
}

/* Footnotes cuối trang & Đường kẻ & CJK */
.footnotes {
    margin-top: 20px;
    padding-top: 10px;
    border-top: 1px solid var(--doc-border);
    font-size: 0.84rem;
    color: var(--doc-muted);
    line-height: 1.45;
}

.footnotes p { margin: 3px 0; }
ul.ref-list { list-style: none; padding-left: 0; }
ul.ref-list li { padding-left: 2em; text-indent: -2em; margin-bottom: 0.55em; overflow-wrap: anywhere; }
.cjk { font-family: 'Noto Serif SC', 'Yu Mincho', 'SimSun', 'Microsoft YaHei', sans-serif; }
pre { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; overflow-x: auto; font-size: 0.88rem; }
code { font-family: var(--font-mono); font-size: 0.88em; background: #f1f5f9; padding: 1px 4px; border-radius: 3px; }
pre code { background: transparent; padding: 0; }

/* An toàn xuất PDF */
@media print {
    @page { margin: 10mm 12mm; }
    body { background: #ffffff !important; padding: 0 !important; font-size: 10.5pt; }
    figure img { max-height: 82vh; }
    .pdf-page {
        width: 100% !important;
        max-width: 100% !important;
        margin: 0 0 12mm !important;
        padding: 0 !important;
        border: none !important;
        box-shadow: none !important;
        border-radius: 0 !important;
    }
    .pdf-page.print-break-after { break-after: page; page-break-after: always; }
}
```
*(Lưu ý `@media print`: Nếu toàn bộ PDF gốc là slide/infographic khổ ngang, thêm `@page { size: A4 landscape; margin: 8mm 10mm; }`. Chỉ gắn class `print-break-after` cho các trang ít chữ chắc chắn nằm gọn trong 1 trang giấy như trang bìa hoặc từng slide, tránh tạo trang thừa 1–2 dòng khi trang văn bản tiếng Việt dài ra.)*

---

## 3. Quy tắc Dàn Trang Theo Cấu Trúc Gốc

1. **Văn bản Đa cột Liên tục vs. Hai luồng Độc lập:**
   - **Văn bản liên tục chảy từ đáy cột 1 lên đỉnh cột 2 (bài báo 2–3 cột, tạp chí):** **BẮT BUỘC** bọc chung vào 1 khối **CSS Multi-Columns** (`.multi-column-flow.cols-2` hoặc `.cols-3`, thêm `.col-rule` nếu bản gốc có đường kẻ dọc ngăn cột). Trình duyệt sẽ tự cân bằng độ cao hai cột mà không bị hụt chân cột 1! Dùng `.span-all` nếu có tiêu đề hoặc hình lớn vắt ngang 2 cột; gắn `break-inside: avoid` cho hình/bảng/callout bên trong để không bị cắt làm đôi.
   - **Hai khối nội dung độc lập đặt cạnh nhau (sidebar + thân bài, 2 card so sánh, 2 cột metadata, bố cục trang bìa/brochure):** Dùng **`CSS Grid` / `Flexbox`** (`display: grid; grid-template-columns: ...; gap: ...; align-items: start;`). Thêm `min-width: 0;` cho item bên trong Grid để bảng/ảnh không phá rộng cột.
   - **TUYỆT ĐỐI KHÔNG** dùng `<table>` để giả lập chia cột dàn trang.
2. **Câu văn nối từ trang nọ sang trang kia (`<!-- cont -->`):**
   - Nếu gặp đoạn đánh dấu `<!-- cont -->` vắt trang, bạn hiểu rằng đó là ranh giới cứng tương ứng với vị trí ngắt trang của văn bản gốc tiếng Anh, nếu bạn cũng ngắt trang tại đó ở văn bản dịch tiếng Việt, nó thường tạo ra khoảng không hụt chữ phía sau (underfull page).
   - Bạn phải khắc phục điều đó một cách chắc chắn bằng cách lấy thêm chữ của trang sau đến **dấu kết thúc câu (dấu chấm, dấu hỏi, dấu chấm than, dấu chấm lửng) gần nhất** ngay sau từ bị ngắt cứng, nhưng việc lấy thêm không được phép quá 1 dòng. Nếu phải lấy thêm hơn 1 dòng mới tìm thấy dấu kết thúc câu, bạn bắt buộc ngắt cứng trang đúng vị trí `<!-- cont -->` và thêm dấu `...` vào từ cuối của trang trước, rồi thêm dấu `...` vào trước từ bắt đầu của trang sau.  
3. **Thụt lề đầu dòng & Drop Caps:**
   - Chỉ áp dụng `text-indent: 1.5em` khi tài liệu gốc thực sự thụt đầu dòng từng đoạn. Nếu tái tạo Drop Caps (`float: left`), kiểm tra cẩn thận để không làm vỡ khoảng cách từ đầu tiên.
4. **Bảng biểu phức tạp:**
   - Hỗ trợ đầy đủ `<table>`, `<caption>`, `<thead>`, `<tbody>`, `<tfoot>`, `colspan`, `rowspan`, `academic-table` (3 đường kẻ học thuật) vs bảng lưới, `ws-nowrap` cho số/mã ngắn, `.num` căn phải cho cột số liệu.
   - Nếu bảng quá nhiều cột có nguy cơ tràn ngang vượt `--page-width`, chủ động bọc riêng bảng đó trong `<div class="table-wrapper">` *(Auto-QA dưới `-PreserveLayout` không ép bọc mọi bảng để bạn tự do giữ thiết kế bảng gọn)*.
   - **Bảng dài vắt qua trang:** Đóng `</table>` ở cuối `<section id="pdf-page-N">`, sang đầu `<section id="pdf-page-N+1">` mở bảng mới kèm lặp lại `<thead>` *(có thể ghi chú "Bảng X (tiếp theo)")*.
5. **Hộp Callout, Thơ ca, Footnotes, Running Header & Đường kẻ:**
   - **Callouts (Định lý, Định nghĩa, Cảnh báo):** Dùng `.callout` + `style="border-left-color: ...; background: ...;"` theo màu PDF gốc, thêm `<div style="text-align: right;">■</div>` cho ký hiệu kết thúc chứng minh nếu có.
   - **Thơ / Trích dẫn:** Dùng `<blockquote ...>` giữ nguyên xuống dòng từng câu thơ; câu đối song song dùng `display: flex; justify-content: space-around;`.
   - **`Running header` & `Footnotes`:** Đặt `.running-header` ở đỉnh trang và `.footnotes` ở đáy **đúng khung trang `.pdf-page` tương ứng** theo bản gốc.
   - **Đường kẻ trang trí:** Khớp kiểu gốc bằng `<hr style="width: 80px; border: 0; border-top: 1.5px solid ...; margin: 18px auto;">` (gạch ngắn căn giữa), vạch mảnh toàn trang, hoặc đường kẻ đôi (`border-top: 3px double ...`).
6. **MathJax & Công thức Toán học (An toàn tuyệt đối):**
   - Khi tài liệu có công thức `\( \)` / `\[ \]`, nhúng vào `<head>`:
     ```html
     <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
     ```
   - Block math đặt trong `<div style="text-align: center; margin: 12px 0; break-inside: avoid;">\[ ... \]</div>`; chừa khoảng trắng quanh `<` và `>` trong LaTeX (`\( x < y \)`); **không** bọc LaTeX trong `<code>` hay `<pre>`.
7. **Chuyển hóa sạch Tag trung gian & Liên kết `References`:**
   - Thay thế trọn vẹn mọi tag tạm từ `work\translated.md` (`<!-- p:N -->`, `<!-- cont -->`, `[HEADER]`, `[FOOTER]`, `[FIG:]`, `[TBL-IMG:]`, `[DIAGRAM-A]`, `[CALLOUT]`, `[FN]`) bằng cấu trúc HTML/CSS tương ứng — **tuyệt đối không để sót tag thô trong `work\draft.html`**.
   - Với `References` / `Bibliography`: giữ nguyên phần nhận diện không dịch kèm định dạng in đậm/nghiêng gốc, dùng `ul.ref-list` nếu bản gốc thụt lề ngược (*hanging indent*), và chuyển mọi **URL / DOI** thành liên kết `<a href="..." target="_blank" rel="noopener">` nhấp được.

---

## 4. Khai thác `manifest.json` & Tái tạo Hình ảnh / Sơ đồ trên Từng Trang

1. **Áp dụng đúng thông tin từ `work/assets/manifest.json` (và ảnh `CropFromJson`):**
   - Dùng đường dẫn tương đối `src="assets/<tên_file>.png"` và luôn viết `alt` tiếng Việt ngắn gọn cho ảnh. *(Lưu ý: ảnh cắt bằng `CropFromJson` không tự ghi vào `manifest.json` — nhớ đối chiếu bổ sung đủ toàn bộ `out_name`.)*
   - **`box: [x0, y0, x1, y1]` (`0.0–1.0`):** Cực kỳ hữu ích cho bảo toàn thiết kế! Dùng trực tiếp tỷ lệ `x0, x1` để đặt ảnh đúng vùng trên trang:
     - Nằm gọn cột trái (`x1 <= 0.50`) / cột phải (`x0 >= 0.50`) / trải rộng (`x0 < 0.45 && x1 > 0.55`).
     - Có thể tính gần đúng tỷ lệ bề rộng hiển thị của ảnh (vd `width = (x1 - x0) * 100%`) để hình minh họa trên `.pdf-page` có kích thước tương xứng bản gốc (kết hợp `max-width: 100%`).
   - **Giữ đúng thứ tự trên–dưới (`y0`):** Trong cùng một cột (cùng vùng `x0, x1`), xếp ảnh theo `y0` tăng dần và đặt mỗi ảnh cạnh đúng đoạn/bước văn bản nằm ngang hàng với nó trong PDF gốc. **Tên tệp `fig_pX_Y` không phải thứ tự đọc**: `Y` chỉ là số thứ tự quét từ trên xuống trên toàn trang, nên ở trang nhiều cột các số chạy so le giữa các cột (vd `fig_p6_1` cột trái, `fig_p6_2` cột phải, `fig_p6_3` lại cột trái). Nếu hình có số/nhãn in sẵn (①, ②, *Step 3*, *(a)*…), mở xem ảnh để đọc nhãn và đối chiếu với vị trí trên trang gốc, tuyệt đối không suy thứ tự hay số bước từ tên tệp.
   - **`placement` (`"figure"` | `"table_cell"`):** Khi là `"table_cell"`, đặt `<img src="assets/..." alt="..." style="max-width: 140px;">` vào đúng ô `<td>` của hàng bảng khớp `context`. Khi là `"figure"`, đặt trong `<figure>...</figure>` (chỉ thêm `<figcaption>` nếu gốc có chú thích, lấy toàn văn từ `work\translated.md` / PDF gốc, **không** dùng chuỗi rút gọn 20 từ `...` trên stdout).
   - **`source`, `drawings`, `width_px`, `height_px`, `dpi`:**
     - `"raster"` hoặc `"hybrid"` → **Nhóm B** (giữ nguyên `<img src="assets/...">`; nếu chữ trong hình Nhóm B mờ, chạy lại Bước 1 với `-Dpi 250/300`).
     - `"vector"` kèm `drawings` thấp/vừa (`<= ~30–50`) → ưu tiên tái tạo bằng HTML/CSS (**Nhóm A**) phối đúng bảng màu và font của `.pdf-page` (rất sắc nét và dễ căn kích thước theo thiết kế trang; nếu đã tái tạo hoàn chỉnh thì bỏ PNG gốc để tránh trùng). `"vector"` nhiều nét phức tạp (scatter/ROC/violin plot...) → **Nhóm B**, giữ nguyên PNG.
2. **Không bao giờ bỏ sót hình hay ghi *"vui lòng xem ở bản gốc"*:** Mọi hình chụp/biểu đồ phức tạp đều phải giữ bằng `<img>` đã tách (hoặc cắt bằng `CropFromJson`), mọi sơ đồ đơn giản đều phải dựng HTML/CSS hoàn chỉnh.

---

## 5. Chốt Chặn Mã nguồn & Kiểm định Nội bộ (Trước khi Đóng gói)
*(Các lỗi kỹ thuật cơ học như ảnh chưa nhúng, thiếu `alt`, quên MathJax `<script>` hay link `#id` gãy sẽ được `html_packager.ps1` kiểm tra tự động; trước khi chạy Bước 4, rà lại 5 điểm mà máy không tự bắt được dưới đây:)*

- **Thuần HTML + CSS (ZERO Script ngoài MathJax):**
  - **TUYỆT ĐỐI KHÔNG** chèn thanh công cụ đọc, lightbox JS, nút chuyển Dark/Light hay bất kỳ `<script>` tự viết nào (chỉ duy nhất thẻ `<script id="MathJax-script" ...>` nếu bài có LaTeX). Không dùng `<iframe>`, `<form>`, `onclick`, `onload`.
- **Rà lại `work\draft.html` trước khi chạy `tools\html_packager.ps1 ... -PreserveLayout -AlsoPdf -CleanDir 'work'`:**
  1. Đã hoàn chỉnh cấu trúc `<!DOCTYPE html><html><head>...</head><body>...</body></html>`, dùng font `'Inter'` (cỡ thân bài `18px`), mỗi trang nằm gọn trong `<section id="pdf-page-N" class="pdf-page">` có chiều cao `auto` (không bị `overflow: hidden` cắt chữ) và chiều rộng `--page-width` trong `740px–1000px`?
  2. Luồng chữ 2–3 cột liên tục đã dùng `.multi-column-flow` (không chặt đôi khiến cột 1 hụt chân)? Không dùng `<table>` để chia cột trang?
  3. Đã chuyển **đủ 100%** nội dung từ `work\translated.md` (không sót câu/trang, nối mượt `<!-- cont -->`, chú thích chân trang đặt đúng trang, không lọt tạp âm scan) và **không còn sót tag trung gian thô** (`[FIG:]`, `[CALLOUT]`, `[DIAGRAM-A]`, `<!-- p:... -->`...)?
  4. Mọi minh họa trong PDF gốc đều có mặt đúng vùng `box` và **đúng thứ tự trên–dưới trong từng cột như bản gốc** (đối chiếu nhãn/số in trên hình, không theo tên tệp) (ảnh Nhóm B dùng `src="assets/..."` + toàn văn `<figcaption>`, ảnh ô bảng nằm đúng `<td>`, sơ đồ Nhóm A dựng đẹp bằng HTML/CSS, link DOI/URL trong `References` bấm được)?
  5. Đã chừa khoảng trắng quanh `<` / `>` trong LaTeX (`\( x < y \)`) và không bọc LaTeX trong `<code>`/`<pre>`?
