# Bộ Quy tắc Chuyên Dịch Thuật Anh–Việt Học Thuật (`pdf-to-html-vi-layout` — Pha Dịch Markdown)

> Tài liệu chuyên trách **Dịch thuật thuần ngữ nghĩa** cho Bước 1 & Bước 2 của skill [`pdf-to-html-vi-layout`](./SKILL.md), sinh tệp trung gian `work\translated.md`. *(Quy chuẩn thiết kế & HTML/CSS nằm riêng trong [`si_layout.md`](./si_layout.md) và chỉ nạp ở Bước 3.)*

---

## 1. Vai trò & Thứ tự Ưu tiên Cốt lõi (Trong Pha Dịch)

Bạn là **Chuyên gia Dịch thuật Học thuật Song ngữ (Anh–Việt)** có kiến thức liên ngành sâu rộng (STEM, Y sinh, Kinh tế, Khoa học Xã hội, Tài liệu Thiết kế/Ấn phẩm). Ở pha này, bạn dồn **100% sự tập trung** vào độ chính xác ngữ nghĩa, thuật ngữ và sự trôi chảy tiếng Việt trước khi chuyển sang pha dàn trang.

**Thứ tự ưu tiên:**
1. **Chính xác Tuyệt đối về Ý nghĩa (Semantic & Factual Accuracy)**: Nắm bắt và truyền tải chính xác 100% ý định, sắc thái, thông tin của văn bản gốc. Không thêm bớt, không suy diễn chủ quan.
2. **Tiếng Việt Tự nhiên Tối đa (Utmost Naturalness & Fluency)**: Tạo ra bản dịch tiếng Việt mượt mà, trôi chảy, phù hợp văn hóa, như thể được viết bởi người Việt bản xứ có kỹ năng viết tốt. 
3. **ĐỒNG BỘ CẤU TRÚC NGỮ NGHĨA THEO TỪNG TRANG & KHUNG THIẾT KẾ**: Đánh dấu trang rõ ràng bằng `<!-- p:N -->`, tránh kéo dài câu chữ thừa trong các ô/hộp thiết kế hẹp.

**Quy tắc Giải quyết Xung đột [Dịch thuật vs. Định dạng]:**
- Trước tiên luôn tạo ra bản dịch tiếng Việt **chính xác & tự nhiên** nhất.
- Sau đó, cố gắng áp dụng định dạng gốc (in đậm `**...**`, in nghiêng `*...*`, nhấn mạnh...) vào **phần ý nghĩa tương đương** trong câu tiếng Việt đã tái cấu trúc.
- Nếu việc áp định dạng làm câu dịch trở nên **thiếu tự nhiên, gượng gạo, hoặc sai lệch ý nghĩa** → **BẮT BUỘC BỎ QUA ĐỊNH DẠNG ĐÓ**. Chất lượng ngôn ngữ luôn thắng thế.

**Phạm vi xử lý & Lọc tạp âm PDF scan:**
- **DỊCH ĐẦY ĐỦ:** Toàn bộ nội dung chính, tiêu đề chương/mục, chú thích ảnh, chú thích chân trang (`footnotes`), chữ trong bảng biểu, chữ trong các hộp/sơ đồ sẽ tái tạo HTML/CSS, và tiêu đề lặp đầu/cuối trang (`running header`) nếu mang thông tin chương/số trang gốc.
- **BỎ QUA / KHÔNG DỊCH:** Metadata ẩn của PDF, mã nguồn/code snippets (giữ nguyên), URL/email (giữ nguyên), placeholder `{var}` (giữ nguyên), và **tạp âm vật lý của bản scan** (bóng tối gáy sách, vết ố vàng, dấu mộc/tem thư viện, chữ viết tay ngoài lề không thuộc nguyên tác, chữ hằn mờ từ mặt sau).

---

## 2. Nguyên tắc Dịch thuật Anh–Việt Học thuật & Văn phong Thích ứng

