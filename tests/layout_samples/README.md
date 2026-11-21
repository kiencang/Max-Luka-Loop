# Bộ PDF Mẫu Kiểm thử cho `pdf-to-html-vi-layout`

Các tệp PDF dưới đây mô phỏng tài liệu kỹ thuật/báo chí thực tế để kiểm thử thủ công quy trình bảo toàn thiết kế (`pdf-to-html-vi-layout`) và khả năng tách ảnh/phân vùng của `extract_assets.exe`:

| Tệp PDF | Số trang | Đặc điểm thiết kế & nội dung cần kiểm thử |
| :--- | :---: | :--- |
| `journal_2col_academic.pdf` | 4 | Tiêu đề + Abstract `.span-all`, **văn bản 2 cột chảy liên tục**, **câu văn vắt ranh giới Trang 1 → 2**, công thức toán chứa `<` / `>`, `callout`, bảng học thuật 3 đường kẻ (`colspan`/`rowspan`, đơn vị Imperial), **Bảng 2 nhúng 3 ảnh thumbnail trong ô (`table_cell`)**, sơ đồ vector Nhóm A (`Figure 1`), ảnh nhiệt đa khung (A)/(B) (`Figure 2`), biểu đồ tán xạ dày Nhóm B (`Figure 3`), `footnotes` và `References` (kèm 1 ghi chú tác giả). |
| `product_datasheet_grid.pdf` | 2 | Trang 1 **bố cục bất đối xứng** (hero banner tối màu + pill/badge ngắn + sidebar trái chứa thẻ KPI/bảng hẹp + cột phải ảnh sản phẩm & sơ đồ khối vector); Trang 2 **đổi bố cục sang 3 thẻ so sánh ngang** + ma trận thông số nhiều cột + ảnh hiện trường đặt cạnh hộp cảnh báo an toàn (kiểm tra `--page-width` mở rộng, `#pdf-page-N` cô lập CSS và dịch cô đọng trong hộp hẹp). |
| `executive_magazine_mixed.pdf` | 3 | Trang 1 tạp chí (**Drop cap**, ảnh rộng hero, **2 cột có đường kẻ dọc `.col-rule`**, trích dẫn kéo ngang); Trang 2 hai bảng đối chiếu đặt cạnh nhau + sơ đồ quy trình khép kín; **Trang 3 là bản scan phụ lục thực tế** (`scanned_pages: [3]`, có dấu mộc/bóng gáy nhiễu, đồng thời chứa ảnh chụp Nhóm B và sơ đồ 3 bước Nhóm A để test *Triage before Crop*). |