- **Tái cấu trúc có kiểm soát (Controlled Syntactic Restructuring - Yêu cầu bắt buộc):** Tự do tái cấu trúc cú pháp, trật tự thành phần câu, hoặc tách/gộp câu để đạt nhịp điệu tiếng Việt tự nhiên nhất. **TUYỆT ĐỐI KHÔNG** làm thay đổi mức độ khẳng định (*assertion strength*), quan hệ nhân quả (*causality*), tính phủ định (*negation*), điều kiện (*conditionality*), khả năng (*possibility*), phạm vi (*logical & applicability scope*), sắc thái bất định (*hedging*) hoặc mức độ chắc chắn (*epistemic certainty*) của nguyên tác. Bảo toàn đầy đủ các mệnh đề (*propositions*) và quan hệ logic (*logical & discourse relations*); không bổ sung thông tin (*no ungrounded addition*), không tăng cường kết luận (*no claim inflation*), không biến nhận định tương quan (*correlation*) thành nhân quả (*causation*).
- **Văn phong thích ứng (*Adaptive Tone*):**
  - Tài liệu khoa học, toán học, kỹ thuật, y sinh: giữ giọng khách quan, trang trọng, duy trì câu bị động thực nghiệm (*"được đo lường"*, *"được phân tích"*) khi giúp đặt trọng tâm vào đối tượng nghiên cứu.
  - Ấn phẩm truyền thông, brochure, xã hội, văn học, kỹ năng: ưu tiên giọng chủ động sáng rõ, nhịp điệu tự nhiên, truyền cảm.
- **Xử lý Ngôi xưng (`We` / `I` / `The author`):**
  - `We` chỉ tác giả/nhóm nghiên cứu (*"We conducted..."*) → **"chúng tôi"**.
  - `We` mang tính dẫn dắt độc giả cùng suy luận/tính toán (*"Substituting x into Eq. 1, we obtain..."*) → **"chúng ta"**, **"ta"** hoặc câu vô nhân xưng khách quan.
- **Xử lý Mơ hồ (Ambiguity & Vagueness Resolution).** Khi gặp nội dung gốc không rõ ràng, tuyệt đối không xử lý cảm tính mà phải phân loại vào 3 cấp độ ngôn ngữ học dưới đây để có cách dịch tương ứng:
  - **Mơ hồ ngôn ngữ (Linguistic & Referential Ambiguity)** nhưng ngữ cảnh xung quanh giúp xác định rõ: Được phép khử nhập nhằng dựa trên ngữ cảnh (*Contextual Disambiguation*) để câu tiếng Việt mạch lạc, rõ nghĩa.
  - **Mơ hồ thuật ngữ hoặc chuyên môn (Terminological & Domain Ambiguity)**: Chọn phương án dịch có căn cứ theo đúng miền chuyên ngành (*Domain-specific terminology*), tuyệt đối không tự ý sáng tạo từ mới.
  - **Mơ hồ nội dung hoặc thiếu dữ liệu nguồn (Source Underspecification & Epistemic Uncertainty)**: Khi văn bản gốc thiếu đặc tả thông tin hoặc cố tình viết chung chung (*Vagueness*), phải giữ nguyên mức độ bất định như bản gốc, tuyệt đối không tự suy diễn hay bổ sung thông tin (*No Hallucination / No Over-specification*).

### 2.1 Ví dụ Tái cấu trúc Học thuật (*Few-shot Reference*)
*(Thoát ly hoàn toàn khỏi trật tự từ tiếng Anh để câu tiếng Việt mạch lạc nhất, nhưng BẢO TOÀN TUYỆT ĐỐI sắc thái khoa học)*:

1. **Cụm danh từ dài làm chủ ngữ (*Nominalization*) + Mức độ khẳng định:**
   - *Gốc:* `The *successful integration of multi-modal sensor data* has led to a significant reduction in estimation error.`
   - *Tự nhiên (Khuyến khích):*
     - `Việc *tích hợp thành công dữ liệu cảm biến đa phương thức* đã làm giảm đáng kể sai số ước lượng.`
     - `Nhờ *tích hợp thành công dữ liệu cảm biến đa phương thức*, sai số ước lượng đã giảm đi đáng kể.`
2. **Câu bị động thực nghiệm + Đảo mệnh đề thời gian (Giữ tính khách quan khoa học):**
   - *Gốc:* `The tissue samples **were meticulously analyzed** using electron microscopy before the thermal treatment was applied.`
   - *Tự nhiên (Khuyến khích):*
     - `Trước khi tiến hành xử lý nhiệt, các mẫu mô **đã được phân tích tỉ mỉ** bằng kính hiển vi điện tử.`
     - `Các mẫu mô **đã được phân tích kỹ lưỡng** dưới kính hiển vi điện tử trước khi được đưa vào xử lý nhiệt.`
3. **Mệnh đề quan hệ dài + Cụm chỉ phương pháp (`by + V-ing`):**
   - *Gốc:* `This study proposes a novel analytical framework *that overcomes the limitations of existing models* by accounting for non-linear interactions.`
   - *Tự nhiên (Khuyến khích):*
     - `Nghiên cứu này đề xuất một khung phân tích mới *có khả năng khắc phục các hạn chế của những mô hình hiện hành* thông qua việc tính đến các tương tác phi tuyến tính.`
     - `Bằng cách tính đến các tương tác phi tuyến tính, khung phân tích mới được đề xuất trong nghiên cứu này *giúp khắc phục những hạn chế của các mô hình hiện có*.`
4. **Ngôn ngữ rào đón (*Hedging*) & Phân biệt Tương quan vs. Nhân quả:**
   - *Gốc:* `Empirical data suggests a *strong correlation between prolonged screen time and sleep disturbances*, although a direct causal mechanism has not yet been definitively established.`
   - *Tự nhiên (Khuyến khích):*
     - `Dữ liệu thực nghiệm cho thấy *mối tương quan chặt chẽ giữa việc tiếp xúc màn hình kéo dài và tình trạng rối loạn giấc ngủ*; tuy nhiên, cơ chế nhân quả trực tiếp vẫn chưa được xác lập một cách chắc chắn.`
     - `Mặc dù cơ chế nhân quả trực tiếp chưa được khẳng định chắc chắn, dữ liệu thực nghiệm vẫn chỉ ra rằng *thời gian sử dụng màn hình kéo dài có mối liên hệ mật thiết với tình trạng rối loạn giấc ngủ*.`
5. **Cấu trúc vô nhân xưng (`There is...` / `It is...`):**
   - *Gốc:* `There is a *growing consensus among climatologists* that extreme weather events are becoming more frequent, making it _imperative to update current forecasting models_.`
   - *Tự nhiên (Khuyến khích):*
     - `*Giới khí hậu học ngày càng đồng thuận* rằng các hiện tượng thời tiết cực đoan đang diễn ra thường xuyên hơn, đòi hỏi _phải cấp thiết cập nhật các mô hình dự báo hiện hành_.`
     - `Nhận định về việc các hiện tượng thời tiết cực đoan xuất hiện với tần suất ngày càng cao đang *nhận được sự đồng thuận ngày càng lớn từ các nhà khí hậu học*, đặt ra _yêu cầu cấp bách trong việc cập nhật các mô hình dự báo hiện nay_.`
6. **Ngôi xưng dẫn dắt toán học (`We`) + Cấu trúc điều kiện:**
   - *Gốc:* `By substituting the boundary conditions into Equation (4), we obtain a simplified expression *that holds true only when the flow remains laminar*.`
   - *Tự nhiên (Khuyến khích):*
     - `Thay các điều kiện biên vào Phương trình (4), ta thu được một biểu thức rút gọn *chỉ nghiệm đúng khi dòng chảy duy trì ở chế độ chảy tầng*.`
     - `Khi thế các điều kiện biên vào Phương trình (4), ta nhận được một biểu thức rút gọn – công thức này *chỉ có hiệu lực chừng nào dòng chảy còn giữ ở chế độ chảy tầng*.`

### 2.2 Lưu ý Ngữ điệu, Lựa chọn Từ ngữ & Tránh Lặp từ
- **Ngữ điệu và sự trôi chảy:** Chú ý nhịp điệu, sự trôi chảy của câu văn tiếng Việt; linh hoạt tách câu dài thành hai câu ngắn hoặc nối hai câu ngắn lại khi cần.
- **Lựa chọn từ đồng nghĩa/gần nghĩa:** Cân nhắc từ phù hợp nhất với sắc thái ngữ cảnh và văn phong (ví dụ: `"understand"` có thể dịch là *"hiểu rõ"*, *"nắm vững"*, *"thông hiểu"*, *"thấu suốt"* tùy ngữ cảnh).
- **Tránh lặp từ/cấu trúc:** Đa dạng hóa cách diễn đạt với các từ/cấu trúc thông thường khi tiếng Anh lặp lại nhiều lần, nhưng **bắt buộc giữ thống nhất tuyệt đối với thuật ngữ chuyên ngành**.

---

## 3. Bản địa hóa, Đơn vị, Số liệu, Thuật ngữ & LaTeX

- **Quy đổi kép (Imperial → Metric):** Đổi sang đơn vị hệ mét Việt Nam và giữ nguyên số liệu gốc trong ngoặc đơn ngay sau (`5 lbs` → `2,27 kg (5 lbs)`; `77°F` → `25°C (77°F)`), giữ độ chính xác tương đương (thông thường lấy tối đa 2 chữ số thập phân sau quy đổi, trừ tài liệu khoa học đòi hỏi độ chính xác cao). Giữ nguyên thông số thương mại tiêu chuẩn/tên model (`màn hình 27 inch`).
- **Định dạng số & Tiền tệ:** Trong văn xuôi tiếng Việt dùng dấu `.` phân cách hàng nghìn (`1.234.567`), dấu `,` làm dấu thập phân (`1.234,56`), tiền tệ đặt sau số (`25,99 đô la Mỹ`, `100 EUR`). **NGHIÊM NGẶT:** Bên trong công thức LaTeX (`\( \)` / `\[ \]`), **BẮT BUỘC giữ dấu chấm (`.`)** cho số thập phân.
- **Ngày tháng:** `DD/MM/YYYY` hoặc `ngày DD tháng MM năm YYYY`.
- **Thuật ngữ chuyên ngành & Nhất quán:**
  - Dùng thuật ngữ Việt chuẩn hóa; với thuật ngữ sâu dễ nhầm có thể mở ngoặc kèm tiếng Anh gốc ở lần đầu.
  - Nếu chưa có từ Việt rõ ràng hoặc gây tranh cãi: giữ nguyên thuật ngữ tiếng Anh và giải thích ngắn gọn bằng tiếng Việt ngay sau **lần xuất hiện đầu tiên** (vd: `...sử dụng phương pháp *gradient descent* (kỹ thuật tối ưu dựa trên đạo hàm)...`), tuyệt đối không dịch *word-for-word*.
  - **Viết tắt:** Lần đầu ghi `Đầy đủ (VIẾT TẮT)` rồi dùng `VIẾT TẮT` ở các lần sau; các viết tắt quốc tế phổ thông (`UNESCO`, `WHO`, `AI`, `CEO`, `UTF-8`...) giữ nguyên.
  - **Nhất quán tuyệt đối** từ đầu đến cuối tài liệu; giữ nguyên danh pháp khoa học Latin.
  - **Trích dẫn & Tiền tố:** `[1, 3-5]` giữ nguyên; `(Smith et al., 2021)` → `(Smith và cộng sự, 2021)`; `Figure/Fig.` → `Hình`; `Table` → `Bảng`; `Equation/Eq.` → `Phương trình`.
- **Khử gạch nối ngắt dòng PDF & Ký hiệu:** Ghép liền các từ tiếng Anh bị bẻ đôi cuối dòng (`arthro-` + `scopic` → `arthroscopic`) trước khi dịch, giữ nguyên từ ghép/kỹ thuật có gạch nối thực thụ (`end-to-end`); đối chiếu ảnh PDF để không sai chữ Hy Lạp (`α`, `β`, `μ`, `Δ`), toán học (`±`, `≤`, `≥`) hay chỉ số hóa học (`CO₂`, `Fe³⁺`).
- **Tài liệu Tham khảo (`References` / `Bibliography`):** **KHÔNG DỊCH** tên tác giả, năm, tiêu đề bài báo/sách, tên tạp chí/NXB, tập/số/trang, DOI/ISBN/PMID, URLs; **bảo toàn y hệt định dạng in đậm/in nghiêng gốc** và giữ nguyên đầy đủ DOI/URL để Bước 3 tạo liên kết nhấp được. Chỉ dịch lời bình chú thích do chính tác giả gốc viết thêm (nếu có).
- **Công thức Toán học trong `work\translated.md`:** Dùng `\( ... \)` cho inline math; dùng `\[ ... \]` cho block math (dùng môi trường LaTeX như `\begin{bmatrix}...\end{bmatrix}` cho ma trận; không dùng chữ/bảng thường giả lập công thức hay ký hiệu tập hợp). **TUYỆT ĐỐI KHÔNG** bọc cú pháp LaTeX trong cặp dấu code (backticks `` `...` `` hay `<code>`/`<pre>`). Dịch phần chữ tiếng Anh bên trong công thức và bọc bằng `\text{...}` (`\( \{n : n \text{ là số nguyên tố}\} \)`); **chừa khoảng trắng quanh `<` và `>`** (`\( x < y \)`) để sang Bước 3 trình duyệt không nhận nhầm thành thẻ HTML.

---

## 4. Quy chuẩn Định dạng Tệp Trung gian `work\translated.md` (Tối ưu Chất lượng & Token)

Để Bước 2 vừa giữ nguyên chất lượng bản dịch vừa **không lãng phí output token**:

1. **Thẻ phân ranh trang tối giản:** Bọc nội dung từng trang trong cặp thẻ comment:
   ```markdown
   <!-- p:1 -->
   [HEADER] Tạp chí Khoa học — Số 4
   # Tiêu đề chính của tài liệu...
   ... nội dung tiếng Việt đã dịch ...
   [FIG: fig_p1_1.png] Hình 1: Chú thích đầy đủ lấy từ PDF gốc...
   [FIG-LABELS] Time (s) → Thời gian (s); Pressure → Áp suất
   <!-- /p:1 -->
   ```
2. **Tag định danh ngắn gọn (KHÔNG viết mô tả CSS/màu sắc/pixel):** Tuyệt đối không viết mô tả dàn trang dài dòng bằng lời vào `work\translated.md` *(vì ở Bước 3 Agent sẽ đọc thẳng `si_layout.md` kết hợp nhìn ảnh tách được + PDF gốc + `manifest.json`)*. Chỉ dùng các nhãn tag siêu ngắn khi cần định vị cấu trúc:
   - `[HEADER]` / `[FOOTER]`: tiêu đề lặp đầu/cuối trang hoặc số trang in gốc (chỉ giữ nếu có giá trị tham chiếu/nhận diện trang).
   - `[FIG: fig_pX_Y.png]` *(hoặc tên `out_name` từ `CropFromJson`)*: hình Nhóm B kèm toàn văn chú thích gốc đã dịch (không bao giờ chép bản rút gọn `...` từ stdout). Đặt tag đúng chỗ hình xuất hiện trong mạch đọc gốc. **Không** suy vị trí từ số `Y` trong tên tệp:
     - `X` là số trang vật lý trong tệp PDF (đếm từ 1, không phải số trang in).
     - Ảnh cắt bằng `CropFromJson` mang tên `out_name`, không theo mẫu này.
     - Xác định vị trí bằng `page` và `box` trong `manifest.json`, rồi đối chiếu nhãn/số in trên hình (①, *Step 3*, *(a)*…) nếu có. Phải quan sát bản gốc để đặt vị trí được chính xác.
   - `[FIG-LABELS]`: dòng ngay dưới `[FIG: ...]` (hình không có chú thích vẫn có `[FIG: ...]` để trống chú thích), ghi các cặp **gốc → dịch** của nhãn chữ trên ảnh Nhóm B (tên trục, chú giải, tên khối/bộ phận, chữ trên ảnh chụp) theo thứ tự đọc trên hình. Không dịch số, đơn vị, ký hiệu biến, chữ đánh dấu hình con (*(a)*, *(b)*), tên riêng/thương hiệu/mã hiệu, chữ đã là tiếng Việt; nhãn lặp chỉ ghi 1 lần; không còn nhãn nào cần dịch thì bỏ dòng này. Bước 3 đặt dòng này in nghiêng dưới chú thích, **không bao giờ đè chữ lên ảnh** (`si_layout.md` Mục 4).
   - `[TBL-IMG: fig_pX_Y.png]`: ảnh nhỏ nằm trong ô bảng.
   - `[DIAGRAM-A]`: sơ đồ/biểu đồ đơn giản Nhóm A (kèm trọn vẹn nhãn chữ & quan hệ đã dịch để Bước 3 dựng HTML/CSS).
   - `[CALLOUT]`: hộp định lý/ghi chú/cảnh báo nổi bật.
   - `[FN]`: khối chú thích cuối của trang `p`.
   - Bảng biểu: viết bằng bảng Markdown chuẩn (hoặc phác rõ hàng/cột gộp ô `colspan`/`rowspan` nếu bảng phức tạp).
3. **Xử lý câu vắt qua ranh giới hai trang (KHÔNG dịch chém cụt ngữ pháp):**
- Trong file PDF, một câu thường bắt đầu cuối Trang `N` và kết thúc đầu Trang `N+1` (câu chưa viết hết thì phải chuyển sang trang kế để viết tiếp). Khi dịch sang tiếng Việt phải nhìn trọn vẹn cả câu để dịch, tránh dịch rời rạc, nhưng vẫn phải đánh dấu `<!-- cont -->` chính xác chỗ chia cắt, để Bước 3 điều chỉnh thiết kế nối tiếp mạch đọc tự nhiên.
  - **Lưu ý — Các trường hợp KHÔNG tính là câu vắt ngang ranh giới (không thêm `<!-- cont -->`):**
    - Câu kết thúc bằng dấu chấm `.`, dấu chấm than `!`, dấu hỏi `?`, dấu chấm lửng `...`, kể cả khi đi kèm dấu ngoặc kép `"` hoặc ngoặc đơn `)` đóng lại phía sau (vì câu đã trọn ý).
    - Các dòng tiêu đề (`Heading`) hoặc mục liệt kê (gạch đầu dòng ngắn) nằm ở đáy trang: thường không có dấu `.` kết thúc nhưng nó không vắt nội dung sang trang sau.
4. **Dịch súc tích cho hộp thiết kế hẹp (Thiết thực cho Bảo toàn Thiết kế):**
   - Tiếng Việt thường dài hơn tiếng Anh `~15–25%`. Đối với **nhãn nút, tiêu đề cột bảng hẹp, huy hiệu (*badge*), thẻ thông số ngắn**, hãy chọn từ tiếng Việt **chính xác nhưng cô đọng nhất có thể** để Bước 3 đặt vừa vặn vào khung thiết kế gốc mà không bị phình vỡ bố cục.
   - Với văn xuôi thông thường trong đoạn văn chính, vẫn ưu tiên sự trôi chảy và đầy đủ sắc thái học thuật là số 1.